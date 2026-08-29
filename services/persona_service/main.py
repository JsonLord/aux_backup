from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query

from apps.api.auth import IdentityProvider

from .compiler import PersonaCompiler
from .generator import TinyTroupeGenerator
from .github_pool import GitHubPersonaPoolClient, PersonaPoolConfig, select_pool_group
from .models import (
    PersonaCompileRequest,
    PersonaGenerateRequest,
    PersonaPatchRequest,
    PersonaPoolLookupRequest,
    SyntheticUserProfile,
)
from .store import persona_store_from_environment

app = FastAPI(title="Persona Runtime", version="1.0.0")
generator = TinyTroupeGenerator()
profiles = persona_store_from_environment()
identity = IdentityProvider(membership_store=profiles if hasattr(profiles, "upsert_workspace_membership") else None)
_pool_config = PersonaPoolConfig.from_env()
pool_client = GitHubPersonaPoolClient(_pool_config) if _pool_config else None


def require_write(auth):
    if auth.get("role", "owner") not in {"owner", "admin", "write", "contributor", "service"}:
        raise HTTPException(403, "workspace role is read-only")


@app.get("/healthz")
def health():
    return {"status": "ok", "tinytroupeAvailable": generator.tinytroupe_available, "dspyAvailable": generator.compiler.dspy_available}


@app.post("/v1/personas/generate", response_model=list[SyntheticUserProfile])
def generate(body: PersonaGenerateRequest, auth=Depends(identity)):
    require_write(auth)
    generated = generator.generate(body.theme, body.customer_profile, body.count, body.scenario,
                                   body.seed, allow_offline_fallback=body.allow_offline_fallback)
    for item in generated:
        profiles.save(item, auth["workspace_id"], auth["owner_user_id"])
    return generated


@app.post("/v1/personas/compile", response_model=SyntheticUserProfile)
def compile_existing(body: PersonaCompileRequest, auth=Depends(identity)):
    require_write(auth)
    compiled = generator.compile_existing(body.persona, body.scenario, body.seed, source=body.source)
    profiles.save(compiled, auth["workspace_id"], auth["owner_user_id"])
    return compiled


@app.post("/v1/personas/pool-lookup")
def pool_lookup(body: PersonaPoolLookupRequest, auth=Depends(identity)):
    """Ranged-match lookup against the GitHub-backed persona pool.

    Returns at most `count` personas; the caller (app.py's select_or_create_personas)
    is responsible for falling back to live generation for any shortfall, per
    docs/persona-pool-plan.md section 4 point 4.
    """
    if pool_client is None:
        return {"poolConfigured": False, "personas": [], "requested": body.count, "matched": 0}
    index_entries = pool_client.fetch_index()
    selected = select_pool_group(index_entries, body.theme, body.customer_profile, body.count, body.behavior_targets)
    personas, skipped = [], []
    for entry in selected:
        path = entry.get("path")
        if not path:
            skipped.append({"path": path, "reason": "index entry has no path"})
            continue
        try:
            raw_profile = pool_client.fetch_persona(path)
        except Exception as error:
            skipped.append({"path": path, "reason": f"fetch failed: {error}"})
            continue
        # Mint a fresh workspace-local id rather than adopting the pool file's own
        # id: PersonaStore.save() keys rows globally by persona_id, so re-saving
        # the same pool persona id under two different workspaces would silently
        # steal it from whichever workspace saved it first (see store.py's
        # single-column PRIMARY KEY). A fresh id per adoption avoids that.
        profile = {**raw_profile, "id": f"persona_{uuid4().hex}"}
        profile.setdefault("generation", {})
        profile["generation"] = {**profile["generation"], "poolSource": {"repo": pool_client.config.repo, "path": path}}
        try:
            validated = SyntheticUserProfile.model_validate(profile).model_dump()
        except Exception as error:
            skipped.append({"path": path, "reason": f"schema validation failed: {error}"})
            continue
        profiles.save(validated, auth["workspace_id"], auth["owner_user_id"])
        personas.append(validated)
    return {"poolConfigured": True, "personas": personas, "requested": body.count,
            "matched": len(personas), "skipped": skipped}


@app.get("/v1/personas", response_model=list[SyntheticUserProfile])
def list_personas(limit: int = Query(default=50, ge=1, le=200), auth=Depends(identity)):
    return profiles.list_for_workspace(auth["workspace_id"], limit)


@app.get("/v1/personas/{persona_id}", response_model=SyntheticUserProfile)
def get_persona(persona_id: str, auth=Depends(identity)):
    try:
        return profiles.get_for_workspace(persona_id, auth["workspace_id"])
    except KeyError as error:
        raise HTTPException(404, "persona not found") from error


@app.patch("/v1/personas/{persona_id}", response_model=SyntheticUserProfile)
def patch(persona_id: str, body: PersonaPatchRequest, auth=Depends(identity)):
    require_write(auth)
    try:
        profiles.get_for_workspace(persona_id, auth["workspace_id"])
    except KeyError:
        raise HTTPException(404, "persona not found")
    updated = SyntheticUserProfile.model_validate(body.persona).model_dump()
    if updated["id"] != persona_id:
        raise HTTPException(409, "persona id cannot be changed")
    updated["source"] = "manual"
    profiles.save(updated, auth["workspace_id"], auth["owner_user_id"])
    return updated
