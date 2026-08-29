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
    assert len(job["output_artifacts"]) == 4
    artifacts = api.get(f"/v1/sessions/{session_id}/artifacts").json()["items"]
    assert {item["kind"] for item in artifacts} >= {"ux.report", "ux.presentation", "ux.slides", "journey.log"}
    assert all(item["metadata"].get("download_name") for item in artifacts if item["kind"] != "persona.profile")
    presentation = next(item for item in artifacts if item["kind"] == "ux.presentation")
    download = api.get(f"/v1/artifacts/{presentation['artifact_id']}/content")
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.headers["content-disposition"].endswith('.html"')
    assert b"UX analysis" in download.content
    assert api.get(f"/v1/jobs/{job['job_id']}/result").json()["artifacts"][0]["kind"] == "ux.report"
    assert api.get(f"/v1/jobs/{job['job_id']}/attempts").json()["items"][0]["status"] == "succeeded"


def test_combined_test_forwards_browser_safety_opt_in_to_journey_worker(tmp_path, monkeypatch):
    """services/journey-worker/node/src/safety.js blocks any task whose text
    matches a destructive-action pattern (purchase, delete account, deploy
    production, ...) unless browserSafety.allowIrreversibleActions is
    explicitly set (spec.md section 36). The control plane must actually
    forward a caller's opt-in to the /v1/runs payload -- previously this key
    was never included at all, so no caller had any way to opt in."""
    import json as json_module

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {}, "generation": {"seed": 1}},
        "metadata": {}})
    received = []

    class WorkerResponse:
        def __init__(self, request): self.request = request
        def __enter__(self):
            payload = json_module.loads(self.request.data)
            received.append(payload.get("browserSafety"))
            self.payload = json_module.dumps({"runId": payload["runId"], "simulationProfile": payload["profile"], "steps": []}).encode()
            return self
        def __exit__(self, *args): pass
        def read(self): return self.payload

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", lambda request, timeout: WorkerResponse(request))
    ids = [persona["artifact_id"]]

    no_opt_in, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(no_opt_in["job_id"])
    assert store.get_job(no_opt_in["job_id"])["status"] == "succeeded"
    assert received[-1] == {}

    opted_in, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"],
                    "browserSafety": {"allowIrreversibleActions": True}},
        "idempotency_key": None})
    JobExecutor(store).run(opted_in["job_id"])
    assert store.get_job(opted_in["job_id"])["status"] == "succeeded"
    assert received[-1] == {"allowIrreversibleActions": True}


def test_combined_test_surfaces_actionable_message_for_irreversible_action_rejection(tmp_path, monkeypatch):
    """When journey-worker rejects a run with the specific 422 safety.js raises
    for an un-opted-in destructive-action task, the job's error must tell the
    caller how to opt in -- not just relay the raw 422 body."""
    import io
    import json as json_module
    from urllib.error import HTTPError

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {}, "generation": {"seed": 1}},
        "metadata": {}})

    def raise_rejection(request, timeout):
        body = json_module.dumps({"error": "invalid_run",
            "message": "potentially irreversible task requires allowIrreversibleActions=true"}).encode()
        raise HTTPError(request.full_url, 422, "Unprocessable Entity", {}, io.BytesIO(body))

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", raise_rejection)
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Delete your account"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "failed"
    assert "did not opt in" in completed["error"]["message"]
    assert "allow_irreversible_actions" in completed["error"]["message"]


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


