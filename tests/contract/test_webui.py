"""The /webui configuration surface (CAP-1).

It fronts the deployment's own provider credentials, so these assert the three
rules that keep it from becoming a way to spend them: it does not exist unless
asked for, it never returns a key, and its passthrough is a connectivity check
rather than a chat product.
"""

import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.credentials import generate_key
from apps.api.model_settings import KIND_REFERENCE, ROLE_ACTING, ROLE_GENERATION, ModelSettingsStore
from apps.webui import build_router, is_enabled


@pytest.fixture
def store(tmp_path):
    return ModelSettingsStore(f"sqlite:///{tmp_path}/settings.db")


@pytest.fixture(autouse=True)
def a_deployment_with_its_own_credentials(monkeypatch):
    monkeypatch.setenv("SPACE_ID", "Leon4gr45/aux-synthetic-ux-demo")
    monkeypatch.delenv("SPACE_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("AUX_DEFAULT_PROVIDER_OWNERS", raising=False)


def client(store, *, auth=None):
    app = FastAPI()
    app.include_router(build_router(
        store, identity=lambda authorization, workspace: auth or {"workspace_id": "w1",
                                                                  "owner_user_id": "a-stranger"}))
    return TestClient(app)


def _saved(store, monkeypatch, *, role=ROLE_ACTING, secret="sk-mine"):
    monkeypatch.setenv("MY_KEY", secret)
    return store.save(workspace_id="w1", owner_user_id="u1", label="Mine", role=role,
                      base_url="https://router.example/v1?token=sk-in-the-url", model="my-model",
                      kind=KIND_REFERENCE, secret_ref="MY_KEY")


# --- rule 1: it does not exist unless asked for -------------------------------

def test_the_surface_is_off_unless_this_deployment_asked_for_it(monkeypatch):
    monkeypatch.delenv("AUX_WEBUI_ENABLED", raising=False)
    assert is_enabled() is False
    monkeypatch.setenv("AUX_WEBUI_ENABLED", "yes")
    assert is_enabled() is False, "only an explicit 1 turns it on"
    monkeypatch.setenv("AUX_WEBUI_ENABLED", "1")
    assert is_enabled() is True


def test_when_it_is_off_the_routes_are_absent_rather_than_forbidden(monkeypatch):
    """A 403 is a surface that exists and said no. This one should not exist:
    what is never registered cannot be misconfigured."""
    monkeypatch.delenv("AUX_WEBUI_ENABLED", raising=False)
    app = FastAPI()
    if is_enabled():
        app.include_router(build_router())

    assert [route.path for route in app.routes if str(route.path).startswith("/webui")] == []
    assert TestClient(app).get("/webui/api/settings").status_code == 404


# --- rule 2: no route returns a key -------------------------------------------

def test_no_route_hands_back_a_stored_key_or_a_key_bearing_url(store, monkeypatch):
    """`store.list()` does not select the secret column, so the settings route is
    safe because of what it calls. The endpoint is cut to scheme and host because
    a base URL can carry a key in a query string -- and this one does."""
    _saved(store, monkeypatch, secret="sk-must-not-appear")

    body = client(store).get("/webui/api/settings").text

    assert "sk-must-not-appear" not in body
    assert "sk-in-the-url" not in body
    assert "https://router.example" in body, "the host is still shown, so a person can read the row"


def test_the_saved_row_comes_back_without_its_key(store, monkeypatch):
    monkeypatch.setenv("AUX_CREDENTIAL_KEY", generate_key())

    response = client(store).put("/webui/api/settings", json={
        "role": ROLE_GENERATION, "label": "Pasted", "baseUrl": "https://blab.example/v1",
        "model": "alias-large", "apiKey": "sk-pasted"})

    assert response.status_code == 200
    assert "sk-pasted" not in response.text


def test_an_unknown_role_is_refused_rather_than_stored_somewhere_odd(store):
    response = client(store).put("/webui/api/settings", json={
        "role": "whatever", "label": "x", "baseUrl": "https://x.example/v1", "model": "m",
        "secretRef": "K"})
    assert response.status_code == 422


# --- workspace scoping --------------------------------------------------------

def test_another_workspaces_provider_cannot_be_deleted_read_or_probed(store, monkeypatch):
    saved = _saved(store, monkeypatch)
    theirs = client(store, auth={"workspace_id": "somebody-else", "owner_user_id": "them"})

    assert theirs.delete(f"/webui/api/settings/{saved['provider_id']}").status_code == 404
    assert theirs.get(f"/webui/api/models?provider_id={saved['provider_id']}").status_code == 404
    assert theirs.post("/webui/api/chat/completions",
                       json={"provider_id": saved["provider_id"]}).status_code == 404
    assert theirs.get("/webui/api/settings").json()["roles"][0]["providers"] == []


def test_a_provider_whose_space_secret_is_gone_is_reported_not_called(store, monkeypatch):
    """An endpoint with no key looks like a fallback and is a 401 on every call."""
    saved = _saved(store, monkeypatch)
    monkeypatch.delenv("MY_KEY")

    response = client(store).get(f"/webui/api/models?provider_id={saved['provider_id']}")

    assert response.status_code == 409
    assert "key" in response.json()["detail"]


# --- the admission rule is the deployment's, not this page's ------------------

def test_the_page_says_whether_this_caller_may_use_the_built_in_providers(store):
    stranger = client(store).get("/webui/api/settings").json()
    assert stranger["builtInAllowed"] is False
    assert "reserved" in stranger["whyNotBuiltIn"]

    owner = client(store, auth={"workspace_id": "w1", "owner_user_id": "x",
                                "user": {"username": "Leon4gr45"}})
    assert owner.get("/webui/api/settings").json()["builtInAllowed"] is True


# --- rule 3: the passthrough is bounded ---------------------------------------

def test_the_check_is_rate_limited_per_workspace(store, monkeypatch):
    import apps.webui.router as router_module
    saved = _saved(store, monkeypatch)
    monkeypatch.setattr(router_module, "_last_probe", {})
    calls = []

    class Answer:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "ready."}}]}

    def post(url, **kwargs):
        calls.append(kwargs)
        return Answer()

    monkeypatch.setattr(router_module.requests, "post", post)
    app = client(store)

    first = app.post("/webui/api/chat/completions", json={"provider_id": saved["provider_id"]})
    second = app.post("/webui/api/chat/completions", json={"provider_id": saved["provider_id"]})

    assert first.status_code == 200 and first.json()["reply"] == "ready."
    assert second.status_code == 429, "a second check straight away is refused"
    assert len(calls) == 1


