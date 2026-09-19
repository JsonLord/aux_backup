"""A plain configuration surface for model providers, at /webui.

Modelled on the llama.cpp / OpenWebUI provider-connection flow: name an
OpenAI-compatible endpoint, fetch its model list, and pick a model per role. The
store, the roles and the encryption already exist (apps/api/model_settings.py);
this is a surface over them and the place a run's models are chosen.

It fronts the deployment's own provider credentials, so three rules hold, and
each is enforced by construction rather than by remembering:

 1. **Off unless asked for.** Without AUX_WEBUI_ENABLED=1 the routes are never
    registered. Not 403 -- absent. A surface that does not exist cannot be
    misconfigured, and this one is the largest new attack surface in the cycle.
 2. **No route returns a key.** The settings route returns `store.list()`, whose
    SELECT does not name the `secret` column, so it is safe because of what it
    calls rather than because of what it remembers to strip. An endpoint is
    echoed as scheme and host only, because a base URL can carry a key in a
    query string -- the same reason build_model_provider_probe() does it.
    Nothing is ever accepted or returned that would let a key be read back out:
    a Space-secret provider is configured by the *name* of the variable.
 3. **The passthrough is bounded.** It answers "does this provider answer" in
    one click. It is size-capped, rate-limited per workspace, unstreamed and
    keeps no history. The moment it grows a conversation it is a chat product
    fronting somebody else's credentials.

The admission rule is the same one the rest of the deployment uses: whoever may
not spend the built-in credentials may not spend them through this page either,
and `why_not_built_in()` already writes that message.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests
from fastapi import APIRouter, Body, Header, HTTPException
from fastapi.responses import FileResponse

from apps.api.model_settings import (
    KIND_REFERENCE, KIND_SECRET, ROLES,
    ModelSettingsError, ModelSettingsStore, may_use_built_in_providers, why_not_built_in,
)

STATIC = Path(__file__).parent / "static"

# What each role does in a run, named for the job rather than for a model size --
# which suits which is the decision this page exists to let somebody make. Kept
# in step with apps/gradio/model_settings_panel.py, which says the same thing.
ROLE_HELP = {
    "generation": ("Writing personas", "Big and infrequent. A large model earns its cost here."),
    "acting": ("Browsing as the persona", "Every step of every run. This is where most of the budget goes."),
    "reflection": ("Reflecting and scoring", "Small, factual, constant. A fast model is the right tool."),
    "vision": ("Looking at screenshots", "Needs to accept images. Once per capture."),
}

# A connectivity check, not a chat. Enough for a sentence back, and no more.
MAX_PROMPT_CHARS = 2_000
MAX_COMPLETION_TOKENS = 256
PROBE_TIMEOUT_SECONDS = 20
# Per workspace, because that is what a provider is scoped to.
PROBE_MIN_SECONDS_APART = 3.0
_last_probe: dict[str, float] = {}


def is_enabled() -> bool:
    """Whether this surface exists at all. Advanced option, off by default."""
    return os.getenv("AUX_WEBUI_ENABLED") == "1"


def _host_only(base_url: str) -> str:
    """Scheme and host. A base URL can carry a key in a query string."""
    split = urlsplit(base_url or "")
    return f"{split.scheme}://{split.netloc}" if split.netloc else ""


def build_router(store: ModelSettingsStore | None = None, identity=None) -> APIRouter:
    """The routes, with their two dependencies injectable so tests need neither
    a real control-plane database nor a Hugging Face token."""
    router = APIRouter(prefix="/webui", tags=["webui"])
    held: dict[str, Any] = {"store": store}

    def settings_store() -> ModelSettingsStore:
        if held["store"] is None:
            held["store"] = ModelSettingsStore()
        return held["store"]

    def whoami(authorization: str | None, workspace_id: str | None) -> dict[str, Any]:
        if identity is not None:
            return identity(authorization, workspace_id)
        from apps.api.auth import IdentityProvider
        try:
            return IdentityProvider().resolve(authorization, workspace_id, "local")
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - an unreadable identity is simply not the owner
            return {"workspace_id": workspace_id or "local", "owner_user_id": "local"}

    def workspace_of(auth: dict[str, Any], workspace_id: str | None) -> str:
        return auth.get("workspace_id") or workspace_id or "local"

    @router.get("")
    @router.get("/")
    def page():
        return FileResponse(STATIC / "index.html")

    @router.get("/app.js")
    def script():
        return FileResponse(STATIC / "app.js", media_type="text/javascript")

    @router.get("/style.css")
    def stylesheet():
        return FileResponse(STATIC / "style.css", media_type="text/css")

    @router.get("/api/settings")
    def read_settings(authorization: str | None = Header(None),
                      workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        """This workspace's providers, by role. Metadata only, by construction."""
        auth = whoami(authorization, workspace_id)
        workspace = workspace_of(auth, workspace_id)
        rows = settings_store().list(workspace)
        by_role: dict[str, list[dict[str, Any]]] = {role: [] for role in ROLES}
        for row in rows:
            entry = dict(row)
            entry["endpoint"] = _host_only(entry.pop("base_url", ""))
            by_role.setdefault(entry["role"], []).append(entry)
        allowed = may_use_built_in_providers(auth)
        return {
            "workspace": workspace,
            "roles": [{"role": role, "label": ROLE_HELP[role][0], "help": ROLE_HELP[role][1],
                       "providers": by_role.get(role, [])} for role in ROLES],
            # So the page can say whether configuring one is required or optional.
            "builtInAllowed": allowed,
            "whyNotBuiltIn": None if allowed else why_not_built_in(auth),
            "encryptionAvailable": _encryption_available(),
        }

    @router.put("/api/settings")
    def save_setting(body: dict = Body(...), authorization: str | None = Header(None),
                     workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        auth = whoami(authorization, workspace_id)
        workspace = workspace_of(auth, workspace_id)
        role = str(body.get("role") or "")
        if role not in ROLES:
            raise HTTPException(422, f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
        kind = KIND_SECRET if body.get("apiKey") else KIND_REFERENCE
        try:
            saved = settings_store().save(
                workspace_id=workspace, owner_user_id=str(auth.get("owner_user_id") or "local"),
                label=str(body.get("label") or ""), role=role,
                base_url=str(body.get("baseUrl") or ""), model=str(body.get("model") or ""),
                kind=kind, secret=str(body.get("apiKey") or ""),
                secret_ref=str(body.get("secretRef") or ""),
                position=int(body.get("position") or 0))
        except (ModelSettingsError, ValueError) as error:
            raise HTTPException(422, str(error))
        # The store returns what it stored, including base_url; the page only
        # ever needs to know which row appeared.
        return {"provider_id": saved["provider_id"], "role": saved["role"],
                "label": saved["label"], "model": saved["model"],
                "endpoint": _host_only(saved["base_url"])}

    @router.delete("/api/settings/{provider_id}")
    def delete_setting(provider_id: str, authorization: str | None = Header(None),
                       workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        auth = whoami(authorization, workspace_id)
        # Scoped to the workspace by the store's own WHERE clause, so another
        # workspace's id is a 404 rather than a deletion.
        if not settings_store().delete(provider_id, workspace_of(auth, workspace_id)):
            raise HTTPException(404, "no such provider in this workspace")
        return {"deleted": provider_id}

    @router.get("/api/models")
    def list_models(provider_id: str, authorization: str | None = Header(None),
                    workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        """What a saved provider serves, asked server-side.

        Model ids only. The key is read from the store here and never crosses
        the wire in either direction -- the browser names a row, not a secret.
        """
        auth = whoami(authorization, workspace_id)
        workspace = workspace_of(auth, workspace_id)
        row = next((item for item in settings_store().list(workspace)
                    if item["provider_id"] == provider_id), None)
        if row is None:
            raise HTTPException(404, "no such provider in this workspace")
        entry = next((item for item in settings_store().chain(workspace, row["role"])
                      if item[2] == row["model"]), None)
        if entry is None:
            raise HTTPException(409, "this provider has no usable key; its Space secret may be gone")
        base_url, api_key, _ = entry
        try:
            response = requests.get(f"{base_url.rstrip('/')}/models",
                                    headers={"authorization": f"Bearer {api_key}"},
                                    timeout=PROBE_TIMEOUT_SECONDS)
            response.raise_for_status()
            listed = response.json().get("data") or []
        except requests.RequestException as error:
            # str() on a requests failure carries the URL but never the header,
            # so this cannot leak the key.
            raise HTTPException(502, f"{_host_only(base_url)} did not answer: {str(error)[:200]}")
        except ValueError:
            raise HTTPException(502, f"{_host_only(base_url)} answered with something that is not JSON")
        return {"endpoint": _host_only(base_url),
                "models": [str(item.get("id")) for item in listed if item.get("id")][:200]}

    @router.post("/api/chat/completions")
    def probe(body: dict = Body(...), authorization: str | None = Header(None),
              workspace_id: str | None = Header(None, alias="X-Workspace-ID")):
        """Does this provider answer? One short completion, and no more.

        Not a chat: no history is kept, nothing streams, the prompt is capped and
        so is the reply. This fronts somebody's provider credentials, and the
        difference between a connectivity check and a chat product is exactly
        these bounds.
        """
        auth = whoami(authorization, workspace_id)
        workspace = workspace_of(auth, workspace_id)
        now = time.monotonic()
        if now - _last_probe.get(workspace, 0.0) < PROBE_MIN_SECONDS_APART:
            raise HTTPException(429, "one check at a time; try again in a moment")
        _last_probe[workspace] = now

        provider_id = str(body.get("provider_id") or "")
        row = next((item for item in settings_store().list(workspace)
                    if item["provider_id"] == provider_id), None)
        if row is None:
            raise HTTPException(404, "no such provider in this workspace")
        entry = next((item for item in settings_store().chain(workspace, row["role"])
                      if item[2] == row["model"]), None)
        if entry is None:
            raise HTTPException(409, "this provider has no usable key; its Space secret may be gone")
        base_url, api_key, model = entry
        prompt = str(body.get("prompt") or "Reply with the single word: ready.")[:MAX_PROMPT_CHARS]
        try:
            response = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"authorization": f"Bearer {api_key}"},
                json={"model": model, "max_tokens": MAX_COMPLETION_TOKENS, "stream": False,
                      "messages": [{"role": "user", "content": prompt}]},
                timeout=PROBE_TIMEOUT_SECONDS)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except requests.RequestException as error:
            raise HTTPException(502, f"{_host_only(base_url)} did not answer: {str(error)[:200]}")
        except (ValueError, KeyError, IndexError):
            raise HTTPException(502, f"{_host_only(base_url)} answered in a shape this does not understand")
        return {"endpoint": _host_only(base_url), "model": model, "reply": str(content)[:4000]}

    return router


def _encryption_available() -> bool:
    from apps.api.credentials import encryption_available
    return encryption_available()