def test_vision_critique_synthesizes_across_personas_with_element_crop(tmp_path, monkeypatch):
    """Stage 2 of the two-stage UX feedback model: real screenshots from a
    JourneyTest run get critiqued by a (mocked) vision model, matched to their
    semantic snapshot by filename stem so a finding can reference a real
    element and get a cropped image of the region it's about. The two
    personas' pain points then go through real cross-persona synthesis
    (aggregateCohort, mocked here at the HTTP boundary since it's already
    covered directly by services/eyeson-worker/node/test/visionCritique.test.js)
    -- the report must show the synthesized result, not per-persona citations."""
    import json as json_module
    from PIL import Image

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    personas = [store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": pid, "persona": {"name": name}, "minibio": f"A {name} persona",
                    "abilities": {}, "behavior": {}, "generation": {"seed": 1}},
        "metadata": {}}) for pid, name in [("persona_ada", "impatient"), ("persona_lin", "patient")]]

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

    def pain_point(pid, run_id):
        return {"id": f"pain_{pid}", "runId": run_id, "userId": pid, "route": "https://example.com",
            "stepIds": ["vision-1"], "title": "Ambiguous button label",
            "summary": "The label does not describe the action.", "severity": "high", "category": "accessibility",
            "confidence": 0.7, "screenshotRef": str(screenshot_path), "videoTimestampMs": 0,
            "behavioralImpact": {"frustrationDelta": 0.4, "confusionDelta": 0.3, "trustDelta": -0.1,
                "cognitiveEffortDelta": 0, "physicalEffortDelta": 0, "elapsedCostMs": 0, "retries": 0, "backtracks": 0},
            "elements": [{"elementId": "#buy-button", "box": {"x": 20, "y": 30, "width": 60, "height": 20},
                "role": "trigger", "contribution": 1, "confidence": 0.7}],
            "diagnosis": {"category": "accessibility", "mechanism": "The label does not describe the action.",
                "rootCause": "Ambiguous button label", "observedEvidence": [], "behavioralEvidence": [],
                "personaInteraction": "", "confidence": 0.7},
            "grounding": {"status": "completed", "references": [{"source": "Nielsen Norman Group", "principle": "Usability heuristic 1"}]},
            "alternatives": [{"id": f"alt_{pid}", "title": "accessibility alternative", "strategy": "accessibility",
                "proposedChange": "Use 'Complete purchase'.", "rationale": "Names the action.",
                "addressesPainPointIds": [f"pain_{pid}"], "expectedImpact": {}, "effort": "low", "confidence": 0.7, "grounding": []}],
            "overlays": []}

    def dispatch(req, timeout):
        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        payload = json_module.loads(req.data)
        if req.full_url.endswith("/v1/runs"):
            return Response(json_module.dumps({"runId": payload["runId"], "runStatus": "completed",
                "profileId": payload["profile"]["id"], "verdict": verdict, "simulationProfile": payload["profile"],
                "artifacts": {"screenshots": [str(screenshot_path)], "snapshots": [str(snapshot_path)]}}).encode())
        if req.full_url.endswith("/v1/journey-evidence-analyses"):
            assert payload["elements"][0]["selector"] == "#buy-button"
            return Response(json_module.dumps({"schemaVersion": "1.0",
                "painPoints": [pain_point(payload["userId"], payload["runId"])]}).encode())
        assert req.full_url.endswith("/v1/cohort-aggregation")
        runs = payload["runs"]
        assert {run["profileId"] for run in runs} == {"persona_ada", "persona_lin"}
        all_points = [point for run in runs for point in run["painPoints"]]
        assert len(all_points) == 2  # one per persona, both fed into aggregation
        return Response(json_module.dumps({"schemaVersion": "1.0", "rootCauses": [{
            "id": "root_1", "signature": "sig", "category": "accessibility",
            "mechanism": "The label does not describe the action.", "elementIds": ["#buy-button"],
            "painPointIds": [point["id"] for point in all_points],
            "affectedUsers": ["persona_ada", "persona_lin"], "affectedIterations": [run["runId"] for run in runs],
            "averageStateImpact": {"frustration": 0.4, "confusion": 0.3, "trust": -0.1}, "abandonmentCount": 0,
            "personaSusceptibility": {"patience": -0.9},
            "alternatives": [all_points[0]["alternatives"][0]],
        }]}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setenv("EYESON_WORKER_URL", "http://eyeson.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    ids = [persona["artifact_id"] for persona in personas]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))

    vision_findings = [item for item in report["critical_pain_points"] if item["source"] == "eyeson-vision-synthesis"]
    assert len(vision_findings) == 1
    finding = vision_findings[0]
    assert finding["title"] == "Ambiguous button label"
    assert finding["severity"] == "high"
    assert finding["affectedPersonas"] == 2
    assert "2 observation(s) across 2 persona(s)" in finding["evidence"]
    assert finding["recommendation"] == "Use 'Complete purchase'."
    assert finding["screenshotCrop"].startswith("data:image/png;base64,")
    # Real knowledge grounding (WCAG/Nielsen-Norman references) is computed per
    # observation in visionCritique.js but aggregateCohort's root-cause groups
    # don't carry it -- must survive synthesis onto the report finding, not get
    # silently dropped at this step.
    assert finding["grounding"] == {"status": "completed",
        "references": [{"source": "Nielsen Norman Group", "principle": "Usability heuristic 1"}]}
    # Not a per-persona citation list -- one synthesized finding, not two.
    assert len([item for item in report["critical_pain_points"] if "Ambiguous button label" in item["title"]]) == 1
    assert not any(item["title"] == "No pain points detected" for item in report["critical_pain_points"])

    presentation = store.read_artifact(completed["output_artifacts"][1]).decode("utf-8")
    assert "Ambiguous button label" in presentation
    assert '<img src="data:image/png;base64,' in presentation
    assert "Grounded in:" in presentation and "Nielsen Norman Group" in presentation

    slides = store.read_artifact(completed["output_artifacts"][2]).decode("utf-8")
    assert "Grounded in:" in slides and "Nielsen Norman Group" in slides


def test_slide_deck_follows_usability_review_anatomy():
    """Real local slide generation (no GitHub, no external mkslides binary --
    see docs/aux-space-status-overview.md), shaped like a usability review deck
    rather than a flat findings list: title, contents, a numbered introduction /
    issues / elements-to-preserve structure, each issue stated as
    issue -> root cause -> recommendation beside its evidence, and self-contained
    keyboard/click navigation in one HTML file."""
    report = {
        "url": "https://example.com", "executive_summary": "Tested with 2 personas.",
        "evidence_language": "observed",
        "journey_outcome": {"tasks": ["Buy an item"]},
        "impact_analysis": {"personasTested": 2, "findingsBySeverity": {"critical": 1, "medium": 1},
                            "priorityOrder": [{"title": "Infinite repetition of page content",
                                               "severity": "critical", "affectedPersonas": 2}]},
        "elements_to_preserve": [
            {"title": "Consistent buttons", "description": "Every control is the same rounded rectangle.",
             "observedByPersonas": 2},
        ],
        "critical_pain_points": [
            {"severity": "critical", "category": "usability", "title": "Infinite repetition of page content",
             "affectedPersonas": 2, "summary": "The hero section repeats down the page.",
             "rootCause": "The list renderer never terminates.",
             "alternatives": [{"proposedChange": "Fix the render loop."}],
             "screenshotCrop": "data:image/png;base64,Zm9v",
             "personaEvidence": [{"personaName": "Ada", "quote": "I keep scrolling past the same block."}]},
            {"severity": "medium", "category": "accessibility", "title": "Low contrast form labels",
             "summary": "Labels are hard to read.", "recommendation": "Increase contrast."},
        ],
    }
    html = JobExecutor._slide_deck(report)

    # Review anatomy: numbered sections, not a flat list.
    assert "Contents" in html
    assert ">01<" in html and ">02<" in html and ">03<" in html
    assert "Introduction" in html and "User issues" in html and "Elements to preserve" in html
    assert "02.1" in html and "02.2" in html  # one numbered sub-divider per issue

    # A real browser run was observed, so the deck must not call the issues "predicted".
    assert "Observed user issue" in html
    assert "Predicted user issue" not in html

    # Issue -> root cause -> recommendation, plus the persona's own words as evidence.
    assert "Root cause analysis" in html and "The list renderer never terminates." in html
    assert "Recommendations: design solutions" in html and "Fix the render loop." in html
    assert "In the user's words" in html and "I keep scrolling past the same block." in html
    assert "Ada" in html

    assert "Low contrast form labels" in html
    assert "Increase contrast." in html  # recommendation falls back into "what to change"
    assert "Current design" in html and '<img src="data:image/png;base64,Zm9v"' in html
    assert "Consistent buttons" in html  # elements to preserve section rendered
    assert "What to fix first" in html  # designer-facing impact ordering
    assert "ArrowRight" in html and "ArrowLeft" in html  # keyboard navigation wired

    empty_html = JobExecutor._slide_deck({"url": "https://example.com", "critical_pain_points": []})
    assert "No findings" in empty_html


def test_slide_deck_says_predicted_when_no_browser_evidence_was_collected():
    """Honesty about evidence class: without a live run the deck must claim no more
    than a heuristic walkthrough does."""
    html = JobExecutor._slide_deck({
        "url": "https://example.com", "evidence_language": "inferred",
        "critical_pain_points": [{"severity": "medium", "category": "ux", "title": "Validate task clarity",
                                  "summary": "Inferred from the configured task."}],
    })
    assert "Predicted user issue" in html
    assert "Observed user issue" not in html


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


def test_persona_thoughts_extract_real_reasoning_and_drop_plumbing():
    """journeytest-core stores the model's reasoning in agent.message.end's
    data.text; the event's own summary is the fixed literal "Assistant message
    ended", so a narration built from summaries alone contains no thinking."""
    journey = {"timeline": [
        {"type": "journey.started", "summary": "Started journey", "elapsedMs": 0},
        {"type": "agent.message.end", "summary": "Assistant message ended", "elapsedMs": 100,
         "data": {"text": "I cannot find the checkout button.", "toolCalls": ["browser_click"]}},
        {"type": "browser.screenshot", "summary": "Captured screenshot", "elapsedMs": 150},
        {"type": "browser.click", "summary": "Clicked #cart", "elapsedMs": 200},
        {"type": "agent.message.end", "summary": "Assistant message ended", "elapsedMs": 250, "data": {"text": "  "}},
    ]}

    thoughts = JobExecutor._persona_thoughts(journey)

    assert [item["kind"] for item in thoughts] == ["reasoning", "action"]
    assert thoughts[0]["text"] == "I cannot find the checkout button."
    assert thoughts[0]["toolCalls"] == ["browser_click"]
    assert thoughts[1]["text"] == "Clicked #cart"
    assert all("Captured screenshot" not in item["text"] for item in thoughts)


def test_persona_thoughts_keep_reasoning_when_truncating():
    """Actions are plentiful and reasoning is scarce; a cap must not drop the
    reasoning, which is the only part that explains a finding."""
    journey = {"timeline": (
        [{"type": "browser.click", "summary": f"Clicked #{index}", "elapsedMs": index} for index in range(20)]
        + [{"type": "agent.message.end", "summary": "Assistant message ended", "elapsedMs": 99,
            "data": {"text": "This layout confuses me."}}]
    )}

    thoughts = JobExecutor._persona_thoughts(journey, limit=3)

    assert len(thoughts) == 3
    assert any(item["kind"] == "reasoning" and item["text"] == "This layout confuses me." for item in thoughts)


def test_merge_strengths_collapses_the_same_decision_across_personas():
    merged = JobExecutor._merge_strengths([
        {"title": "Consistent buttons", "description": "Rounded rectangles.", "personaId": "p1",
         "route": "https://example.com", "screenshotRef": "/a.png", "elements": []},
        {"title": "consistent buttons", "description": "Rounded rectangles.", "personaId": "p2",
         "route": "https://example.com", "screenshotRef": "/b.png", "elements": []},
        {"title": "Simple palette", "description": "Few colours.", "personaId": "p1",
         "route": "https://example.com", "screenshotRef": "/a.png", "elements": []},
    ])

    assert [item["title"] for item in merged] == ["Consistent buttons", "Simple palette"]
    assert merged[0]["observedByPersonas"] == 2
    assert merged[0]["screenshotRefs"] == ["/a.png", "/b.png"]
    assert merged[1]["observedByPersonas"] == 1


def test_preserved_from_verdicts_uses_met_pass_criteria_only():
    """A met pass criterion is a flow that worked; the fail criterion
    ("tasks-blocked") being met is the opposite and must never be praised."""
    preserved = JobExecutor._preserved_from_verdicts([
        {"profileId": "p1", "verdict": {"criteria": [
            {"id": "tasks-completed", "result": "met", "explanation": "All tasks completed."},
            {"id": "tasks-blocked", "result": "met", "explanation": "The run was blocked."},
            {"id": "nav-usable", "result": "not-met"},
        ]}},
        {"profileId": "p2", "verdict": {"criteria": [{"id": "tasks-completed", "result": "met"}]}},
    ])

    assert [item["title"] for item in preserved] == ["Flow completes: tasks-completed"]
    assert preserved[0]["observedByPersonas"] == 2


def test_impact_analysis_orders_by_severity_then_reach():
    impact = JobExecutor._impact_analysis([
        {"title": "Medium wide", "severity": "medium", "affectedPersonas": 5, "category": "ux"},
        {"title": "Critical narrow", "severity": "critical", "affectedPersonas": 1, "category": "blocker",
         "susceptibleTraits": ["patience"]},
        {"title": "High wide", "severity": "high", "affectedPersonas": 4, "category": "ux",
         "susceptibleTraits": ["patience"]},
    ], personas=[{"id": "p1"}, {"id": "p2"}])

    assert [entry["title"] for entry in impact["priorityOrder"]] == ["Critical narrow", "High wide", "Medium wide"]
    assert impact["blockingCount"] == 2
    assert impact["personasTested"] == 2
    assert impact["mostSusceptibleTraits"] == ["patience"]


def test_attach_persona_evidence_quotes_every_affected_persona():
    findings = [
        {"title": "Synthesized", "affectedPersonaIds": ["p1", "p2"]},
        {"title": "Single persona", "personaId": "p1"},
        {"title": "No persona"},
    ]
    thoughts = {
        "p1": [{"kind": "action", "text": "Clicked"}, {"kind": "reasoning", "text": "I am lost."}],
        "p2": [{"kind": "reasoning", "text": "Where is the button?"}],
    }

    JobExecutor._attach_persona_evidence(findings, thoughts, {"p1": "Ada", "p2": "Lin"})

    assert [item["quote"] for item in findings[0]["personaEvidence"]] == ["I am lost.", "Where is the button?"]
    assert [item["personaName"] for item in findings[0]["personaEvidence"]] == ["Ada", "Lin"]
    assert findings[1]["personaEvidence"][0]["quote"] == "I am lost."
    assert "personaEvidence" not in findings[2]


def test_executive_summary_reports_what_was_found_not_what_was_prepared():
    summary = JobExecutor._executive_summary(
        "https://example.com", ["Buy"], [{"id": "p1"}],
        [{"severity": "critical", "title": "Broken"}, {"severity": "low", "title": "Nit"}],
        [{"title": "Consistent buttons"}])

    assert "2 usability issue(s) were identified" in summary
    assert "1 of them high-severity or blocking" in summary
    assert "1 design decision(s) are working" in summary

    empty = JobExecutor._executive_summary("https://example.com", ["Buy"], [{"id": "p1"}],
                                           [{"title": "No pain points detected", "severity": "low"}], [])
    assert "0 usability issue(s) were identified" in empty


def test_persona_thoughts_fall_back_to_verdict_prose_when_provider_hides_reasoning():
    """journeytest-core writes only assistant `text` content blocks into
    agent.message.end's data.text. A reasoning model returns its thinking in
    `thinking` blocks, which are dropped -- verified live: 12 thinking blocks in
    a run, zero events carrying data.text. Rather than report that the persona
    thought nothing, fall back to the agent's own verdict prose, labelled as
    such."""
    journey = {
        "timeline": [
            {"type": "agent.message.end", "summary": "Assistant message ended", "elapsedMs": 100,
             "data": {"contentTypes": ["thinking", "toolCall"], "toolCalls": ["browser_open"]}},
            {"type": "browser.open", "summary": "Opened https://example.com", "elapsedMs": 200},
        ],
        "verdict": {"status": "failed", "summary": "The application is inaccessible due to an HTTP error.",
                    "uxFindings": [{"title": "Error page", "description": "The error page offers no guidance."}],
                    "blockers": [{"title": "503", "description": "The site returned Service Unavailable."}]},
    }

    thoughts = JobExecutor._persona_thoughts(journey)

    reasoning = [item for item in thoughts if item["kind"] == "reasoning"]
    assert [item["source"] for item in reasoning] == ["verdict", "verdict.blockers", "verdict.uxFindings"]
    assert reasoning[0]["text"] == "The application is inaccessible due to an HTTP error."
    assert any("Service Unavailable" in item["text"] for item in reasoning)
    # The real action is still narrated, and still labelled as coming from the timeline.
    assert [item["text"] for item in thoughts if item["kind"] == "action"] == ["Opened https://example.com"]
    assert all(item["source"] == "timeline" for item in thoughts if item["kind"] == "action")


def test_persona_thoughts_prefer_live_reasoning_over_the_verdict_fallback():
    """When the provider does emit text blocks, the live per-step reasoning is
    used and the verdict fallback must not fire."""
    journey = {
        "timeline": [{"type": "agent.message.end", "summary": "Assistant message ended", "elapsedMs": 100,
                      "data": {"text": "I cannot see a checkout button anywhere."}}],
        "verdict": {"summary": "Task could not be completed."},
    }

    thoughts = JobExecutor._persona_thoughts(journey)

    assert [item["text"] for item in thoughts] == ["I cannot see a checkout button anywhere."]
    assert thoughts[0]["source"] == "timeline"
