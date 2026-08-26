from fastapi import FastAPI, HTTPException

from .compiler import PersonaCompiler
from .generator import TinyTroupeGenerator
from .models import PersonaGenerateRequest, PersonaPatchRequest, SyntheticUserProfile

app = FastAPI(title="Persona Runtime", version="1.0.0")
generator = TinyTroupeGenerator()
profiles: dict[str, dict] = {}


@app.get("/healthz")
def health():
    return {"status": "ok", "tinytroupeAvailable": generator.tinytroupe_available, "dspyAvailable": generator.compiler.dspy_available}


@app.post("/v1/personas/generate", response_model=list[SyntheticUserProfile])
def generate(body: PersonaGenerateRequest):
    generated = generator.generate(body.theme, body.customer_profile, body.count, body.scenario, body.seed)
    profiles.update({item["id"]: item for item in generated})
    return generated


@app.patch("/v1/personas/{persona_id}", response_model=SyntheticUserProfile)
def patch(persona_id: str, body: PersonaPatchRequest):
    current = profiles.get(persona_id)
    if current is None:
        raise HTTPException(404, "persona not found")
    updated = SyntheticUserProfile.model_validate(body.persona).model_dump()
    if updated["id"] != persona_id:
        raise HTTPException(409, "persona id cannot be changed")
    updated["source"] = "manual"
    profiles[persona_id] = updated
    return updated
