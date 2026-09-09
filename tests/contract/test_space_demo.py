import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_space_runtime_dependencies_include_gradio_transitive_imports():
    requirements = Path("spaces/aux-demo/requirements.txt").read_text().splitlines()

    assert "requests>=2.32,<3" in requirements


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


def test_space_demo_exposes_visible_browser_progress_and_named_api():
    demo = load_demo()

    assert "Generating" in demo.run_started()
    assert "Preview ready" in demo.run_finished()
    config = demo.demo.get_config_file()
    named_dependencies = [
        dependency
        for dependency in config["dependencies"]
        if dependency["api_name"] == "run_contract_demo"
    ]
    assert len(named_dependencies) == 1
    assert len(named_dependencies[0]["inputs"]) == 4
    assert len(named_dependencies[0]["outputs"]) == 4
