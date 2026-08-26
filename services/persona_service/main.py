from fastapi import Depends, FastAPI, HTTPException, Query

from apps.api.auth import IdentityProvider

from .compiler import PersonaCompiler
from .generator import TinyTroupeGenerator
from .models import PersonaGenerateRequest, PersonaPatchRequest, SyntheticUserProfile
from .store import persona_store_from_environment

app = FastAPI(title="Persona Runtime", version="1.0.0")
generator = TinyTroupeGenerator()
profiles = persona_store_from_environment()
identity = IdentityProvider(membership_store=profiles if hasattr(profiles, "upsert_workspace_membership") else None)


def require_write(auth):
    if auth.get("role", "owner") not in {"owner", "admin", "write", "contributor", "service"}:
        raise HTTPException(403, "workspace role is read-only")


@app.get("/healthz")
def health():
    return {"status": "ok", "tinytroupeAvailable": generator.tinytroupe_available, "dspyAvailable": generator.compiler.dspy_available}


@app.post("/v1/personas/generate", response_model=list[SyntheticUserProfile])
def generate(body: PersonaGenerateRequest, auth=Depends(identity)):
    require_write(auth)
    generated = generator.generate(body.theme, body.customer_profile, body.count, body.scenario, body.seed)
    for item in generated:
        profiles.save(item, auth["workspace_id"], auth["owner_user_id"])
    return generated


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
