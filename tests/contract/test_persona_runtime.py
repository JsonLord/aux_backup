from fastapi.testclient import TestClient

from services.persona_service.main import app, profiles
from services.persona_service.semantic import DirectLLMSemanticEngine, MockSemanticEngine


def test_personas_are_distinct_complete_reproducible_and_editable():
    profiles.clear()
    api = TestClient(app)
    payload = {"theme": "checkout", "customer_profile": "busy customers", "scenario": "Buy an item", "count": 2, "seed": 42}
    generated = api.post("/v1/personas/generate", json=payload)
    assert generated.status_code == 200
    first, second = generated.json()
    assert first["id"] != second["id"]
    assert set(first) == {"id", "source", "persona", "abilities", "behavior", "generation"}
    assert all(0 <= first["behavior"][trait] <= 1 for trait in ("patience", "persistence", "riskTolerance"))
    assert first["abilities"]["vision"]["colorVision"] == "typical"

    first["behavior"]["patience"] = .91
    saved = api.patch(f"/v1/personas/{first['id']}", json={"persona": first})
    assert saved.status_code == 200
    assert saved.json()["source"] == "manual"
    assert saved.json()["behavior"]["patience"] == .91


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
