import json
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


class FakeSessionClient:
    def __init__(self):
        self.job_calls = []

    def create_session(self, payload):
        return {"session_id": "ses_1"}

    def create_artifact(self, session_id, kind, content, metadata=None):
        return {"artifact_id": f"art_{content['id']}"}

    def create_job(self, payload):
        self.job_calls.append(payload)
        return {"job_id": "job_1"}

    def wait_for_job(self, job_id):
        return {"job_id": job_id, "status": "succeeded", "output_artifacts": []}


def test_start_and_monitor_sessions_defaults_irreversible_actions_off(monkeypatch):
    app_module = load_root_app()
    fake = FakeSessionClient()
    monkeypatch.setattr(app_module, "authenticated_clients", lambda *a, **k: (fake, None))

    list(app_module.start_and_monitor_sessions([PROFILE], ["Buy an item"], "https://example.com", False,
                                                "ses", "local", None, None))

    assert fake.job_calls[0]["metadata"]["browserSafety"] == {"allowIrreversibleActions": False}


def test_start_and_monitor_sessions_forwards_explicit_opt_in(monkeypatch):
    app_module = load_root_app()
    fake = FakeSessionClient()
    monkeypatch.setattr(app_module, "authenticated_clients", lambda *a, **k: (fake, None))

    list(app_module.start_and_monitor_sessions([PROFILE], ["Buy an item"], "https://example.com", True,
                                                "ses", "local", None, None))

    assert fake.job_calls[0]["metadata"]["browserSafety"] == {"allowIrreversibleActions": True}


def _find_event_fn(app_module, name):
    for dependency in app_module.demo.fns.values():
        if getattr(dependency.fn, "__name__", None) == name:
            return dependency.fn
    raise AssertionError(f"no event handler named {name} found")


TIMELINE = [
    {"type": "journey.started", "summary": "Started journey j1", "elapsedMs": 0},
    {"type": "browser.open", "summary": "Opened https://example.com", "elapsedMs": 500},
    {"type": "agent.message.end", "summary": "Assistant message ended", "elapsedMs": 1200,
     "data": {"text": "I expected a Buy button near the price, but I only see a grey box.",
              "toolCalls": ["browser_click"]}},
    {"type": "browser.snapshot", "summary": "Captured snapshot", "elapsedMs": 1300},
    {"type": "browser.click", "summary": "Clicked #buy-button", "elapsedMs": 1500},
    {"type": "agent.message.error", "summary": "Assistant error: boom", "elapsedMs": 1600,
     "data": {"errorMessage": "provider timeout"}},
]


def test_thought_log_renders_real_reasoning_not_the_placeholder_summary():
    """journeytest-core's agent.message.end events carry the model's actual
    reasoning in data.text; their `summary` is always the fixed literal
    "Assistant message ended". Rendering summary alone showed none of the
    thinking this tab exists for."""
    app_module = load_root_app()
    log = json.dumps({"runs": [{"runId": "run_1", "verdict": {"status": "failed", "summary": "Blocked."},
                                "simulationProfile": {"persona": {"name": "Ada"}}, "timeline": TIMELINE}]})

    rendered = app_module.format_persona_thought_log(log)

    assert "I expected a Buy button near the price" in rendered
    assert "Assistant message ended" not in rendered
    assert "Clicked #buy-button" in rendered
    assert "provider timeout" in rendered
    assert "Captured snapshot" not in rendered  # plumbing event filtered out


