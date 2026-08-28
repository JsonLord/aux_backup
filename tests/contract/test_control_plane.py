from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.executor import JobExecutor
from apps.api.store import Store


def client(tmp_path: Path, legacy_provider=None):
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    return TestClient(create_app(store, legacy_provider=legacy_provider)), store


def test_read_only_workspace_role_cannot_mutate(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    def viewer(): return {"workspace_id": "alpha", "owner_user_id": "user-a", "role": "read"}
    api = TestClient(create_app(store, identity_provider=viewer))
    assert api.get("/v1/me").status_code == 200
    response = api.post("/v1/sessions", json={})
    assert response.status_code == 403


def test_health_session_job_idempotency_and_ordered_events(tmp_path):
    api, store = client(tmp_path)
    assert api.get("/healthz").status_code == 200
    session = api.post("/v1/sessions", json={}).json()
    payload = {"session_id": session["session_id"], "type": "fixture.noop", "idempotency_key": "same"}
    first = api.post("/v1/jobs", json=payload)
    duplicate = api.post("/v1/jobs", json=payload)
    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert first.json()["job_id"] == duplicate.json()["job_id"]
    store.event(first.json()["job_id"], "fixture.second", .5, {})
    events = api.get(f'/v1/jobs/{first.json()["job_id"]}/events').json()["items"]
    sequences = [item["sequence"] for item in events]
    assert sequences == list(range(1, len(sequences) + 1))


def test_artifact_is_persistent_across_store_instances(tmp_path):
    api, _ = client(tmp_path)
    session_id = api.post("/v1/sessions", json={}).json()["session_id"]
    artifact = api.post("/v1/artifacts", json={"session_id": session_id, "kind": "fixture", "content": {"saved": True}}).json()
    restarted = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    assert restarted.get_artifact(artifact["artifact_id"])["kind"] == "fixture"
    assert Path(artifact["path"]).read_text().strip().startswith("{")


def test_combined_test_executes_and_exposes_result_and_attempt(tmp_path):
    api, _ = client(tmp_path)
    session_id = api.post("/v1/sessions", json={}).json()["session_id"]
    persona = api.post("/v1/artifacts", json={"session_id": session_id, "kind": "persona.profile", "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {}, "generation": {"seed": 1}}}).json()
    response = api.post("/v1/jobs", json={
        "session_id": session_id,
        "type": "combined_test",
        "input_artifacts": [persona["artifact_id"]],
        "metadata": {"url": "https://example.com", "persona_artifacts": [persona["artifact_id"]], "tasks": ["Find support"]},
    })
    assert response.status_code == 202
    job = api.get(f"/v1/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "succeeded"
    assert len(job["output_artifacts"]) == 3
    artifacts = api.get(f"/v1/sessions/{session_id}/artifacts").json()["items"]
    assert {item["kind"] for item in artifacts} >= {"ux.report", "ux.presentation", "journey.log"}
    assert all(item["metadata"].get("download_name") for item in artifacts if item["kind"] != "persona.profile")
    presentation = next(item for item in artifacts if item["kind"] == "ux.presentation")
    download = api.get(f"/v1/artifacts/{presentation['artifact_id']}/content")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["content-disposition"].endswith('.html"')
    assert b"UX analysis" in download.content
    assert api.get(f"/v1/jobs/{job['job_id']}/result").json()["artifacts"][0]["kind"] == "ux.report"
    assert api.get(f"/v1/jobs/{job['job_id']}/attempts").json()["items"][0]["status"] == "succeeded"


def test_failure_is_structured_and_session_deletion_removes_records(tmp_path):
    api, _ = client(tmp_path)
    session_id = api.post("/v1/sessions", json={}).json()["session_id"]
    job_id = api.post("/v1/jobs", json={"session_id": session_id, "type": "unknown"}).json()["job_id"]
    job = api.get(f"/v1/jobs/{job_id}").json()
    assert job["status"] == "failed"
    assert job["error"] == {"code": "execution_failed", "message": "unsupported job type: unknown", "retryable": False}
    assert api.delete(f"/v1/sessions/{session_id}").status_code == 204
    assert api.get(f"/v1/jobs/{job_id}").status_code == 404


def test_workspace_isolation_and_prefixed_artifact_keys(tmp_path):
    api, _ = client(tmp_path)
    alpha = {"X-Workspace-ID": "alpha", "X-User-ID": "user-a"}
    beta = {"X-Workspace-ID": "beta", "X-User-ID": "user-b"}
    session = api.post("/v1/sessions", json={}, headers=alpha).json()
    assert session["workspace_id"] == "alpha"
    assert session["owner_user_id"] == "user-a"
    assert api.get(f"/v1/sessions/{session['session_id']}", headers=beta).status_code == 404
    artifact = api.post("/v1/artifacts", headers=alpha, json={"session_id": session["session_id"], "kind": "fixture", "content": "tenant-safe"}).json()
    assert f"alpha/{session['session_id']}" in artifact["path"]
    assert api.get(f"/v1/artifacts/{artifact['artifact_id']}/content", headers=beta).status_code == 404
    beta_session = api.post("/v1/sessions", json={}, headers=beta).json()
    assert [item["session_id"] for item in api.get("/v1/sessions", headers=alpha).json()["items"]] == [session["session_id"]]
    alpha_job = api.post("/v1/jobs", headers=alpha, json={"session_id": session["session_id"], "type": "unknown", "idempotency_key": "same"}).json()
    beta_job = api.post("/v1/jobs", headers=beta, json={"session_id": beta_session["session_id"], "type": "unknown", "idempotency_key": "same"}).json()
    assert alpha_job["job_id"] != beta_job["job_id"]
    assert alpha_job["idempotency_key"] == beta_job["idempotency_key"] == "same"


def test_waiting_dependency_is_rescheduled_after_success(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile", "content_type": "application/json", "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {}, "generation": {"seed": 1}}, "metadata": {}})
    base = {"session_id": session["session_id"], "type": "combined_test", "version": "1.0", "pipeline_run_id": None, "input_artifacts": [persona["artifact_id"]], "seed": 1, "metadata": {"url": "https://example.com", "persona_artifacts": [persona["artifact_id"]], "tasks": ["Find help"]}, "idempotency_key": None}
    dependency, _ = store.create_job({**base, "depends_on": []})
    dependent, _ = store.create_job({**base, "depends_on": [dependency["job_id"]]})
    executor = JobExecutor(store)
    executor.run(dependent["job_id"])
    assert store.get_job(dependent["job_id"])["status"] == "waiting_on_dependency"
    executor.run(dependency["job_id"])
    assert store.get_job(dependent["job_id"])["status"] == "succeeded"
    assert "job.dependencies_satisfied" in [event["type"] for event in store.events(dependent["job_id"])]


def test_only_one_executor_can_claim_a_job(tmp_path):
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    job, _ = store.create_job({"session_id": session["session_id"], "type": "unknown", "version": "1.0", "pipeline_run_id": None, "depends_on": [], "input_artifacts": [], "seed": None, "metadata": {}, "idempotency_key": None})
    assert store.claim_job(job["job_id"])["status"] == "claimed"
    assert store.claim_job(job["job_id"]) is None


def test_persona_snapshots_reach_worker_and_persist_in_report(tmp_path, monkeypatch):
    import json
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    profiles = [{"id": f"persona_{name.lower()}", "source": "manual", "persona": {"name": name}, "abilities": {}, "behavior": {"patience": patience}, "generation": {"seed": seed, "model": "fixture", "compilerVersion": "1"}} for name, patience, seed in (("Ada", .8, 1), ("Lin", .2, 2))]
    artifacts = [store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile", "content_type": "application/json", "content": profile, "metadata": {"immutable_run_snapshot": True}}) for profile in profiles]
    received = []

    class WorkerResponse:
        def __init__(self, request): self.request = request
        def __enter__(self):
            payload = json.loads(self.request.data)
            received.append(payload["profile"])
            self.payload = json.dumps({"runId": payload["runId"], "simulationProfile": payload["profile"], "steps": []}).encode()
            return self
        def __exit__(self, *args): pass
        def read(self): return self.payload

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", lambda request, timeout: WorkerResponse(request))
    ids = [artifact["artifact_id"] for artifact in artifacts]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0", "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1, "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Find help"]}, "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    report = json.loads(store.read_artifact(completed["output_artifacts"][0]))
    assert received == profiles
    assert report["synthetic_users"] == profiles
    assert [run["simulationProfile"] for run in report["journey_outcome"]["runs"]] == profiles


def test_report_pain_points_are_derived_from_real_journeytest_verdict_not_hardcoded(tmp_path, monkeypatch):
    """critical_pain_points must reflect the JourneyTest run's own AgentVerdict
    (blockers/uxFindings/suggestedImprovements/failed criteria) -- a genuine,
    per-run, evidence-grounded outcome -- rather than a fixed per-task sentence
    that's the same regardless of what the browser run actually found."""
    import json as json_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {}, "generation": {"seed": 1}},
        "metadata": {}})

    verdict = {
        "status": "failed", "confidence": "high", "summary": "Checkout could not be completed.",
        "criteria": [{"id": "tasks-completed", "result": "not-met", "explanation": "Checkout button never appeared."},
                     {"id": "tasks-blocked", "result": "blocked", "explanation": "Blocked by an infinite spinner.",
                      "evidence": {"screenshot": "/tmp/run/screenshots/003.png"}}],
        "blockers": [{"id": "blocker-1", "severity": "critical", "category": "blocker",
                      "title": "Checkout spinner never resolves",
                      "description": "The spinner after clicking 'Buy' spins indefinitely.",
                      "evidence": {"screenshot": "/tmp/run/screenshots/003.png", "observation": "Spinner visible for 30s+"},
                      "recommendation": "Add a timeout and error state to the checkout request."}],
        "uxFindings": [{"id": "finding-1", "severity": "minor", "category": "ui",
                        "title": "Low-contrast price label", "description": "Price text is hard to read on the card background."}],
        "suggestedImprovements": [],
    }

    class WorkerResponse:
        def __init__(self, request): self.request = request
        def __enter__(self):
            payload = json_module.loads(self.request.data)
            self.payload = json_module.dumps({"runId": payload["runId"], "runStatus": "completed",
                "profileId": "persona_ada", "verdict": verdict, "simulationProfile": payload["profile"]}).encode()
            return self
        def __exit__(self, *args): pass
        def read(self): return self.payload

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", lambda request, timeout: WorkerResponse(request))
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))

    findings = report["critical_pain_points"]
    assert report["evidence_language"] == "observed"
    titles = {item["title"] for item in findings}
    assert "Checkout spinner never resolves" in titles
    assert "Low-contrast price label" in titles
    assert any(item["source"] == "criteria" and "tasks-blocked" in item["title"] for item in findings)
    assert not any("Validate task clarity" in item["title"] for item in findings)

    blocker = next(item for item in findings if item["title"] == "Checkout spinner never resolves")
    assert blocker["severity"] == "critical"
    assert "screenshot: /tmp/run/screenshots/003.png" in blocker["evidence"]
    assert blocker["recommendation"] == "Add a timeout and error state to the checkout request."

    ux_finding = next(item for item in findings if item["title"] == "Low-contrast price label")
    assert ux_finding["severity"] == "medium"  # journeytest "minor" maps to report "medium"


