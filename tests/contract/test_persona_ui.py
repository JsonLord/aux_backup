import json

import pytest

from apps.gradio.api_client import PersonaRuntimeClient, normalize_personas


def test_persona_json_component_accepts_list_wrappers_and_single_profiles():
    profile = {"id": "persona-1", "persona": {"name": "Ada"}}

    assert normalize_personas([profile]) == [profile]
    assert normalize_personas({"personas": [profile]}) == [profile]
    assert normalize_personas(profile) == [profile]
    assert normalize_personas(json.dumps([profile])) == [profile]


def test_persona_json_component_rejects_non_object_entries():
    with pytest.raises(ValueError, match="Persona 1 is not a JSON object"):
        normalize_personas(["not-json"])


def test_persona_generation_uses_configurable_long_running_timeout(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self): pass
        def json(self): return []

    def post(*args, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setenv("PERSONA_GENERATION_TIMEOUT", "1234")
    monkeypatch.setattr("apps.gradio.api_client.requests.post", post)

    PersonaRuntimeClient().generate("theme", "profile", 1)

    assert captured["timeout"] == 1234.0
