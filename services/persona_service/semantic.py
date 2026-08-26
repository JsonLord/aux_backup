"""Replaceable semantic engines; provider details never escape this module."""
from __future__ import annotations

import hashlib
import json
import os
import random
from typing import Any, Protocol

import requests


class SemanticEngine(Protocol):
    name: str

    def compile_behavior(self, persona: dict[str, Any], scenario: str, traits: tuple[str, ...], seed: int) -> dict[str, float]: ...


class MockSemanticEngine:
    """Deterministic CI/offline engine, not a claim of behavioral validity."""

    name = "mock-v1"

    def compile_behavior(self, persona, scenario, traits, seed):
        fingerprint = hashlib.sha256(json.dumps(persona, sort_keys=True).encode()).digest()
        rng = random.Random(seed + int.from_bytes(fingerprint[:4]))
        return {trait: round(.25 + rng.random() * .5, 3) for trait in traits}


class DirectLLMSemanticEngine:
    name = "blablador-alias-huge"

    def __init__(self, api_key=None, base_url=None, model="alias-huge"):
        self.api_key = api_key or os.getenv("BLABLADOR_API_KEY")
        self.base_url = (base_url or os.getenv("BLABLADOR_BASE_URL", "https://api.helmholtz-blablador.fz-juelich.de/v1")).rstrip("/")
        self.model = model
        if not self.api_key:
            raise ValueError("BLABLADOR_API_KEY is required for the direct semantic engine")

    def compile_behavior(self, persona, scenario, traits, seed):
        schema = {trait: "number from 0 to 1" for trait in traits}
        prompt = {"task": "Compile web-interaction priors. Do not infer medical or physical impairments from demographics.", "persona": persona, "scenario": scenario, "seed": seed, "required_output": schema}
        response = requests.post(f"{self.base_url}/chat/completions", headers={"authorization": f"Bearer {self.api_key}"}, json={"model": self.model, "temperature": 0, "response_format": {"type": "json_object"}, "messages": [{"role": "user", "content": json.dumps(prompt)}]}, timeout=60)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        result = json.loads(content)
        if set(result) != set(traits):
            raise ValueError("semantic engine returned an invalid behavior schema")
        return {trait: max(0.0, min(1.0, float(result[trait]))) for trait in traits}


def semantic_engine() -> SemanticEngine:
    selected = os.getenv("SEMANTIC_ENGINE", "direct" if os.getenv("BLABLADOR_API_KEY") else "mock")
    if selected == "direct":
        return DirectLLMSemanticEngine()
    if selected == "mock":
        return MockSemanticEngine()
    raise ValueError(f"unsupported SEMANTIC_ENGINE: {selected}")