def test_passed_run_with_unblocked_fail_criterion_reports_no_pain_point(tmp_path, monkeypatch):
    """Regression test for a bug found in a live smoke test against the real
    JourneyTest engine: journeyContract() emits one pass criterion
    ("tasks-completed") and one fail criterion ("tasks-blocked"). For the fail
    criterion, result "not-met" means the failure condition did NOT occur --
    that's the GOOD outcome and must not be reported as a pain point. (Verified
    live: a real run against https://example.com returned verdict.status
    "passed" with criteria [{"id": "tasks-completed", "result": "met"},
    {"id": "tasks-blocked", "result": "not-met"}], and the pre-fix code
    incorrectly flagged the second one as a "high" severity pain point.)"""
    import json as json_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_fw", "persona": {"name": "Friedrich Wolf"}, "abilities": {}, "behavior": {}, "generation": {"seed": 1}},
        "metadata": {}})

    verdict = {
        "status": "passed", "confidence": "high", "summary": "Understood the page.",
        "criteria": [{"id": "tasks-completed", "result": "met", "explanation": "Task completed."},
                     {"id": "tasks-blocked", "result": "not-met", "explanation": "No blocking issue occurred."}],
        "blockers": [], "uxFindings": [], "suggestedImprovements": [],
    }

    class WorkerResponse:
        def __init__(self, request): self.request = request
        def __enter__(self):
            payload = json_module.loads(self.request.data)
            self.payload = json_module.dumps({"runId": payload["runId"], "runStatus": "completed",
                "profileId": "persona_fw", "verdict": verdict, "simulationProfile": payload["profile"]}).encode()
            return self
        def __exit__(self, *args): pass
        def read(self): return self.payload

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", lambda request, timeout: WorkerResponse(request))
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Understand the page"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))

    findings = report["critical_pain_points"]
    assert not any(item["source"] == "criteria" for item in findings), findings
    assert findings[0]["title"] == "No pain points detected"


