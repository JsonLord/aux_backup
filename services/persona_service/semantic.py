"""Replaceable semantic engines; provider details never escape this module."""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
from typing import Any, Protocol

import requests


# Real-world population-wide prevalence, used only as an unconditional sampling
# weight -- never as a function of any persona detail (age, gender, occupation,
# etc.). Approximate, source-agnostic figures for a mixed population; not a
# clinical claim. "custom" is reserved for manual UI entry, never generated.
_COLOR_VISION_WEIGHTS = (
    ("typical", 0.92), ("deuteranopia", 0.04), ("protanopia", 0.03), ("tritanopia", 0.01),
)


def _int_env_override(name: str):
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _float_env_override(name: str):
    raw = os.getenv(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


class SemanticEngine(Protocol):
    name: str

    def compile_behavior(self, persona: dict[str, Any], scenario: str, traits: tuple[str, ...], seed: int) -> dict[str, float]: ...
    def compile_abilities(self, persona: dict[str, Any], scenario: str, seed: int) -> dict[str, Any]: ...


def _weighted_choice(rng: random.Random, weights: tuple[tuple[str, float], ...]) -> str:
    total = sum(weight for _, weight in weights)
    pick = rng.random() * total
    cursor = 0.0
    for value, weight in weights:
        cursor += weight
        if pick <= cursor:
            return value
    return weights[-1][0]


class MockSemanticEngine:
    """Deterministic CI/offline engine, not a claim of behavioral validity."""

    name = "mock-v1"

    def compile_behavior(self, persona, scenario, traits, seed):
        fingerprint = hashlib.sha256(json.dumps(persona, sort_keys=True).encode()).digest()
        rng = random.Random(seed + int.from_bytes(fingerprint[:4]))
        return {trait: round(.25 + rng.random() * .5, 3) for trait in traits}

    def compile_abilities(self, persona, scenario, seed):
        # A distinct fingerprint offset from compile_behavior's so the two calls
        # for the same persona/seed don't share (and thus correlate) their RNG
        # stream. Sampling here is unconditional on persona content by
        # construction -- the fingerprint only salts the seed, it is never
        # branched on.
        fingerprint = hashlib.sha256(("abilities:" + json.dumps(persona, sort_keys=True)).encode()).digest()
        rng = random.Random(seed + int.from_bytes(fingerprint[:4]))
        color_vision = _weighted_choice(rng, _COLOR_VISION_WEIGHTS)
        return {
            "colorVision": color_vision,
            "acuity": round(min(1.0, max(0.0, rng.gauss(.85, .12))), 3),
            "contrastSensitivity": round(min(1.0, max(0.0, rng.gauss(.85, .12))), 3),
            "glareSensitivity": round(min(1.0, max(0.0, rng.gauss(.25, .12))), 3),
            "pointerPrecision": round(min(1.0, max(0.0, rng.gauss(.85, .1))), 3),
            "movementSpeed": round(min(1.0, max(0.0, rng.gauss(.8, .12))), 3),
            "dragReliability": round(min(1.0, max(0.0, rng.gauss(.85, .1))), 3),
            "processingSpeed": round(min(1.0, max(0.0, rng.gauss(.75, .12))), 3),
            "workingMemoryItems": max(1, min(12, round(rng.gauss(7, 1.5)))),
            "distractionSusceptibility": round(min(1.0, max(0.0, rng.gauss(.35, .15))), 3),
            "wordsPerMinute": max(60, min(500, round(rng.gauss(230, 45)))),
            "compensatoryStrategies": ["relies on labels/icons rather than color alone"] if color_vision != "typical" else [],
        }


class DirectLLMSemanticEngine:
    name = "openai-compatible-direct"

    def __init__(self, api_key=None, base_url=None, model=None):
        self.api_key = api_key or os.getenv("BLABLADOR_API_KEY") or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("BLABLADOR_BASE_URL")
                         or os.getenv("OPENAI_COMPATIBLE_ENDPOINT") or os.getenv("OPENAI_BASE_URL")
                         or "https://debian-devil.tail3f341b.ts.net/v1").rstrip("/")
        # The freellmapi router requires the literal model id "auto"; other ids 400.
        self.model = model or os.getenv("OPENAI_MODEL", "auto")
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY or BLABLADOR_API_KEY is required for the direct semantic engine")

    @staticmethod
    def _parse_json_completion(content: str) -> dict:
        """Parse a JSON object out of a chat completion, tolerating a markdown code
        fence around it even though response_format: json_object was requested.

        Observed live: the "auto" router can land on a model (e.g. a Gemini variant)
        that answers with ```json\\n{...}\\n``` instead of a bare JSON object despite
        that parameter. Falls back to extracting the first {...} block (same
        technique app.py's generate_tasks already uses) if a direct parse fails.
        """
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
            stripped = re.sub(r"\n?```\s*$", "", stripped)
            stripped = stripped.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", stripped, re.DOTALL)
            if match:
                return json.loads(match.group())
            raise

    def _complete_json(self, prompt: dict, max_attempts: int | None = None, retry_wait_seconds: float | None = None) -> dict:
        """POST the prompt and parse a JSON completion, retrying the same request on
        transient failure. The "auto" router occasionally returns a non-2xx status,
        a connection error (observed live, under concurrent load against a
        self-hosted backend: SSL: UNEXPECTED_EOF_WHILE_READING -- the server
        dropping the connection), or an empty completion body -- none of which
        TinyTroupe's own retry logic covers, since this call bypasses TinyTroupe
        entirely. Each attempt is the exact same request; nothing about the prompt
        changes between retries. The wait grows with each attempt (retry_wait_seconds
        * attempt number) to give a momentarily overloaded server more room to
        recover on later tries. Overridable via SEMANTIC_ENGINE_MAX_ATTEMPTS /
        SEMANTIC_ENGINE_RETRY_WAIT_SECONDS.
        """
        if max_attempts is None:
            max_attempts = _int_env_override("SEMANTIC_ENGINE_MAX_ATTEMPTS") or 4
        if retry_wait_seconds is None:
            retry_wait_seconds = _float_env_override("SEMANTIC_ENGINE_RETRY_WAIT_SECONDS") or 2.0
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.post(f"{self.base_url}/chat/completions", headers={"authorization": f"Bearer {self.api_key}"}, json={"model": self.model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": json.dumps(prompt)}]}, timeout=60)
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                if not content or not content.strip():
                    raise ValueError("model returned an empty completion")
                return self._parse_json_completion(content)
            except (requests.RequestException, ValueError, KeyError, IndexError, json.JSONDecodeError) as error:
                last_error = error
                if attempt < max_attempts:
                    time.sleep(retry_wait_seconds * attempt)
        raise RuntimeError(f"semantic engine request failed after {max_attempts} attempts: {last_error}") from last_error

    def compile_behavior(self, persona, scenario, traits, seed):
        schema = {trait: "number from 0 to 1" for trait in traits}
        prompt = {"task": "Compile web-interaction priors. Do not infer medical or physical impairments from demographics.", "persona": persona, "scenario": scenario, "seed": seed, "required_output": schema}
        result = self._complete_json(prompt)
        if set(result) != set(traits):
            raise ValueError("semantic engine returned an invalid behavior schema")
        return {trait: max(0.0, min(1.0, float(result[trait]))) for trait in traits}

    _ABILITY_FIELDS = (
        "colorVision", "acuity", "contrastSensitivity", "glareSensitivity",
        "pointerPrecision", "movementSpeed", "dragReliability",
        "processingSpeed", "workingMemoryItems", "distractionSusceptibility",
        "wordsPerMinute", "compensatoryStrategies",
    )

    def compile_abilities(self, persona, scenario, seed):
        schema = {
            "colorVision": 'one of "typical", "protanopia", "deuteranopia", "tritanopia"',
            "acuity": "number from 0 to 1, 1 is normal visual acuity",
            "contrastSensitivity": "number from 0 to 1, 1 is normal contrast sensitivity",
            "glareSensitivity": "number from 0 to 1, higher is more sensitive to glare/brightness",
            "pointerPrecision": "number from 0 to 1, 1 is precise mouse/touch pointing",
            "movementSpeed": "number from 0 to 1, 1 is fast pointer movement",
            "dragReliability": "number from 0 to 1, 1 is reliable drag-and-drop",
            "processingSpeed": "number from 0 to 1, 1 is fast cognitive processing of new UI",
            "workingMemoryItems": "integer from 1 to 12, typical adult is 5 to 9",
            "distractionSusceptibility": "number from 0 to 1, higher is more easily distracted",
            "wordsPerMinute": "integer from 60 to 500, typical adult reading speed is 200 to 260",
            "compensatoryStrategies": "short list of strings describing any coping strategies implied by the "
                                      "other values (e.g. relying on icons over color); empty list if none apply",
        }
        prompt = {
            "task": "Compile functional/perceptual ability priors for a synthetic web user, representing "
                    "realistic population-wide statistical diversity in vision, motor control, cognition, and "
                    "reading. Sample as if drawing independently from general population statistics. Do not "
                    "infer, correlate, or condition any value on the persona's age, gender, occupation, or any "
                    "other demographic or biographical detail -- that would encode harmful stereotypes (e.g. "
                    "assuming an older persona has worse vision). Most people are within typical ranges; only a "
                    "realistic minority should deviate meaningfully.",
            "persona": persona, "scenario": scenario, "seed": seed, "required_output": schema,
        }
        result = self._complete_json(prompt)
        if set(result) != set(self._ABILITY_FIELDS):
            raise ValueError("semantic engine returned an invalid ability schema")
        color_vision = result["colorVision"] if result["colorVision"] in {"typical", "protanopia", "deuteranopia", "tritanopia"} else "typical"
        strategies = result["compensatoryStrategies"]
        return {
            "colorVision": color_vision,
            "acuity": max(0.0, min(1.0, float(result["acuity"]))),
            "contrastSensitivity": max(0.0, min(1.0, float(result["contrastSensitivity"]))),
            "glareSensitivity": max(0.0, min(1.0, float(result["glareSensitivity"]))),
            "pointerPrecision": max(0.0, min(1.0, float(result["pointerPrecision"]))),
            "movementSpeed": max(0.0, min(1.0, float(result["movementSpeed"]))),
            "dragReliability": max(0.0, min(1.0, float(result["dragReliability"]))),
            "processingSpeed": max(0.0, min(1.0, float(result["processingSpeed"]))),
            "workingMemoryItems": max(1, min(12, int(result["workingMemoryItems"]))),
            "distractionSusceptibility": max(0.0, min(1.0, float(result["distractionSusceptibility"]))),
            "wordsPerMinute": max(60, min(500, int(result["wordsPerMinute"]))),
            "compensatoryStrategies": [str(item) for item in strategies] if isinstance(strategies, list) else [],
        }


def semantic_engine() -> SemanticEngine:
    selected = os.getenv("SEMANTIC_ENGINE", "direct" if (os.getenv("BLABLADOR_API_KEY") or os.getenv("OPENAI_API_KEY")) else "mock")
    if selected == "direct":
        return DirectLLMSemanticEngine()
    if selected == "mock":
        return MockSemanticEngine()
    raise ValueError(f"unsupported SEMANTIC_ENGINE: {selected}")
