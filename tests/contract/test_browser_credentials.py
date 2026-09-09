"""A stored browser session is a bearer credential; these are its guardrails."""
import json
import os
import stat

import pytest

from apps.api.credentials import (
    CredentialError, CredentialStore, KIND_PASSWORD, KIND_REFERENCE, KIND_STATE,
    encryption_available, generate_key,
)

STATE_JSON = json.dumps({"cookies": [{"name": "sid", "value": "s3cr3t"}], "origins": []})


@pytest.fixture
def store(tmp_path):
    return CredentialStore(f"sqlite:///{tmp_path / 'control.db'}")


def _worker_recorder(monkeypatch, capture_result):
    """Record every call the store makes to the browser service."""
    calls = []

    class _Response:
        def __init__(self, body): self._body = json.dumps(body).encode()
        def read(self): return self._body
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_urlopen(call, timeout=None):
        calls.append({"url": call.full_url, "method": call.get_method(),
                      "body": json.loads(call.data) if call.data else None})
        if call.full_url.endswith("/v1/login-captures"):
            return _Response(capture_result)
        return _Response({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setenv("AUX_CREDENTIAL_KEY", generate_key())


def test_secrets_are_refused_rather_than_stored_in_the_clear(store, monkeypatch):
    # A password store that silently degrades to plaintext is worse than one that
    # refuses: nobody finds out until the database leaks.
    monkeypatch.delenv("AUX_CREDENTIAL_KEY", raising=False)
    assert encryption_available() is False

    with pytest.raises(CredentialError, match="AUX_CREDENTIAL_KEY"):
        store.put(label="Shop login", kind=KIND_STATE, secret=STATE_JSON)

    assert store.list_credentials() == []


def test_a_reference_credential_needs_no_key_and_stores_no_secret(store, monkeypatch):
    # The recommended path: the value stays in the environment (a Space secret)
    # and only its name is written down.
    monkeypatch.delenv("AUX_CREDENTIAL_KEY", raising=False)
    monkeypatch.setenv("HF_SHOP_SESSION", STATE_JSON)

    meta = store.put(label="Shop (Space secret)", kind=KIND_REFERENCE, secret_ref="HF_SHOP_SESSION")

    assert meta["kind"] == KIND_REFERENCE
    assert meta["secret_ref"] == "HF_SHOP_SESSION"
    assert meta["resolvable"] is True
    with store.connect() as db:
        row = db.execute("SELECT secret FROM browser_credentials").fetchone()
    assert row["secret"] is None, "a reference must never write the value itself"


def test_listing_never_returns_the_secret(store, keyed):
    store.put(label="Shop login", kind=KIND_STATE, secret=STATE_JSON)

    listed = store.list_credentials()
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert "s3cr3t" not in json.dumps(listed)


def test_state_is_encrypted_at_rest(store, keyed):
    store.put(label="Shop login", kind=KIND_STATE, secret=STATE_JSON)

    with store.connect() as db:
        stored = db.execute("SELECT secret FROM browser_credentials").fetchone()["secret"]
    assert "s3cr3t" not in stored
    assert "cookies" not in stored


def test_a_run_gets_an_owner_only_state_file(store, keyed, tmp_path):
    meta = store.put(label="Shop login", kind=KIND_STATE, secret=STATE_JSON)

    path = store.write_state_file(meta["credential_id"], tmp_path / "sessions")

    assert json.loads(open(path, encoding="utf-8").read())["cookies"][0]["value"] == "s3cr3t"
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600, f"session file must not be readable by others (got {oct(mode)})"
    assert store.list_credentials()[0]["last_used_at"] is not None


def test_a_reference_resolves_from_the_environment_at_run_time(store, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_SHOP_SESSION", STATE_JSON)
    meta = store.put(label="Shop", kind=KIND_REFERENCE, secret_ref="HF_SHOP_SESSION")

    path = store.write_state_file(meta["credential_id"], tmp_path / "sessions")
    assert json.loads(open(path, encoding="utf-8").read())["cookies"][0]["value"] == "s3cr3t"


def test_a_reference_whose_variable_is_missing_says_so(store, tmp_path, monkeypatch):
    monkeypatch.setenv("HF_SHOP_SESSION", STATE_JSON)
    meta = store.put(label="Shop", kind=KIND_REFERENCE, secret_ref="HF_SHOP_SESSION")
    monkeypatch.delenv("HF_SHOP_SESSION")

    assert store.list_credentials()[0]["resolvable"] is False
    with pytest.raises(CredentialError, match="HF_SHOP_SESSION"):
        store.write_state_file(meta["credential_id"], tmp_path / "sessions")


def test_storage_state_must_be_json(store, keyed):
    with pytest.raises(CredentialError, match="not valid JSON"):
        store.put(label="Broken", kind=KIND_STATE, secret="not json")


def test_a_password_has_no_session_to_hand_a_run_yet(store, keyed, tmp_path):
    meta = store.put(label="Shop", kind=KIND_PASSWORD, username="ada", secret="hunter2")

    assert meta["username"] == "ada"
    with pytest.raises(CredentialError, match="capture one by signing in"):
        store.write_state_file(meta["credential_id"], tmp_path / "sessions")


def test_credentials_do_not_leak_across_workspaces(store, keyed, tmp_path):
    meta = store.put(workspace_id="alpha", label="Shop", kind=KIND_STATE, secret=STATE_JSON)

    assert store.list_credentials("beta") == []
    assert store.delete(meta["credential_id"], workspace_id="beta") is False
    with pytest.raises(CredentialError, match="not found"):
        store.write_state_file(meta["credential_id"], tmp_path / "s", workspace_id="beta")

    assert store.delete(meta["credential_id"], workspace_id="alpha") is True


def test_a_captured_session_turns_a_password_into_a_usable_credential(store, keyed, tmp_path, monkeypatch):
    meta = store.put(label="Shop", kind=KIND_PASSWORD, username="ada", secret="hunter2")
    calls = _worker_recorder(monkeypatch, {"status": "succeeded", "state": STATE_JSON})

    updated = store.capture_session(meta["credential_id"], "https://shop.example.com/login")

    # The worker owns the browser, so the password crosses exactly one loopback hop.
    capture = next(c for c in calls if c["url"].endswith("/v1/login-captures"))
    assert capture["body"]["password"] == "hunter2"
    assert capture["body"]["username"] == "ada"

    # It is now a session credential, and a run can be handed the file.
    assert updated["kind"] == KIND_STATE
    path = store.write_state_file(meta["credential_id"], tmp_path / "sessions")
    assert json.loads(open(path, encoding="utf-8").read())["cookies"][0]["value"] == "s3cr3t"


def test_an_unanswered_second_factor_is_reported_not_swallowed(store, keyed, monkeypatch):
    # "Go and answer the challenge" and "the password is wrong" need different
    # reactions, so the worker's own wording is surfaced rather than flattened.
    meta = store.put(label="Shop", kind=KIND_PASSWORD, username="ada", secret="hunter2")

    class _Response:
        def read(self):
            return json.dumps({"status": "second_factor_timed_out",
                               "detail": "The second factor was not answered in time; "
                                         "nothing was saved."}).encode()
        def __enter__(self): return self
        def __exit__(self, *_): return False

    monkeypatch.setattr("urllib.request.urlopen", lambda call, timeout=None: _Response())

    with pytest.raises(CredentialError, match="second factor was not answered"):
        store.capture_session(meta["credential_id"], "https://shop.example.com/login")

    # Nothing was written: the credential is still just a password.
    assert store.list_credentials()[0]["kind"] == KIND_PASSWORD


def test_a_failing_sign_in_service_never_echoes_the_password(store, keyed, monkeypatch):
    meta = store.put(label="Shop", kind=KIND_PASSWORD, username="ada", secret="hunter2")

    def explode(call, timeout=None):
        raise OSError("connection refused to http://worker/v1/login-captures")

    monkeypatch.setattr("urllib.request.urlopen", explode)

    with pytest.raises(CredentialError) as raised:
        store.capture_session(meta["credential_id"], "https://shop.example.com/login")
    assert "hunter2" not in str(raised.value)


def test_only_a_password_credential_can_be_signed_in(store, keyed):
    meta = store.put(label="Shop", kind=KIND_STATE, secret=STATE_JSON)
    with pytest.raises(CredentialError, match="only a password credential"):
        store.capture_session(meta["credential_id"], "https://shop.example.com/login")


def test_signing_in_by_hand_stores_a_session_and_never_a_password(store, keyed, monkeypatch):
    # For a site with no credential registered: the person types their own
    # username and password into the browser, and only the session is kept.
    calls = _worker_recorder(monkeypatch, {"status": "succeeded", "state": STATE_JSON})

    meta = store.sign_in_by_hand(label="Shop (by hand)", login_url="https://shop.example.com/login")

    assert meta["kind"] == KIND_STATE
    capture = next(c for c in calls if c["url"].endswith("/v1/login-captures"))
    assert "password" not in capture["body"], "this service must not be typing anything"
    assert capture["body"]["url"] == "https://shop.example.com/login"
    # Nothing resembling a password is in the record.
    with store.connect() as db:
        row = db.execute("SELECT username, kind FROM browser_credentials").fetchone()
    assert row["username"] is None


def test_the_browser_is_handed_over_for_the_sign_in_and_handed_back_after(store, keyed, monkeypatch):
    # Input is refused without a handover, so it has to bracket the sign-in.
    calls = _worker_recorder(monkeypatch, {"status": "succeeded", "state": STATE_JSON})

    store.sign_in_by_hand(label="Shop", login_url="https://shop.example.com/login")

    order = [(c["method"], c["url"].rsplit("/", 1)[-1]) for c in calls]
    assert order == [("POST", "takeovers"), ("POST", "login-captures"), ("DELETE", "takeovers")]


def test_the_browser_is_handed_back_even_when_the_sign_in_fails(store, keyed, monkeypatch):
    # Leaving it handed over would block the agent from ever acting again.
    calls = _worker_recorder(monkeypatch, {"status": "failed", "detail": "gave up"})

    with pytest.raises(CredentialError, match="gave up"):
        store.sign_in_by_hand(label="Shop", login_url="https://shop.example.com/login")

    assert ("DELETE", "takeovers") in [(c["method"], c["url"].rsplit("/", 1)[-1]) for c in calls]


def test_a_password_sign_in_is_also_handed_over_for_the_challenge_it_may_hit(store, keyed, monkeypatch):
    meta = store.put(label="Shop", kind=KIND_PASSWORD, username="ada", secret="hunter2")
    calls = _worker_recorder(monkeypatch, {"status": "succeeded", "state": STATE_JSON})

    store.capture_session(meta["credential_id"], "https://shop.example.com/login")

    order = [(c["method"], c["url"].rsplit("/", 1)[-1]) for c in calls]
    assert order == [("POST", "takeovers"), ("POST", "login-captures"), ("DELETE", "takeovers")]


def test_signing_in_by_hand_needs_somewhere_to_sign_in(store, keyed):
    with pytest.raises(CredentialError, match="URL of the sign-in page"):
        store.sign_in_by_hand(label="Shop", login_url="")
    with pytest.raises(CredentialError, match="needs a label"):
        store.sign_in_by_hand(label="", login_url="https://shop.example.com/login")
