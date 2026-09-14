"""Who may spend the Space's own model credentials, and how everyone else brings theirs."""

import os

import pytest

from apps.api.credentials import generate_key
from apps.api.model_settings import (
    KIND_REFERENCE, KIND_SECRET, ROLE_ACTING, ROLE_GENERATION,
    ModelSettingsError, ModelSettingsStore, may_use_built_in_providers,
    space_owner, why_not_built_in,
)


@pytest.fixture
def store(tmp_path):
    return ModelSettingsStore(f"sqlite:///{tmp_path}/settings.db")


@pytest.fixture(autouse=True)
def owned_space(monkeypatch):
    monkeypatch.setenv("SPACE_ID", "Leon4gr45/aux-synthetic-ux-demo")
    monkeypatch.delenv("SPACE_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("AUX_DEFAULT_PROVIDER_OWNERS", raising=False)


def test_the_owner_of_the_space_is_read_from_the_environment():
    """A fork reserves its own owner's budget, not the budget of whoever wrote
    the file."""
    assert space_owner() == "Leon4gr45"


def test_three_callers_may_spend_the_built_in_credentials():
    owner = {"role": "user", "owner_user_id": "675f", "user": {"username": "Leon4gr45"}}
    admin = {"role": "admin", "owner_user_id": "admin"}
    stranger = {"role": "user", "owner_user_id": "999", "user": {"username": "someone-else"}}

    assert may_use_built_in_providers(owner), "the Space's owner, by either name"
    assert may_use_built_in_providers(admin), "the break-glass API token"
    assert may_use_built_in_providers(stranger, example_persona="Friedrich_Wolf.agent.json"), \
        "and anyone trying a bundled example, who would otherwise see nothing at all"

    assert not may_use_built_in_providers(stranger)
    assert not may_use_built_in_providers(None)
    assert not may_use_built_in_providers({}, example_persona="")


def test_the_owner_matches_on_id_as_well_as_username(monkeypatch):
    monkeypatch.setenv("AUX_DEFAULT_PROVIDER_OWNERS", "675f37b072d14a2cff8b7343")
    assert may_use_built_in_providers({"owner_user_id": "675f37b072d14a2cff8b7343"})


def test_a_refusal_says_what_to_do_about_it():
    message = why_not_built_in({"owner_user_id": "999"})
    assert "Leon4gr45" in message
    assert "Space secret" in message, "the path that needs no encryption key"
    assert "Settings" in message


def test_a_space_secret_provider_stores_the_name_and_never_the_value(store, monkeypatch):
    monkeypatch.setenv("MY_ROUTER_KEY", "sk-the-real-thing")
    store.save(workspace_id="w1", owner_user_id="u1", label="My router", role=ROLE_GENERATION,
               base_url="https://router.example/v1/", model="auto",
               kind=KIND_REFERENCE, secret_ref="MY_ROUTER_KEY")

    (row,) = store.list("w1")
    assert row["secret_ref"] == "MY_ROUTER_KEY"
    assert "secret" not in row, "listing returns metadata only"
    assert "sk-the-real-thing" not in str(row)
    # The trailing slash is normalised, so "/v1/" and "/v1" are one endpoint.
    assert row["base_url"] == "https://router.example/v1"
    assert store.chain("w1", ROLE_GENERATION) == [
        ("https://router.example/v1", "sk-the-real-thing", "auto")]


def test_a_secret_that_left_the_environment_is_not_offered_as_a_provider(store, monkeypatch):
    """An endpoint with no key looks like a fallback and is a 401 on every call."""
    monkeypatch.setenv("GONE_TOMORROW", "sk-today")
    store.save(workspace_id="w1", owner_user_id="u1", label="Temp", role=ROLE_ACTING,
               base_url="https://router.example/v1", model="auto",
               kind=KIND_REFERENCE, secret_ref="GONE_TOMORROW")
    assert store.chain("w1", ROLE_ACTING)

    monkeypatch.delenv("GONE_TOMORROW")
    assert store.chain("w1", ROLE_ACTING) == []
    assert store.list("w1"), "the row stays, so the UI can show what needs fixing"


def test_a_pasted_key_is_encrypted_and_comes_back_usable(store, monkeypatch):
    monkeypatch.setenv("AUX_CREDENTIAL_KEY", generate_key())
    store.save(workspace_id="w1", owner_user_id="u1", label="Pasted", role=ROLE_GENERATION,
               base_url="https://blablador.example/v1", model="alias-large",
               kind=KIND_SECRET, secret="sk-pasted")

    with store.connect() as db:
        (stored,) = db.execute("SELECT secret FROM model_providers").fetchone()
    assert "sk-pasted" not in stored, "at rest it is ciphertext"
    assert store.chain("w1", ROLE_GENERATION) == [
        ("https://blablador.example/v1", "sk-pasted", "alias-large")]


def test_a_pasted_key_is_refused_when_nothing_can_encrypt_it(store, monkeypatch):
    monkeypatch.delenv("AUX_CREDENTIAL_KEY", raising=False)
    with pytest.raises(Exception) as raised:
        store.save(workspace_id="w1", owner_user_id="u1", label="Pasted", role=ROLE_GENERATION,
                   base_url="https://x.example/v1", model="m", kind=KIND_SECRET, secret="sk")
    assert "Space secret" in str(raised.value), "and it names the way that still works"


def test_a_provider_is_an_endpoint_a_model_and_a_key_or_it_is_not_a_provider(store):
    """The failure that cost five cycles was a fallback carrying the endpoint and
    not the model."""
    for missing in ({"base_url": ""}, {"model": ""}, {"label": ""}):
        fields = {"label": "X", "base_url": "https://x.example/v1", "model": "m", **missing}
        with pytest.raises(ModelSettingsError):
            store.save(workspace_id="w1", owner_user_id="u1", role=ROLE_GENERATION,
                       kind=KIND_REFERENCE, secret_ref="K", **fields)
    with pytest.raises(ModelSettingsError):
        store.save(workspace_id="w1", owner_user_id="u1", label="X", role="not-a-role",
                   base_url="https://x.example/v1", model="m", kind=KIND_REFERENCE, secret_ref="K")


def test_order_is_the_fallback_order_and_roles_do_not_mix(store, monkeypatch):
    monkeypatch.setenv("K1", "one")
    monkeypatch.setenv("K2", "two")
    monkeypatch.setenv("K3", "three")
    common = {"workspace_id": "w1", "owner_user_id": "u1", "kind": KIND_REFERENCE}
    store.save(**common, label="Second", role=ROLE_GENERATION, base_url="https://b.example/v1",
               model="alias-huge", secret_ref="K2", position=1)
    store.save(**common, label="First", role=ROLE_GENERATION, base_url="https://a.example/v1",
               model="alias-large", secret_ref="K1", position=0)
    store.save(**common, label="Acting", role=ROLE_ACTING, base_url="https://c.example/v1",
               model="auto", secret_ref="K3", position=0)

    assert [model for _, _, model in store.chain("w1", ROLE_GENERATION)] == ["alias-large", "alias-huge"]
    assert [model for _, _, model in store.chain("w1", ROLE_ACTING)] == ["auto"]


def test_one_workspace_cannot_see_or_delete_another_s_providers(store, monkeypatch):
    monkeypatch.setenv("K", "v")
    saved = store.save(workspace_id="w1", owner_user_id="u1", label="Mine", role=ROLE_GENERATION,
                       base_url="https://x.example/v1", model="m",
                       kind=KIND_REFERENCE, secret_ref="K")

    assert store.list("w2") == []
    assert store.chain("w2", ROLE_GENERATION) == []
    assert store.delete(saved["provider_id"], "w2") is False, "deleting across workspaces does nothing"
    assert store.list("w1"), "and leaves the owner's row alone"
    assert store.delete(saved["provider_id"], "w1") is True


def test_the_dialog_never_renders_a_stored_key(tmp_path, monkeypatch):
    """Inputs are write-only. The table is metadata, the same rule the browser
    credential dialog follows, and for the same reason."""
    from apps.gradio import model_settings_panel

    monkeypatch.setenv("A_SECRET_NAME", "sk-must-not-appear")
    monkeypatch.setenv("AUX_CREDENTIAL_KEY", generate_key())
    store = ModelSettingsStore(f"sqlite:///{tmp_path}/s.db")
    store.save(workspace_id="w1", owner_user_id="u1", label="By reference", role=ROLE_GENERATION,
               base_url="https://router.example/v1", model="auto",
               kind=KIND_REFERENCE, secret_ref="A_SECRET_NAME")
    store.save(workspace_id="w1", owner_user_id="u1", label="Pasted", role=ROLE_ACTING,
               base_url="https://blablador.example/v1", model="alias-large",
               kind=KIND_SECRET, secret="sk-also-must-not-appear")

    rendered = str(model_settings_panel._rows(store, "w1"))
    assert "sk-must-not-appear" not in rendered
    assert "sk-also-must-not-appear" not in rendered
    assert "A_SECRET_NAME" in rendered, "the name is the point of a reference row"
    assert "alias-large" in rendered and "Browsing as the persona" in rendered


def test_the_banner_tells_a_visitor_where_they_stand_before_they_start():
    """Finding out after starting a run, from a 502, is the version of this that
    wastes somebody's afternoon."""
    from apps.gradio import model_settings_panel

    owner = model_settings_panel._access_banner({"user": {"username": "Leon4gr45"}})
    assert "built-in models" in owner and "aux-cred-banner ok" in owner

    stranger = model_settings_panel._access_banner({"owner_user_id": "999"})
    assert "aux-cred-banner warn" in stranger
    assert "Space secret name is enough" in stranger, "and names the path needing no encryption key"


def test_every_role_the_dialog_offers_is_a_role_the_store_accepts():
    """A label with no matching role would save silently into the wrong chain."""
    from apps.api.model_settings import ROLES
    from apps.gradio import model_settings_panel

    assert set(model_settings_panel.ROLE_LABELS.values()) == set(ROLES)
    assert set(model_settings_panel.ROLE_HELP) == set(ROLES)
