from typing import Any, Literal

from pydantic import BaseModel, Field


class PersonaGenerateRequest(BaseModel):
    theme: str
    customer_profile: str
    count: int = Field(default=1, ge=1, le=50)
    scenario: str = ""
    seed: int = 1


class PersonaPatchRequest(BaseModel):
    persona: dict[str, Any]


class SyntheticUserProfile(BaseModel):
    id: str
    source: Literal["tinytroupe", "manual", "preset"]
    persona: dict[str, Any]
    abilities: dict[str, Any]
    behavior: dict[str, Any]
    generation: dict[str, Any]
