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
from .compiler import TRAITS
from .models import BehaviorProfile
from .semantic import MockSemanticEngine


class TinyTroupeGenerator:
    """TinyTroupe boundary with a deterministic offline development fallback."""

    def __init__(self):
        self.compiler = PersonaCompiler()

    @property
    def tinytroupe_available(self) -> bool:
        return importlib.util.find_spec("tinytroupe") is not None

    def generate(self, theme: str, customer_profile: str, count: int, scenario: str, seed: int,
                 allow_offline_fallback: bool = False) -> list[dict[str, Any]]:
        if os.getenv("PERSONA_GENERATOR", "offline") == "tinytroupe":
            if not self.tinytroupe_available:
                raise RuntimeError("PERSONA_GENERATOR=tinytroupe but TinyTroupe is not installed")
            # TinyTroupe constructs its OpenAI singleton during import, so prepare
            # the standard SDK variables before importing the package.
            self._openai_compatible_settings()
            tinytroupe = importlib.import_module("tinytroupe")
            clients = importlib.import_module("tinytroupe.clients")
            self._configure_openai_compatible(tinytroupe.config_manager, clients)
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
            try:
                people = generate(**arguments)
            except Exception:
                if not allow_offline_fallback:
                    raise
                # Explicit acceptance-only fallback: retain the failed runtime in
                # provenance and never label these profiles as model-generated.
                return self._offline_profiles(theme, customer_profile, count, scenario, seed,
                                              "tinytroupe-offline-fallback-after-runtime-error",
                                              allow_compiler_fallback=True)
            raw = [self._serialize_tiny_person(person) for person in people]
            return [self._profile(item, scenario, seed + index, "tinytroupe@a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4") for index, item in enumerate(raw)]
        # Offline fallback remains explicit and cannot satisfy pinned-package acceptance.
        return self._offline_profiles(theme, customer_profile, count, scenario, seed,
                                      "tinytroupe-offline-placeholder")

    @staticmethod
    def _openai_compatible_settings():
        """Resolve aliases and prepare the standard OpenAI SDK environment.

        Primary provider is the self-hosted freellmapi router (Tailscale Funnel,
        see spaces/aux-live/start-live.sh); BLABLADOR_* names remain supported as
        legacy aliases. The router requires the literal model id "auto" -- any
        other id 400s with model_not_found -- so that is the default here.
        """
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY")
        base_url = (os.getenv("OPENAI_COMPATIBLE_ENDPOINT") or os.getenv("OPENAI_BASE_URL")
                    or os.getenv("BLABLADOR_BASE_URL")
                    or "https://debian-devil.tail3f341b.ts.net/v1").rstrip("/")
        model = os.getenv("OPENAI_MODEL", "auto")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY or BLABLADOR_API_KEY is required for TinyTroupe")
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        return base_url, model

    @staticmethod
    def _max_completion_tokens():
        """Bound the completion budget so large aliases stay inside the Blablador
        gateway read-timeout. TinyTroupe defaults this to 128000, which the
        Helmholtz proxy cannot stream for the large models and answers with a
        ``502 Proxy Error``. Returns ``None`` when the override is unparseable so
        the config.ini ceiling applies instead."""
        raw = os.getenv("OPENAI_MAX_COMPLETION_TOKENS")
        if not raw:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    @classmethod
    def _configure_openai_compatible(cls, config_manager, clients):
        """Map Helmholtz settings onto TinyTroupe's registered OpenAI client.

        JsonLord/TinyTroupe's ``fix-openai-auth-error`` branch introduced a
        dedicated Blablador client, but that branch is based on TinyTroupe 0.5.2.
        The pinned 0.7 runtime exposes the equivalent public client override and
        config-manager APIs, which lets this adapter preserve the reviewed 0.7
        boundary without patching site-packages.
        """
        base_url, model = cls._openai_compatible_settings()
        overrides = {"api_type": "openai", "base_url": base_url,
                     "model": model, "reasoning_model": model}
        max_completion_tokens = cls._max_completion_tokens()
        if max_completion_tokens is not None:
            overrides["max_completion_tokens"] = max_completion_tokens
        config_manager.update_multiple(overrides)
        clients.force_api_type("openai")
        cls._patch_system_message_ordering()

    @staticmethod
    def _consolidate_leading_system_message(messages):
        """Merge every system-role message into a single leading one.

        TinyTroupe 0.7's ``LLMChat.call()`` (``tinytroupe/utils/llm.py``) appends a
        JSON/typing-format instruction with ``role: "system"`` to the *end* of the
        conversation immediately before almost every structured/typed call (the
        ``@llm()``-decorated persona-attribute generators all go through this
        path). The Helmholtz Blablador gateway's backend rejects any request whose
        system message is not the first one with ``400 System message must be at
        the beginning``, which TinyTroupe's own retry logic then treats as
        non-retryable and silently turns into ``None`` for that field. Moving all
        system-role content into one leading message preserves every instruction
        verbatim while satisfying that ordering requirement.
        """
        if not messages:
            return messages
        system_parts = [message["content"] for message in messages if message.get("role") == "system"]
        if not system_parts:
            return messages
        if len(system_parts) == 1 and messages[0].get("role") == "system":
            return messages
        rest = [message for message in messages if message.get("role") != "system"]
        return [{"role": "system", "content": "\n\n".join(system_parts)}, *rest]

    @classmethod
    def _patch_system_message_ordering(cls):
        """Wrap the registered OpenAI-compatible client so every outgoing request
        satisfies Blablador's "system message must be at the beginning" rule,
        without editing TinyTroupe's installed package files. Idempotent: safe to
        call on every generation request."""
        try:
            openai_client_module = importlib.import_module("tinytroupe.clients.openai_client")
        except ImportError:
            return
        client_class = getattr(openai_client_module, "OpenAIClient", None)
        if client_class is None or getattr(client_class.send_message, "_aux_gateway_patch", False):
            return
        original_send_message = client_class.send_message

        def patched_send_message(self, current_messages, *args, **kwargs):
            current_messages = cls._consolidate_leading_system_message(current_messages)
            return original_send_message(self, current_messages, *args, **kwargs)

        patched_send_message._aux_gateway_patch = True
        client_class.send_message = patched_send_message

    def _offline_profiles(self, theme, customer_profile, count, scenario, seed, model,
                          allow_compiler_fallback=False):
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
            try:
                profiles.append(self._profile(persona, scenario, persona_seed, model))
            except Exception:
                if not allow_compiler_fallback:
                    raise
                values = MockSemanticEngine().compile_behavior(persona, scenario, TRAITS, persona_seed)
                values["seed"] = persona_seed
                profiles.append({"id": f"persona_{uuid4().hex}", "source": "tinytroupe", "persona": persona,
                    "abilities": default_abilities(), "behavior": BehaviorProfile.model_validate(values).model_dump(),
                    "generation": {"seed": persona_seed, "model": model,
                        "compilerVersion": f"{self.compiler.version}/mock-v1-after-provider-error"}})
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
        # Compilation happens exactly once for this new synthetic user. The validated
        # result is embedded in the durable profile rather than recomputed per run.
        compilation = self.compiler.compile_with_metadata(persona, scenario, seed)
        return {"id": f"persona_{uuid4().hex}", "source": "tinytroupe", "persona": persona,
                "abilities": default_abilities(), "behavior": compilation.profile.model_dump(),
                "generation": {"seed": seed, "model": model,
                               "compilerVersion": f"{self.compiler.version}/{compilation.compiler_version}"}}
