from __future__ import annotations

import importlib.util
import importlib
import inspect
import json
import os
import random
from typing import Any
from uuid import uuid4

from .compiler import PersonaCompiler, default_abilities


class TinyTroupeGenerator:
    """TinyTroupe boundary with a deterministic offline development fallback."""

    def __init__(self):
        self.compiler = PersonaCompiler()

    @property
    def tinytroupe_available(self) -> bool:
        return importlib.util.find_spec("tinytroupe") is not None

    def generate(self, theme: str, customer_profile: str, count: int, scenario: str, seed: int) -> list[dict[str, Any]]:
        if os.getenv("PERSONA_GENERATOR", "offline") == "tinytroupe":
            if not self.tinytroupe_available:
                raise RuntimeError("PERSONA_GENERATOR=tinytroupe but TinyTroupe is not installed")
            factory_type = importlib.import_module("tinytroupe.factory.tiny_person_factory").TinyPersonFactory
            factory = factory_type(context=f"{theme}. Target customers: {customer_profile}. Generation seed: {seed}.")
            generate = factory.generate_people
            arguments = {"number_of_people": count}
            try:
                accepts_seed = "seed" in inspect.signature(generate).parameters
            except (TypeError, ValueError):
                accepts_seed = False
            if accepts_seed:
                arguments["seed"] = seed
            people = generate(**arguments)
            raw = [self._serialize_tiny_person(person) for person in people]
            return [self._profile(item, scenario, seed + index, "tinytroupe@a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4") for index, item in enumerate(raw)]
        # Offline fallback remains explicit and cannot satisfy pinned-package acceptance.
        rng = random.Random(seed)
        occupations = ["Researcher", "Operations specialist", "Independent professional", "Customer advocate"]
        profiles = []
        for index in range(count):
            persona_seed = seed + index
            persona = {
                "name": f"Synthetic User {index + 1}",
                "age": 24 + rng.randrange(38),
                "occupation": occupations[rng.randrange(len(occupations))],
                "education": "Not specified",
                "context": customer_profile,
                "goals": [f"Complete the {theme} journey", scenario or "Reach the intended outcome"],
                "motivations": ["Efficiency", "Confidence in the result"],
                "preferences": ["Clear language", "Predictable navigation"],
                "beliefs": [],
                "skills": ["Everyday web use"],
                "technologyExperience": "intermediate",
                "personality": {"description": "Generated offline baseline; tweak before execution."},
            }
            profiles.append(self._profile(persona, scenario, persona_seed, "tinytroupe-offline-placeholder"))
        return profiles

    @staticmethod
    def _serialize_tiny_person(person):
        """Use supported serialization methods rather than TinyPerson internals."""
        for method_name in ("to_dict", "to_json", "serialize"):
            method = getattr(person, method_name, None)
            if callable(method):
                try:
                    value = method()
                except TypeError:
                    continue
                if isinstance(value, str): value = json.loads(value)
                if isinstance(value, dict):
                    return {"name": getattr(person, "name", value.get("name")), **value}
        raise RuntimeError("TinyTroupe TinyPerson exposes no supported serialization method")

    def _profile(self, persona, scenario, seed, model):
        return {"id": f"persona_{uuid4().hex}", "source": "tinytroupe", "persona": persona,
                "abilities": default_abilities(), "behavior": self.compiler.compile(persona, scenario, seed),
                "generation": {"seed": seed, "model": model, "compilerVersion": self.compiler.version}}