def test_the_check_does_not_stream_and_caps_what_it_asks_for(store, monkeypatch):
    """The difference between a connectivity check and a chat product fronting
    somebody's credentials is exactly these bounds."""
    import apps.webui.router as router_module
    saved = _saved(store, monkeypatch)
    monkeypatch.setattr(router_module, "_last_probe", {})
    sent = {}

    class Answer:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(router_module.requests, "post",
                        lambda url, **kwargs: (sent.update(kwargs), Answer())[1])

    client(store).post("/webui/api/chat/completions", json={
        "provider_id": saved["provider_id"], "prompt": "x" * 9000})

    assert sent["json"]["stream"] is False
    assert sent["json"]["max_tokens"] == router_module.MAX_COMPLETION_TOKENS
    assert len(sent["json"]["messages"][0]["content"]) == router_module.MAX_PROMPT_CHARS
    assert len(sent["json"]["messages"]) == 1, "no history is carried"


def test_the_router_is_registered_before_the_gradio_catch_all():
    """Gradio mounts a catch-all at "/". Registered after it, /webui is swallowed
    and the page 404s in the deployed Space while every test here still passes --
    so the ordering is asserted on the source, which is where it lives."""
    source = pathlib.Path("app.py").read_text()

    included = source.index("fastapi_app.include_router(build_router())")
    mounted = source.index('gr.mount_gradio_app(fastapi_app, demo, path="/"')

    assert included < mounted
