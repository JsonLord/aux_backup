from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ColorVision = Literal["typical", "protanopia", "deuteranopia", "tritanopia", "custom"]


class PersonaGenerateRequest(BaseModel):
    theme: str
    customer_profile: str
    count: int = Field(default=1, ge=1, le=50)
    scenario: str = ""
    seed: int = 1
    allow_offline_fallback: bool = False


class PersonaPatchRequest(BaseModel):
    persona: dict[str, Any]


class PersonaPoolLookupRequest(BaseModel):
    """Ranged-match lookup against the GitHub-backed persona pool (docs/persona-pool-plan.md section 4)."""

    theme: str
    customer_profile: str
    count: int = Field(default=1, ge=1, le=50)
    behavior_targets: dict[str, float] | None = None


class PersonaCompileRequest(BaseModel):
    """Compile behavior/ability profiles for an already-built persona (e.g. a
    bundled TinyTroupe example agent), skipping live TinyTroupe generation."""

    persona: dict[str, Any]
    scenario: str = ""
    seed: int = 1
    source: Literal["tinytroupe", "manual", "preset"] = "preset"


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


class VisionAbilities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    colorVision: ColorVision = "typical"
    acuity: float = Field(default=1.0, ge=0, le=1)
    contrastSensitivity: float = Field(default=1.0, ge=0, le=1)
    glareSensitivity: float = Field(default=.2, ge=0, le=1)


class MotorAbilities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pointerPrecision: float = Field(default=.9, ge=0, le=1)
    movementSpeed: float = Field(default=.8, ge=0, le=1)
    dragReliability: float = Field(default=.9, ge=0, le=1)


class CognitionAbilities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    processingSpeed: float = Field(default=.8, ge=0, le=1)
    workingMemoryItems: int = Field(default=5, ge=1, le=12)
    distractionSusceptibility: float = Field(default=.3, ge=0, le=1)


class ReadingAbilities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    wordsPerMinute: int = Field(default=220, ge=60, le=500)


class AbilityProfile(BaseModel):
    """Functional/perceptual ability priors (spec.md §6.1 "Functional abilities").

    Distinct from BehaviorProfile: abilities describe device- and
    perception-facing capability, not coping/emotional tendencies. Uses
    ``extra="ignore"`` (unlike BehaviorProfile's ``extra="forbid"``) because this
    nested structure is also built up incrementally by manual UI edits
    (apply_persona_tweaks) that may not touch every field.
    """

    model_config = ConfigDict(extra="ignore")

    vision: VisionAbilities = Field(default_factory=VisionAbilities)
    motor: MotorAbilities = Field(default_factory=MotorAbilities)
    cognition: CognitionAbilities = Field(default_factory=CognitionAbilities)
    reading: ReadingAbilities = Field(default_factory=ReadingAbilities)
    compensatoryStrategies: list[str] = Field(default_factory=list)


class SyntheticUserProfile(BaseModel):
    id: str
    source: Literal["tinytroupe", "manual", "preset"]
    persona: dict[str, Any]
    abilities: AbilityProfile
    behavior: BehaviorProfile
    generation: dict[str, Any]