def test_report_viewer_renders_review_structure_not_raw_json():
    """The Report Viewer tab dumped raw JSON while every other tab rendered its
    artifact; a ux.report must read as the review it is."""
    app_module = load_root_app()
    report = json.dumps({
        "url": "https://example.com", "evidence_language": "observed",
        "executive_summary": "1 synthetic user attempted 1 task.",
        "impact_analysis": {"priorityOrder": [{"title": "Hidden nav", "severity": "high", "affectedPersonas": 2}]},
        "critical_pain_points": [{
            "title": "Hidden nav", "severity": "high", "category": "navigation", "affectedPersonas": 2,
            "summary": "Primary navigation is inside a dropdown.",
            "rootCause": "The nav collapses at every viewport width.",
            "alternatives": [{"proposedChange": "Expose the top-level sections inline."}],
            "personaEvidence": [{"personaName": "Ada", "quote": "I cannot find the sections."}],
            "grounding": {"references": [{"source": "Nielsen Norman Group", "principle": "Heuristic 6"}]},
        }],
        "elements_to_preserve": [{"title": "Consistent buttons", "description": "One control style.",
                                  "observedByPersonas": 2}],
        "limitations": ["Observed on a single run."],
    })

    rendered = app_module.format_ux_report(report)

    assert "# Usability review" in rendered
    assert "## What to fix first" in rendered
    assert "02.1 Hidden nav" in rendered
    assert "**Observed user issue**" in rendered
    assert "**Root cause analysis**" in rendered
    assert "Expose the top-level sections inline." in rendered
    assert "I cannot find the sections." in rendered and "Ada" in rendered
    assert "Nielsen Norman Group" in rendered
    assert "## Elements to preserve" in rendered and "Consistent buttons" in rendered
    assert "## Limitations" in rendered


def test_report_viewer_falls_back_for_non_report_json():
    app_module = load_root_app()
    assert "```json" in app_module.format_ux_report('{"something": "else"}')
    assert "Could not parse" in app_module.format_ux_report("not json")


class FakeArtifactClient:
    def __init__(self, path): self.path = path
    def download_artifact(self, artifact): return self.path


def test_snapshot_overlay_pairs_with_the_screenshot_from_its_own_run(tmp_path):
    """Every persona's run produces captures with the same stems ("after-click"),
    so pairing on the stem alone would show one persona's snapshot over another
    persona's screenshot."""
    from PIL import Image
    app_module = load_root_app()
    right = tmp_path / "right.png"
    Image.new("RGB", (300, 200), color="white").save(right)

    snapshot_artifact = {"artifact_id": "art_snap", "kind": "browser.snapshot",
                         "metadata": {"capture_stem": "after-click", "run_id": "run_B"}}
    artifacts = [
        {"artifact_id": "art_a", "kind": "browser.screenshot",
         "metadata": {"capture_stem": "after-click", "run_id": "run_A"}},
        {"artifact_id": "art_b", "kind": "browser.screenshot",
         "metadata": {"capture_stem": "after-click", "run_id": "run_B"}},
        snapshot_artifact,
    ]
    content = json.dumps({"url": "https://example.com", "elements": [
        {"selector": "#buy", "role": "button", "text": "Buy",
         "boundingBox": {"x": 10, "y": 20, "width": 80, "height": 30}}]})

    picked = {}

    class Client(FakeArtifactClient):
        def download_artifact(self, artifact):
            picked["artifact_id"] = artifact["artifact_id"]
            return str(right)

    caption, html = app_module.render_snapshot_overlay(content, snapshot_artifact, artifacts, Client(str(right)))

    assert picked["artifact_id"] == "art_b"  # the screenshot from the same run
    assert "1 element(s)" in caption
    assert "data:image/png;base64," in html
    assert "left:10.0px" in html and "width:80.0px" in html  # real box drawn
    assert "#buy" in html


def test_snapshot_overlay_falls_back_to_an_element_list_without_a_screenshot():
    app_module = load_root_app()
    snapshot_artifact = {"artifact_id": "art_snap", "kind": "browser.snapshot",
                         "metadata": {"capture_stem": "lonely", "run_id": "run_A"}}
    content = json.dumps({"url": "https://example.com",
                          "elements": [{"selector": "#buy", "role": "button", "text": "Buy"}]})

    caption, html = app_module.render_snapshot_overlay(content, snapshot_artifact, [snapshot_artifact], None)

    assert "No matching screenshot" in caption
    assert "#buy" in html and "<ul" in html


def test_snapshot_overlay_reports_unparseable_json():
    app_module = load_root_app()
    caption, html = app_module.render_snapshot_overlay("not json", {"metadata": {}}, [], None)
    assert "Could not parse" in caption and html == ""
