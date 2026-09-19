"""Which providers one caller may run on, composed in one place.

`ModelSettingsStore.chain()` knows what a workspace configured for a role, and
`services/persona_service/providers.py` knows what the deployment itself can
reach. Neither knows whether *this* caller is allowed the second, and that is the
question this module exists to answer, because getting it wrong in the permissive
direction makes the admission gate in app.py decorative: refused at the door,
served at the back.

So the order is the design:

  1. the workspace's own providers, for this role
  2. the deployment's own -- only when the caller is allowed them

and a caller who is allowed neither gets an empty chain, which fails loudly
rather than quietly spending somebody else's budget.

This composes; it does not resolve. Endpoint, model and key still travel together
as one set, and the environment is still read only by providers.py.
"""
from __future__ import annotations

from typing import Any

from apps.api.model_settings import ModelSettingsStore, may_use_built_in_providers
from services.persona_service.providers import model_providers

# Opened once. The store is a thin SQLite adapter and every call reconnects, so
# this holds no connection -- it avoids re-running the schema check per call.
_store: ModelSettingsStore | None = None


def settings_store() -> ModelSettingsStore:
    global _store
    if _store is None:
        _store = ModelSettingsStore()
    return _store


def providers_for(workspace_id: str, role: str, *, built_in_allowed: bool,
                  store: ModelSettingsStore | None = None) -> list[tuple[str, str, str]]:
    """This caller's chain for one role, most preferred first.

    Each entry is (base_url, api_key, model) -- the same shape `model_providers()`
    produces, so a configured workspace and a default one are walked by identical
    code and a fallback behaves the same either way.
    """
    chain: list[tuple[str, str, str]] = list((store or settings_store()).chain(workspace_id, role))
    if built_in_allowed:
        # Keyed on endpoint *and* model: two aliases on one host are two
        # providers, and deduplicating on the host alone would drop the second.
        seen = {(url.rstrip("/"), model) for url, _, model in chain}
        for url, key, model in model_providers():
            if (url.rstrip("/"), model) not in seen:
                chain.append((url, key, model))
    return chain


def record_model_access(metadata: dict[str, Any], auth: dict[str, Any] | None,
                        *, example_persona: str | None = None) -> dict[str, Any]:
    """Stamp onto a job, at creation, whether it may use the built-in providers.

    It has to be decided here rather than when the job runs. The decision needs an
    auth dict -- `may_use_built_in_providers` reads the role, the username and the
    user id -- and a job carries only `workspace_id` and `owner_user_id`. In
    hf_token mode that owner id is the Hugging Face `sub` while `space_owner()`
    yields a *username*, so re-deriving it later would deny the Space's own owner
    the credentials reserved for them, on every asynchronous run, with nothing in
    the failure that reads as being about identity.

    Deciding it once here also makes it auditable -- a run records whose budget it
    was allowed to spend -- and stops it drifting: editing the owner list midway
    does not change what an already-created job may do.
    """
    auth = auth or {}
    user = auth.get("user") or {}
    metadata = dict(metadata or {})
    metadata["modelAccess"] = {
        "builtInAllowed": bool(may_use_built_in_providers(auth, example_persona=example_persona)),
        # Who it was decided for, so the record can be read back by a person.
        "decidedFor": str(user.get("username") or auth.get("owner_user_id") or "local"),
    }
    return metadata


def built_in_allowed(job: dict[str, Any]) -> bool:
    """What `record_model_access` decided for this job.

    A job created before this existed, or by a path that does not stamp it, keeps
    the behaviour it had: the deployment's providers are available to it. Denying
    those retroactively would break every queued job on deploy, which is a worse
    failure than the one this guards against.
    """
    access = (job.get("metadata") or {}).get("modelAccess") or {}
    return bool(access.get("builtInAllowed", True))
