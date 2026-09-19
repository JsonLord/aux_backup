"""Persona semantic compiler.

DSPy is loaded dynamically when configured. The deterministic compiler is the safe
development baseline and deliberately never infers impairments from demographics.
"""
from __future__ import annotations

import importlib
import importlib.util
import math
import os
from dataclasses import dataclass
from typing import Any

from .models import AbilityProfile, BehaviorProfile
from .providers import model_providers, unreachable, why
from .semantic import semantic_engine


TRAITS = (
    "patience", "persistence", "irritability", "angerReactivity", "angerRecovery",
    "impulsivity", "ambiguityTolerance", "failureTolerance",
    "repeatFailureTolerance", "selfEfficacy", "digitalConfidence", "helpSeeking",
    "exploration", "verificationTendency", "riskTolerance",
)

# Flat ability field names, matching AbilityProfile's nested structure flattened.
ABILITY_FIELDS = (
    "colorVision", "acuity", "contrastSensitivity", "glareSensitivity",
    "pointerPrecision", "movementSpeed", "dragReliability",
    "processingSpeed", "workingMemoryItems", "distractionSusceptibility",
    "wordsPerMinute", "compensatoryStrategies",
)

_BEHAVIOR_KEY_MAP = {"angerReactivity": "anger_reactivity", "angerRecovery": "anger_recovery", "ambiguityTolerance": "ambiguity_tolerance", "failureTolerance": "failure_tolerance", "repeatFailureTolerance": "repeat_failure_tolerance", "selfEfficacy": "self_efficacy", "digitalConfidence": "digital_confidence", "helpSeeking": "help_seeking", "verificationTendency": "verification_tendency", "riskTolerance": "risk_tolerance"}
_ABILITY_KEY_MAP = {"colorVision": "color_vision", "contrastSensitivity": "contrast_sensitivity", "glareSensitivity": "glare_sensitivity", "pointerPrecision": "pointer_precision", "movementSpeed": "movement_speed", "dragReliability": "drag_reliability", "processingSpeed": "processing_speed", "workingMemoryItems": "working_memory_items", "distractionSusceptibility": "distraction_susceptibility", "wordsPerMinute": "words_per_minute", "compensatoryStrategies": "compensatory_strategies"}


def _bounded(value: Any) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("behavior traits must be finite numbers")
    return round(max(0.0, min(1.0, numeric)), 3)


def _ability_from_flat(flat: dict[str, Any]) -> AbilityProfile:
    """Nest a flat {field: value} ability dict into the typed AbilityProfile."""
    return AbilityProfile.model_validate({
        "vision": {"colorVision": flat["colorVision"], "acuity": flat["acuity"],
                   "contrastSensitivity": flat["contrastSensitivity"], "glareSensitivity": flat["glareSensitivity"]},
        "motor": {"pointerPrecision": flat["pointerPrecision"], "movementSpeed": flat["movementSpeed"],
                  "dragReliability": flat["dragReliability"]},
        "cognition": {"processingSpeed": flat["processingSpeed"], "workingMemoryItems": flat["workingMemoryItems"],
                      "distractionSusceptibility": flat["distractionSusceptibility"]},
        "reading": {"wordsPerMinute": flat["wordsPerMinute"]},
        "compensatoryStrategies": flat["compensatoryStrategies"],
    })


@dataclass(frozen=True)
class CompilationResult:
    profile: BehaviorProfile
    compiler_version: str


@dataclass(frozen=True)
class AbilityCompilationResult:
    profile: AbilityProfile
    compiler_version: str


def _on_a_provider_that_answers(dspy_program, call):
    """Run one compilation, moving on only when an endpoint cannot be reached.

    A 400 or a refusal is the provider answering; asking a different one the same
    bad question spends a second budget on the same failure. A name that will not
    resolve is a different matter, and it is what ended five cycles.
    """
    last_error = None
    providers = model_providers() or [None]
    for index in range(len(providers)):
        where = dspy_program.configure_lm(force=index > 0, index=index)
        try:
            return call()
        except Exception as error:  # noqa: BLE001 - re-raised below when it is not transport
            last_error = error
            if not unreachable(error) or index == len(providers) - 1:
                raise
            print(f"[persona] {where} could not be reached ({why(error)}); "
                  f"compiling on the next configured provider", flush=True)
    raise last_error


class PersonaCompiler:
    version = "persona-compiler-v1"

    def compile(self, persona: dict[str, Any], scenario: str, seed: int) -> dict[str, Any]:
        return self.compile_with_metadata(persona, scenario, seed).profile.model_dump()

    def compile_with_metadata(self, persona: dict[str, Any], scenario: str, seed: int,
                              providers=None) -> CompilationResult:
        if os.getenv("PERSONA_COMPILER", "native") == "dspy":
            if not self.dspy_available:
                raise RuntimeError("PERSONA_COMPILER=dspy but DSPy is not installed")
            dspy_program = importlib.import_module("services.persona_service.dspy_program")
            prediction = _on_a_provider_that_answers(
                dspy_program, lambda: dspy_program.build_compiler()(tiny_person=persona, scenario=scenario))
            values = {trait: _bounded(getattr(prediction, _BEHAVIOR_KEY_MAP.get(trait, trait))) for trait in TRAITS}
            values["seed"] = seed
            return CompilationResult(BehaviorProfile.model_validate(values), "dspy-predict@3.3.0")
        # PLACEHOLDER: DSPy remains gated until the reviewed parity corpus is complete.
        engine = semantic_engine(providers)
        values = {trait: _bounded(value) for trait, value in engine.compile_behavior(persona, scenario, TRAITS, seed).items()}
        values["seed"] = seed
        return CompilationResult(BehaviorProfile.model_validate(values), engine.name)

    def compile_abilities_with_metadata(self, persona: dict[str, Any], scenario: str, seed: int,
                                        providers=None) -> AbilityCompilationResult:
        """Compile persona-varied functional/perceptual abilities.

        Same PERSONA_COMPILER gate and DSPy opt-in boundary as compile_with_metadata
        (see Stage 4 audit: DSPy is not the default before human-reviewed parity
        approval). Never infers ability values from persona demographics -- see
        semantic.py and dspy_program.py's CompileAbilityProfile docstring.
        """
        if os.getenv("PERSONA_COMPILER", "native") == "dspy":
            if not self.dspy_available:
                raise RuntimeError("PERSONA_COMPILER=dspy but DSPy is not installed")
            dspy_program = importlib.import_module("services.persona_service.dspy_program")
            prediction = _on_a_provider_that_answers(
                dspy_program, lambda: dspy_program.build_ability_compiler()(tiny_person=persona, scenario=scenario))
            flat = {field: getattr(prediction, _ABILITY_KEY_MAP.get(field, field)) for field in ABILITY_FIELDS}
            return AbilityCompilationResult(_ability_from_flat(flat), "dspy-predict@3.3.0")
        engine = semantic_engine(providers)
        flat = engine.compile_abilities(persona, scenario, seed)
        return AbilityCompilationResult(_ability_from_flat(flat), engine.name)

    @property
    def dspy_available(self) -> bool:
        return importlib.util.find_spec("dspy") is not None


def default_abilities() -> dict[str, Any]:
    """Static fallback used only by the fully-offline persona path (no model
    credentials configured at all). Live and offline-after-runtime-error paths use
    PersonaCompiler.compile_abilities_with_metadata for persona-varied abilities."""
    return AbilityProfile().model_dump()
