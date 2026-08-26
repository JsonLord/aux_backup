import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient


def load_demo():
    path = Path("spaces/aux-demo/app.py")
    spec = importlib.util.spec_from_file_location("aux_space_demo", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_space_demo_is_transparent_deterministic_and_healthy():
    demo = load_demo()
    first = demo.run_contract_demo("https://example.com", "Find support", 2, 42)
    assert first == demo.run_contract_demo("https://example.com", "Find support", 2, 42)
    run = json.loads(first[0])
    assert run["mode"] == "offline_contract_demo"
    assert run["verdict"] == "not_executed"
    assert len(run["syntheticUsers"]) == 2
    assert "No browser was launched." in run["limitations"]
    assert json.loads(first[3])["live_browser"] == "not_configured"
    response = TestClient(demo.app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "mode": "offline_contract_demo"}
