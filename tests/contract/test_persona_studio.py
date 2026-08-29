import importlib.util
from functools import lru_cache
from pathlib import Path

import pytest
import requests


@lru_cache(maxsize=1)
def load_root_app():
    path = Path(__file__).parents[2] / "app.py"
    spec = importlib.util.spec_from_file_location("aux_root_app_studio", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROFILE = {
    "id": "persona_1", "source": "preset", "persona": {"name": "Ada"},
    "behavior": {"patience": 0.7}, "abilities": {"vision": {"colorVision": "protanopia", "acuity": 0.6}},
}


def test_load_persona_returns_defaults_for_empty_list_instead_of_crashing():
    app_module = load_root_app()

    result = app_module.load_persona([], "0")

    assert result[0] is None
    assert result[1] == ""


def test_load_persona_returns_defaults_for_out_of_range_index():
    app_module = load_root_app()

    result = app_module.load_persona([PROFILE], "5")

    # Falls back to the first available profile rather than crashing.
    assert result[0] == PROFILE


def test_load_persona_loads_matching_index():
    app_module = load_root_app()

    result = app_module.load_persona([PROFILE], "0")

    assert result[0] == PROFILE
    assert result[1] == '{\n  "id": "persona_1",\n  "source": "preset",\n  "persona": {\n    "name": "Ada"\n  },\n  "behavior": {\n    "patience": 0.7\n  },\n  "abilities": {\n    "vision": {\n      "colorVision": "protanopia",\n      "acuity": 0.6\n    }\n  }\n}'


class FakePersonaClient:
    def __init__(self, compiled=None, error=None):
        self.compiled = compiled or {**PROFILE, "id": "persona_example", "name": "Friedrich Wolf"}
        self.error = error
        self.compile_calls = []

    def compile(self, persona, scenario="", seed=1, source="preset"):
        self.compile_calls.append((scenario, seed))
        if self.error:
            raise self.error
        return self.compiled


def test_load_example_persona_into_studio_appends_and_selects_new_entry(monkeypatch):
    app_module = load_root_app()
    fake = FakePersonaClient()
    monkeypatch.setattr(app_module, "authenticated_clients", lambda *a, **k: (None, fake))

    personas, index_update, status = app_module.load_example_persona_into_studio(
        "Friedrich_Wolf.agent.json", [PROFILE], "local", None, None)

    assert len(personas) == 2
    assert personas[-1]["id"] == "persona_example"
    assert index_update["value"] == "1"
    assert "Friedrich Wolf" in status


def test_load_example_persona_into_studio_requires_a_selection():
    app_module = load_root_app()

    personas, index_update, status = app_module.load_example_persona_into_studio(None, [], "local", None, None)

    assert personas == []
    assert "Choose a bundled example persona" in status


def test_load_example_persona_into_studio_surfaces_compile_failure(monkeypatch):
    app_module = load_root_app()
    fake = FakePersonaClient(error=requests.exceptions.RequestException("router unavailable"))
    monkeypatch.setattr(app_module, "authenticated_clients", lambda *a, **k: (None, fake))

    personas, index_update, status = app_module.load_example_persona_into_studio(
        "Friedrich_Wolf.agent.json", [], "local", None, None)

    assert personas == []
    assert "Failed to load" in status
    assert "router unavailable" in status


def test_monitor_and_log_reports_permission_error_instead_of_crashing(monkeypatch):
    app_module = load_root_app()

    def raise_permission_error(*a, **k):
        raise PermissionError("Sign in with Hugging Face to continue")

    monkeypatch.setattr(app_module, "authenticated_clients", raise_permission_error)

    # monitor_and_log is a closure defined inside build_app(); reach it through
    # the Gradio Blocks' fn_map by name to test the real deployed behavior.
    fn = _find_event_fn(app_module, "monitor_and_log")
    feed, log = fn("local", None, None)

    assert "Sign in with Hugging Face" in feed
    assert log == ""


def test_monitor_and_log_reports_http_error_instead_of_crashing(monkeypatch):
    app_module = load_root_app()

    class FakeSessionClient:
        def list_sessions(self):
            response = requests.models.Response()
            response.status_code = 401
            raise requests.exceptions.HTTPError(response=response)

    monkeypatch.setattr(app_module, "authenticated_clients", lambda *a, **k: (FakeSessionClient(), None))

    fn = _find_event_fn(app_module, "monitor_and_log")
    feed, log = fn("local", None, None)

    assert "401" in feed
    assert log == ""


def _find_event_fn(app_module, name):
    for dependency in app_module.demo.fns.values():
        if getattr(dependency.fn, "__name__", None) == name:
            return dependency.fn
    raise AssertionError(f"no event handler named {name} found")
