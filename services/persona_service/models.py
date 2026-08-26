from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class PersonaGenerateRequest(BaseModel):
    theme: str
    customer_profile: str
    count: int = Field(default=1, ge=1, le=50)
    scenario: str = ""
    seed: int = 1


class PersonaPatchRequest(BaseModel):
    persona: dict[str, Any]


class BehaviorProfile(BaseModel):
    """Versioned semantic boundary consumed by the native Journey worker."""

    model_config = ConfigDict(extra="forbid")

    seed: int
    patience: float = Field(ge=0, le=1)
    persistence: float = Field(ge=0, le=1)
    irritability: float = Field(ge=0, le=1)
    angerReactivity: float = Field(ge=0, le=1)
    angerRecovery: float = Field(ge=0, le=1)
    impulsivity: float = Field(ge=0, le=1)
    ambiguityTolerance: float = Field(ge=0, le=1)
    failureTolerance: float = Field(ge=0, le=1)
    repeatFailureTolerance: float = Field(ge=0, le=1)
    selfEfficacy: float = Field(ge=0, le=1)
    digitalConfidence: float = Field(ge=0, le=1)
    helpSeeking: float = Field(ge=0, le=1)
    exploration: float = Field(ge=0, le=1)
    verificationTendency: float = Field(ge=0, le=1)
    riskTolerance: float = Field(ge=0, le=1)


class SyntheticUserProfile(BaseModel):
    id: str
    source: Literal["tinytroupe", "manual", "preset"]
    persona: dict[str, Any]
    abilities: dict[str, Any]
    behavior: BehaviorProfile
    generation: dict[str, Any]
