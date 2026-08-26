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

from .models import BehaviorProfile
from .semantic import semantic_engine


TRAITS = (
    "patience", "persistence", "irritability", "angerReactivity", "angerRecovery",
    "impulsivity", "ambiguityTolerance", "failureTolerance",
    "repeatFailureTolerance", "selfEfficacy", "digitalConfidence", "helpSeeking",
    "exploration", "verificationTendency", "riskTolerance",
)


def _bounded(value: Any) -> float:
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError("behavior traits must be finite numbers")
    return round(max(0.0, min(1.0, numeric)), 3)


@dataclass(frozen=True)
class CompilationResult:
    profile: BehaviorProfile
    compiler_version: str


class PersonaCompiler:
    version = "persona-compiler-v1"

    def compile(self, persona: dict[str, Any], scenario: str, seed: int) -> dict[str, Any]:
        return self.compile_with_metadata(persona, scenario, seed).profile.model_dump()

    def compile_with_metadata(self, persona: dict[str, Any], scenario: str, seed: int) -> CompilationResult:
        if os.getenv("PERSONA_COMPILER", "native") == "dspy":
            if not self.dspy_available:
                raise RuntimeError("PERSONA_COMPILER=dspy but DSPy is not installed")
            program = importlib.import_module("services.persona_service.dspy_program").build_compiler()
            prediction = program(tiny_person=persona, scenario=scenario)
            key_map = {"angerReactivity": "anger_reactivity", "angerRecovery": "anger_recovery", "ambiguityTolerance": "ambiguity_tolerance", "failureTolerance": "failure_tolerance", "repeatFailureTolerance": "repeat_failure_tolerance", "selfEfficacy": "self_efficacy", "digitalConfidence": "digital_confidence", "helpSeeking": "help_seeking", "verificationTendency": "verification_tendency", "riskTolerance": "risk_tolerance"}
            values = {trait: _bounded(getattr(prediction, key_map.get(trait, trait))) for trait in TRAITS}
            values["seed"] = seed
            return CompilationResult(BehaviorProfile.model_validate(values), "dspy-predict@3.3.0")
        # PLACEHOLDER: DSPy remains gated until the reviewed parity corpus is complete.
        engine = semantic_engine()
        values = {trait: _bounded(value) for trait, value in engine.compile_behavior(persona, scenario, TRAITS, seed).items()}
        values["seed"] = seed
        return CompilationResult(BehaviorProfile.model_validate(values), engine.name)

    @property
    def dspy_available(self) -> bool:
        return importlib.util.find_spec("dspy") is not None


def default_abilities() -> dict[str, Any]:
    return {
        "vision": {"colorVision": "typical", "acuity": 1.0, "contrastSensitivity": 1.0, "glareSensitivity": .2},
        "motor": {"pointerPrecision": .9, "movementSpeed": .8, "dragReliability": .9},
        "cognition": {"processingSpeed": .8, "workingMemoryItems": 5, "distractionSusceptibility": .3},
        "reading": {"wordsPerMinute": 220},
        "compensatoryStrategies": [],
    }
