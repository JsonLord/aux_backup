import configparser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from services.persona_service.compiler import PersonaCompiler, TRAITS
from services.persona_service.main import app, profiles
from services.persona_service.models import BehaviorProfile
from services.persona_service.semantic import DirectLLMSemanticEngine, MockSemanticEngine
from services.persona_service.store import PersonaStore
from services.persona_service.generator import TinyTroupeGenerator


def test_root_tinytroupe_config_uses_registered_openai_client():
    config = configparser.ConfigParser()
    config.read(Path(__file__).parents[2] / "config.ini")

    assert config["OpenAI"]["API_TYPE"] == "openai"
    assert config["OpenAI"]["BASE_URL"] == "https://debian-devil.tail3f341b.ts.net/v1"


def test_personas_are_distinct_complete_reproducible_and_editable(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ENGINE", "mock")
    profiles.clear()
    api = TestClient(app)
    payload = {"theme": "checkout", "customer_profile": "busy customers", "scenario": "Buy an item", "count": 2, "seed": 42}
    generated = api.post("/v1/personas/generate", json=payload)
    assert generated.status_code == 200
    first, second = generated.json()
    assert first["id"] != second["id"]
    assert set(first) == {"id", "source", "persona", "abilities", "behavior", "generation"}
    assert all(0 <= first["behavior"][trait] <= 1 for trait in ("patience", "persistence", "riskTolerance"))
    # Abilities are persona-varied (not a fixed static default); assert schema/bounds, not an exact value.
    assert first["abilities"]["vision"]["colorVision"] in {"typical", "protanopia", "deuteranopia", "tritanopia"}
    assert 0 <= first["abilities"]["vision"]["acuity"] <= 1
    assert 1 <= first["abilities"]["cognition"]["workingMemoryItems"] <= 12
    assert first["abilities"] != second["abilities"], "abilities should vary between distinct personas"

    first["behavior"]["patience"] = .91
    saved = api.patch(f"/v1/personas/{first['id']}", json={"persona": first})
    assert saved.status_code == 200
    assert saved.json()["source"] == "manual"
    assert saved.json()["behavior"]["patience"] == .91

    fetched = api.get(f"/v1/personas/{first['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == saved.json()
    assert [item["id"] for item in api.get("/v1/personas").json()] == [first["id"], second["id"]]


def test_compile_endpoint_gives_an_existing_persona_real_behavior_and_abilities(monkeypatch):
    """The "Example Persona" / Friedrich_Wolf testing path skips live TinyTroupe
    generation but must still produce a real, journey-testable profile: journey
    runs require profile.behavior, so a bare {name, persona} dict isn't enough."""
    monkeypatch.setenv("SEMANTIC_ENGINE", "mock")
    profiles.clear()
    api = TestClient(app)
    raw_persona = {"name": "Friedrich Wolf", "type": "TinyPerson",
                   "persona": {"name": "Friedrich Wolf", "occupation": {"title": "Architect"}}}
    compiled = api.post("/v1/personas/compile", json={"persona": raw_persona, "scenario": "Example persona preview", "seed": 1})
    assert compiled.status_code == 200
    body = compiled.json()
    assert body["source"] == "preset"
    assert body["persona"]["name"] == "Friedrich Wolf"
    assert set(body) == {"id", "source", "persona", "abilities", "behavior", "generation"}
    assert all(0 <= body["behavior"][trait] <= 1 for trait in ("patience", "persistence", "riskTolerance"))
    assert body["abilities"]["vision"]["colorVision"] in {"typical", "protanopia", "deuteranopia", "tritanopia"}

    fetched = api.get(f"/v1/personas/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body


def test_persona_store_survives_reopening(tmp_path):
    database = tmp_path / "personas.db"
    profile = {
        "id": "persona_persisted",
        "source": "manual",
        "persona": {"name": "Ada"},
        "abilities": {},
        "behavior": {},
        "generation": {"seed": 7},
    }
    first = PersonaStore(str(database))
    first[profile["id"]] = profile
    first.close()

    reopened = PersonaStore(str(database))
    assert reopened[profile["id"]] == profile
    reopened.close()


def test_persona_endpoints_are_workspace_scoped(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ENGINE", "mock")
    profiles.clear()
    api = TestClient(app)
    alpha = {"X-Workspace-ID": "alpha", "X-User-ID": "user-a"}
    beta = {"X-Workspace-ID": "beta", "X-User-ID": "user-b"}
    generated = api.post("/v1/personas/generate", headers=alpha, json={"theme": "checkout", "customer_profile": "customers", "count": 1, "seed": 3}).json()[0]
    assert api.get(f"/v1/personas/{generated['id']}", headers=alpha).status_code == 200
    assert api.get(f"/v1/personas/{generated['id']}", headers=beta).status_code == 404
    assert api.get("/v1/personas", headers=beta).json() == []
    assert api.patch(f"/v1/personas/{generated['id']}", headers=beta, json={"persona": generated}).status_code == 404


def test_tiny_person_serialization_uses_public_method():
    class TinyPerson:
        name = "Ada"
        def to_dict(self): return {"goals": ["Complete checkout"]}
        @property
        def _persona(self): raise AssertionError("private persona state must not be read")
    assert TinyTroupeGenerator._serialize_tiny_person(TinyPerson()) == {"name": "Ada", "goals": ["Complete checkout"]}


def test_mock_semantic_engine_is_deterministic():
    engine = MockSemanticEngine()
    first = engine.compile_behavior({"name": "Ada"}, "checkout", ("patience",), 9)
    assert first == engine.compile_behavior({"name": "Ada"}, "checkout", ("patience",), 9)


def test_direct_engine_normalizes_provider_response(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"choices": [{"message": {"content": '{"patience": 1.4}'}}]}

    monkeypatch.setattr("services.persona_service.semantic.requests.post", lambda *args, **kwargs: Response())
    engine = DirectLLMSemanticEngine(api_key="fixture", base_url="https://provider.invalid")
    assert engine.compile_behavior({"name": "Ada"}, "checkout", ("patience",), 9) == {"patience": 1.0}


def test_direct_engine_accepts_space_openai_compatible_variable_names(monkeypatch):
    monkeypatch.delenv("BLABLADOR_API_KEY", raising=False)
    monkeypatch.delenv("BLABLADOR_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT", "https://provider.invalid/v1/")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    engine = DirectLLMSemanticEngine()

    assert engine.api_key == "fixture"
    assert engine.base_url == "https://provider.invalid/v1"
    assert engine.model == "test-model"


def test_tinytroupe_maps_blablador_to_registered_openai_client(monkeypatch):
    updates = {}

    class Config:
        def update_multiple(self, values): updates.update(values)

    class Clients:
        selected = None

        @classmethod
        def force_api_type(cls, value): cls.selected = value

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("BLABLADOR_API_KEY", "fixture-secret")
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT", "https://blablador.invalid/v1/")
    monkeypatch.setenv("OPENAI_MODEL", "alias-large")

    TinyTroupeGenerator._configure_openai_compatible(Config(), Clients)

    assert updates == {"api_type": "openai", "base_url": "https://blablador.invalid/v1",
                       "model": "alias-large", "reasoning_model": "alias-large"}
    assert Clients.selected == "openai"
    assert __import__("os").environ["OPENAI_API_KEY"] == "fixture-secret"
    assert __import__("os").environ["OPENAI_BASE_URL"] == "https://blablador.invalid/v1"


def test_compiled_profile_validates_exact_behavior_schema(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ENGINE", "mock")
    compiled = PersonaCompiler().compile({"name": "Ada"}, "checkout", 9)
    validated = BehaviorProfile.model_validate(compiled)
    assert set(validated.model_dump()) == {"seed", *TRAITS}
    assert validated.seed == 9
    with pytest.raises(ValidationError):
        BehaviorProfile.model_validate({**compiled, "unversionedTrait": .5})


def test_compiled_abilities_are_persona_varied_and_bounded(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ENGINE", "mock")
    compiler = PersonaCompiler()
    ada = compiler.compile_abilities_with_metadata({"name": "Ada"}, "checkout", 9)
    bob = compiler.compile_abilities_with_metadata({"name": "Bob"}, "checkout", 10)

    assert ada.compiler_version == "mock-v1"
    assert ada.profile.vision.colorVision in {"typical", "protanopia", "deuteranopia", "tritanopia"}
    assert 0 <= ada.profile.vision.acuity <= 1
    assert 1 <= ada.profile.cognition.workingMemoryItems <= 12
    assert 60 <= ada.profile.reading.wordsPerMinute <= 500
    assert ada.profile != bob.profile, "different persona/seed should produce different abilities"

    # Same persona/seed is reproducible.
    ada_again = compiler.compile_abilities_with_metadata({"name": "Ada"}, "checkout", 9)
    assert ada.profile == ada_again.profile

    # Sampling must not systematically correlate with age (no stereotyping): with the
    # persona otherwise held fixed, mean acuity across many seeds should not trend
    # down as age increases. (MockSemanticEngine's RNG draws never branch on any
    # persona field by construction; this is a statistical sanity check of that.)
    from services.persona_service.semantic import MockSemanticEngine
    engine = MockSemanticEngine()

    def mean_acuity(age):
        values = [engine.compile_abilities({"name": "P", "age": age}, "checkout", seed)["acuity"] for seed in range(200)]
        return sum(values) / len(values)

    young_mean, old_mean = mean_acuity(22), mean_acuity(81)
    assert abs(young_mean - old_mean) < 0.05, (
        f"mean acuity should not vary meaningfully with age alone (young={young_mean}, old={old_mean})")


def test_dspy_ability_signature_matches_flat_ability_fields():
    dspy = pytest.importorskip("dspy")
    from services.persona_service.compiler import ABILITY_FIELDS, _ABILITY_KEY_MAP
    from services.persona_service.dspy_program import CompileAbilityProfile

    output_names = set(CompileAbilityProfile.output_fields.keys())
    expected = {_ABILITY_KEY_MAP.get(field, field) for field in ABILITY_FIELDS}
    assert output_names == expected


def test_generation_compiles_and_persists_once(monkeypatch):
    monkeypatch.setenv("SEMANTIC_ENGINE", "mock")
    generator = TinyTroupeGenerator()
    calls = 0
    original = generator.compiler.compile_with_metadata

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(generator.compiler, "compile_with_metadata", counted)
    profile = generator.generate("checkout", "customers", 1, "Buy", 31)[0]
    assert calls == 1
    assert BehaviorProfile.model_validate(profile["behavior"])
    assert profile["generation"]["compilerVersion"].startswith("persona-compiler-v1/")
    store = PersonaStore(":memory:")
    store.save(profile)
    assert store[profile["id"]]["behavior"] == profile["behavior"]
    assert calls == 1
    store.close()
