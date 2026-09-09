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
    sent = {}

    class _Response:
        def read(self):
            return json.dumps({"status": "succeeded", "state": STATE_JSON}).encode()
        def __enter__(self): return self
        def __exit__(self, *_): return False

    def fake_urlopen(call, timeout=None):
        sent["url"] = call.full_url
        sent["body"] = json.loads(call.data)
        sent["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    updated = store.capture_session(meta["credential_id"], "https://shop.example.com/login")

    # The worker owns the browser, so the password crosses exactly one loopback hop.
    assert sent["url"].endswith("/v1/login-captures")
    assert sent["body"]["password"] == "hunter2"
    assert sent["body"]["username"] == "ada"
    # The wait has to outlast the worker's own second-factor patience, or a
    # half-finished login is thrown away by the client instead of the server.
    assert sent["timeout"] >= 300

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