def test_vision_critique_pairs_screenshot_with_its_snapshot_and_crops_the_finding(tmp_path, monkeypatch):
    """Stage 2 of the two-stage UX feedback model: real screenshots from a
    JourneyTest run get critiqued by a (mocked) vision model, matched to their
    semantic snapshot by filename stem so a finding can reference a real element
    and get a cropped image of exactly the region it's about."""
    import json as json_module
    from PIL import Image

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "minibio": "A busy shopper",
                    "abilities": {}, "behavior": {}, "generation": {"seed": 1}},
        "metadata": {}})

    run_dir = tmp_path / "run"
    (run_dir / "screenshots").mkdir(parents=True)
    (run_dir / "snapshots").mkdir(parents=True)
    screenshot_path = run_dir / "screenshots" / "step1.png"
    Image.new("RGB", (200, 150), color="white").save(screenshot_path)
    snapshot_path = run_dir / "snapshots" / "step1.json"
    snapshot_path.write_text(json_module.dumps({"elements": [
        {"selector": "#buy-button", "role": "button", "text": "Buy", "boundingBox": {"x": 20, "y": 30, "width": 60, "height": 20}},
    ]}))

    verdict = {"status": "passed", "confidence": "high", "summary": "Task completed.",
        "criteria": [{"id": "tasks-completed", "result": "met"}, {"id": "tasks-blocked", "result": "not-met"}],
        "blockers": [], "uxFindings": [], "suggestedImprovements": []}

    def dispatch(req, timeout):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        payload = json_module.loads(req.data)
        if req.full_url.endswith("/v1/runs"):
            return Response(json_module.dumps({"runId": payload["runId"], "runStatus": "completed",
                "profileId": "persona_ada", "verdict": verdict, "simulationProfile": payload["profile"],
                "artifacts": {"screenshots": [str(screenshot_path)], "snapshots": [str(snapshot_path)]}}).encode())
        assert req.full_url.endswith("/v1/journey-evidence-analyses")
        assert payload["elements"][0]["selector"] == "#buy-button"
        assert payload["personaSummary"] == "A busy shopper"
        return Response(json_module.dumps({"schemaVersion": "1.0", "findings": [
            {"category": "accessibility", "severity": "high", "elementSelector": "#buy-button",
             "title": "Ambiguous button label", "description": "The label does not describe the action.",
             "recommendation": "Use 'Complete purchase'.", "box": {"x": 20, "y": 30, "width": 60, "height": 20},
             "grounding": {"status": "completed", "references": [{"source": "Nielsen Norman Group", "principle": "Usability heuristic 1"}]}},
        ]}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setenv("EYESON_WORKER_URL", "http://eyeson.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))

    vision_findings = [item for item in report["critical_pain_points"] if item["source"] == "eyeson-vision"]
    assert len(vision_findings) == 1
    finding = vision_findings[0]
    assert finding["title"] == "Ambiguous button label"
    assert finding["severity"] == "high"
    assert "#buy-button" in finding["evidence"]
    assert "Nielsen Norman Group" in finding["evidence"]
    assert finding["screenshotCrop"].startswith("data:image/png;base64,")
    # No stage-1 findings (verdict passed cleanly) and no misleading "No pain
    # points detected" alongside a real stage-2 finding.
    assert not any(item["title"] == "No pain points detected" for item in report["critical_pain_points"])

    presentation = store.read_artifact(completed["output_artifacts"][1]).decode("utf-8")
    assert "Ambiguous button label" in presentation
    assert '<img src="data:image/png;base64,' in presentation


def test_vision_findings_seen_on_multiple_screenshots_are_deduped_not_repeated():
    """Regression test for a live observation: the same page-wide rendering bug
    was independently flagged on two different sampled screenshots from one run,
    producing two near-identical "Infinite repetition of page content" findings
    in the report. That reads as noise, not confirmation -- collapse them."""
    findings = [
        {"severity": "critical", "category": "usability", "title": "Infinite repetition of page content",
         "summary": "The hero section repeats down the page.", "recommendation": "Fix the render loop.",
         "evidence": "screenshot: /run/screenshots/001.png", "source": "eyeson-vision", "runId": "run1", "personaId": "p1"},
        {"severity": "critical", "category": "usability", "title": "Infinite repetition of page content",
         "summary": "The layout repeats vertically many times.", "recommendation": "Check the layout component.",
         "evidence": "screenshot: /run/screenshots/007.png", "source": "eyeson-vision", "runId": "run1", "personaId": "p1"},
        {"severity": "medium", "category": "accessibility", "title": "Low contrast form labels",
         "summary": "Labels are hard to read.", "evidence": "screenshot: /run/screenshots/001.png",
         "source": "eyeson-vision", "runId": "run1", "personaId": "p1"},
    ]
    deduped = JobExecutor._dedupe_vision_findings(findings)
    assert len(deduped) == 2
    repetition = next(item for item in deduped if item["title"] == "Infinite repetition of page content")
    assert repetition["severity"] == "critical"
    assert "seen on 2 screenshots" in repetition["evidence"]
    assert "001.png" in repetition["evidence"] and "007.png" in repetition["evidence"]
    contrast = next(item for item in deduped if item["title"] == "Low contrast form labels")
    assert contrast["evidence"] == "screenshot: /run/screenshots/001.png"  # single occurrence, not rewritten


def test_ui_adaptation_calls_the_configured_llm_for_a_real_prototype(tmp_path, monkeypatch):
    """ui_adaptation jobs must actually ask the model to implement the requested
    change, including revising the previous prototype for iterative chat-based
    adaptation, instead of always returning the same fixed HTML template regardless
    of what was requested."""
    import services.persona_service.semantic as semantic_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured = {}

    def fake_complete_text(self, system_prompt, user_prompt, **kwargs):
        captured["system_prompt"], captured["user_prompt"] = system_prompt, user_prompt
        return "```html\n<html><body><h1>Emerald button</h1></body></html>\n```"

    monkeypatch.setattr(semantic_module.DirectLLMSemanticEngine, "complete_text", fake_complete_text)

    job, _ = store.create_job({"session_id": session["session_id"], "type": "ui_adaptation", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": [], "seed": None,
        "metadata": {"title": "Interactive UI adaptation", "request": "Change primary color to emerald",
                     "previous_html": "<html><body><h1>Old button</h1></body></html>"},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    html = store.read_artifact(completed["output_artifacts"][0]).decode("utf-8")

    assert "Emerald button" in html
    assert not html.strip().startswith("```")
    assert "Change primary color to emerald" in captured["user_prompt"]
    assert "Old button" in captured["user_prompt"]  # previous prototype passed through for revision


def test_ui_adaptation_falls_back_to_static_template_without_llm_credentials(tmp_path, monkeypatch):
    for var in ("OPENAI_API_KEY", "BLABLADOR_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    job, _ = store.create_job({"session_id": session["session_id"], "type": "ui_adaptation", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": [], "seed": None,
        "metadata": {"title": "UX solution prototype", "request": "Improve clarity"}, "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    html = store.read_artifact(completed["output_artifacts"][0]).decode("utf-8")
    assert "Offline fallback" in html
    assert "Improve clarity" in html


def test_existing_sqlite_schema_receives_additive_tenant_columns(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, metadata TEXT NOT NULL, external_ref TEXT NOT NULL)")
        db.execute("INSERT INTO sessions VALUES ('ses_old','now','{}','{}')")
    store = Store(f"sqlite:///{database}", str(tmp_path / "artifacts"))
    migrated = store.get_session("ses_old")
    assert migrated["workspace_id"] == "local"
    assert migrated["owner_user_id"] == "local"


def test_legacy_github_import_creates_read_only_session_and_artifacts(tmp_path):
    class LegacyFixture:
        def list_branches(self, repository):
            assert repository == "owner/repo"
            return [{"name": "ux-old", "commit_sha": "abc", "read_only": True}]

        def read_artifacts(self, repository, branch):
            assert (repository, branch) == ("owner/repo", "ux-old")
            return [{"path": "user_experience_reports/report.md", "content": b"# Legacy report", "sha": "abc"}]

    api, _ = client(tmp_path, LegacyFixture())
    headers = {"X-Workspace-ID": "alpha", "X-User-ID": "user-a"}
    branches = api.get("/v1/legacy/github/branches", params={"repository": "owner/repo"}, headers=headers)
    assert branches.json()["items"][0]["read_only"] is True
    imported = api.post("/v1/legacy/github/import", headers=headers, json={"repository": "owner/repo", "branch": "ux-old"})
    assert imported.status_code == 201
    result = imported.json()
    assert result["read_only"] is True and result["imported"] == 1
    assert result["session"]["workspace_id"] == "alpha"
    session = api.get(f"/v1/sessions/{result['session']['session_id']}", headers=headers).json()
    assert session["external_ref"] == {"provider": "github", "repository": "owner/repo", "branch": "ux-old"}


def test_artifact_retention_and_pinning(tmp_path):
    api, store = client(tmp_path)
    session_id = api.post("/v1/sessions", json={}).json()["session_id"]
    raw = api.post("/v1/artifacts", json={"session_id": session_id, "kind": "screenshot", "retention_class": "raw", "content": "pixels"}).json()
    structured = api.post("/v1/artifacts", json={"session_id": session_id, "kind": "report", "retention_class": "structured", "content": "report"}).json()
    assert datetime.fromisoformat(raw["expires_at"]) < datetime.fromisoformat(structured["expires_at"])
    pinned = api.patch(f"/v1/artifacts/{raw['artifact_id']}/pin", json={"pinned": True}).json()
    assert pinned["pinned"] == 1
    future = (datetime.now(timezone.utc) + timedelta(days=181)).isoformat()
    assert store.delete_expired_artifacts(future) == 1
    assert store.get_artifact(raw["artifact_id"]) is not None
    assert store.get_artifact(structured["artifact_id"]) is None
