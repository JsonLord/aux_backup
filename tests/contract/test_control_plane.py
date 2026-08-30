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
    # The criterion is still identifiable, but a report states it as a sentence
    # about the user rather than as the engine's own label.
    blocked = next(item for item in findings if item.get("criterionId") == "tasks-blocked")
    assert blocked["source"] == "criteria" and blocked["criterionResult"] == "blocked"
    assert blocked["title"] == "The journey was blocked before completion"
    assert "tasks-blocked" not in blocked["title"]
    assert not any("Validate task clarity" in item["title"] for item in findings)

    blocker = next(item for item in findings if item["title"] == "Checkout spinner never resolves")
    assert blocker["severity"] == "critical"
    assert "screenshot: 003.png" in blocker["evidence"]
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

    # Stated as something about the user, not as the engine's criterion label.
    assert [item["title"] for item in preserved] == ["Users can finish the tasks they came to do"]
    assert preserved[0]["criterionId"] == "tasks-completed"
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
        {"title": "Checkout button is hard to find",
         "summary": "The checkout button sits below the fold.", "affectedPersonaIds": ["p1", "p2"]},
        {"title": "Checkout button is hard to find",
         "summary": "The checkout button sits below the fold.", "personaId": "p1"},
        {"title": "Checkout button is hard to find", "summary": "The checkout button sits below the fold."},
    ]
    thoughts = {
        "p1": [{"kind": "action", "text": "Clicked"},
               {"kind": "reasoning", "text": "I scrolled twice before the checkout button appeared below the fold."}],
        "p2": [{"kind": "reasoning", "text": "I could not find the checkout button until I scrolled below the fold."}],
    }

    JobExecutor._attach_persona_evidence(findings, thoughts, {"p1": "Ada", "p2": "Lin"})

    assert [item["personaName"] for item in findings[0]["personaEvidence"]] == ["Ada", "Lin"]
    assert "checkout button" in findings[1]["personaEvidence"][0]["quote"]
    assert "personaEvidence" not in findings[2]


def test_a_persona_quote_about_something_else_is_not_published_as_evidence():
    """One sentence about tab navigation was attached to all five findings of a live
    run -- "Missing input labels" included -- because the persona's *last* piece of
    reasoning was taken regardless of what it was about. That reads as evidence and
    is not."""
    navigation = ("The main navigation uses buttons labeled with numbers and 'Previous view'/"
                  "'Next view' which may not be immediately obvious as tabs to all users.")
    findings = [
        {"title": "Unconventional tab navigation",
         "summary": "The main navigation uses numbered buttons that may not read as tabs.",
         "personaId": "p1"},
        {"title": "Missing input labels",
         "summary": "Several input fields rely on placeholder text rather than explicit label elements.",
         "personaId": "p1"},
    ]

    JobExecutor._attach_persona_evidence(
        findings, {"p1": [{"kind": "reasoning", "text": navigation}]}, {"p1": "Friedrich Wolf"})

    assert findings[0]["personaEvidence"][0]["quote"] == navigation
    assert "personaEvidence" not in findings[1]


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


def test_page_wide_finding_falls_back_to_the_full_screenshot():
    """A vision finding about the page as a whole has no element to crop, which
    left the deck's "Current design" panel empty on a real run where every
    finding was page-wide. Showing the page itself beats showing nothing."""
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1400, 400), color="white").save(buffer, format="PNG")

    uri = JobExecutor._screenshot_data_uri(buffer.getvalue(), max_width=700)

    # JPEG, not PNG: inlining page-wide captures as base64 PNG made a real
    # seven-finding deck 1.78 MB.
    assert uri.startswith("data:image/jpeg;base64,")
    import base64 as b64
    with Image.open(BytesIO(b64.b64decode(uri.split(",", 1)[1]))) as scaled:
        assert scaled.width == 700  # downscaled for a slide

    # A full-page capture of a long page is taller than any slide panel can render
    # legibly, so the visible top is kept rather than the whole page squashed.
    tall = BytesIO()
    Image.new("RGB", (1400, 12000), color="white").save(tall, format="PNG")
    capped = JobExecutor._screenshot_data_uri(tall.getvalue(), max_width=700, max_height=1500)
    with Image.open(BytesIO(b64.b64decode(capped.split(",", 1)[1]))) as scaled:
        assert (scaled.width, scaled.height) == (700, 1500)

    assert JobExecutor._screenshot_data_uri(b"not an image") is None


def test_finding_slide_labels_a_full_page_shot_distinctly_from_a_region_crop():
    region = JobExecutor._finding_slide(
        {"title": "Bad button", "summary": "s", "screenshotCrop": "data:image/png;base64,Zm9v",
         "screenshotIsRegion": True}, 1, "Observed user issue")
    full = JobExecutor._finding_slide(
        {"title": "Layout repeats", "summary": "s", "screenshotCrop": "data:image/png;base64,Zm9v",
         "screenshotIsRegion": False}, 1, "Observed user issue")

    assert ">Current design<" in region and "full page" not in region
    assert "Current design (page context)" in full


def test_redesign_is_rendered_as_live_html_beside_the_current_screenshot():
    """The reference deck pairs a photo of the current design with a mockup of the
    proposed one. The proposed half is real, inspectable HTML here -- rendered in a
    sandboxed iframe so its CSS cannot leak into the deck, with the markup shown
    underneath so it can be read and lifted."""
    html = JobExecutor._finding_slide({
        "title": "Generic link text", "summary": "The link says only 'Learn more'.",
        "screenshotCrop": "data:image/png;base64,Zm9v", "screenshotIsRegion": True,
        "redesignHtml": '<div class="fix"><style>.fix a{font-weight:600}</style>'
                        '<a href="#">Read the IANA domain policy</a></div>',
    }, 1, "Observed user issue")

    assert "Current design" in html
    assert "Re-design (live HTML)" in html
    assert "<iframe" in html and 'sandbox="allow-same-origin"' in html
    assert "srcdoc=" in html
    # The fragment is escaped into srcdoc, not injected raw into the deck.
    assert '<div class="fix">' not in html.split("<details")[0]
    assert "Re-design markup" in html
    assert "Read the IANA domain policy" in html  # readable in the code block


def test_redesign_generation_is_skipped_without_credentials(monkeypatch):
    """No model configured means no redesign -- never a canned template that
    ignores the finding."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BLABLADOR_API_KEY", raising=False)
    findings = [{"title": "Broken thing", "severity": "critical"}]

    JobExecutor._attach_redesigns(findings, "https://example.com")

    assert "redesignHtml" not in findings[0]


def test_redesign_generation_is_bounded_and_targets_the_worst_findings(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setenv("EYESON_REDESIGN_LIMIT", "2")  # opt back in (conftest disables it)
    asked = []

    def fake_fragment(finding, url):
        asked.append(finding["title"])
        return f'<div>fix for {finding["title"]}</div>'

    monkeypatch.setattr(JobExecutor, "_generate_redesign_fragment", staticmethod(fake_fragment))
    findings = [
        {"title": "low one", "severity": "low"},
        {"title": "critical one", "severity": "critical"},
        {"title": "high one", "severity": "high"},
        {"title": "No pain points detected", "severity": "low"},
    ]

    JobExecutor._attach_redesigns(findings, "https://example.com")

    assert asked == ["critical one", "high one"]  # bounded, worst first
    assert findings[1]["redesignHtml"] == "<div>fix for critical one</div>"
    assert "redesignHtml" not in findings[0]


def test_redesign_fragment_rejects_a_full_document_or_prose(monkeypatch):
    """A fragment is what the slide can embed; a whole page or a paragraph of
    explanation is not, and silently rendering either would be worse than none."""
    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    monkeypatch.setenv("EYESON_REDESIGN_LIMIT", "3")  # opt back in (conftest disables it)

    class Engine:
        def __init__(self, reply): self.reply = reply
        def complete_text(self, system, user): return self.reply

    import services.persona_service.semantic as semantic

    for reply, expected in [("<html><body>whole page</body></html>", None),
                            ("Sorry, I cannot do that.", None),
                            ("```html\n<div>ok</div>\n```", "<div>ok</div>")]:
        monkeypatch.setattr(semantic, "DirectLLMSemanticEngine", lambda r=reply: Engine(r))
        assert JobExecutor._generate_redesign_fragment({"title": "t"}, "https://example.com") == expected


def test_near_duplicate_findings_are_merged_into_one_issue():
    """aggregateCohort groups on an exact match of the vision model's free-form
    mechanism text, so one issue phrased three ways stayed three numbered issues.
    A real run produced exactly these three titles for one problem."""
    merged = JobExecutor._merge_similar_findings([
        {"title": "Visually styled link is not interactive", "severity": "medium",
         "affectedPersonaIds": ["p1"], "alternatives": [{"proposedChange": "Make it a real anchor."}]},
        {"title": "Visually apparent link is not interactive", "severity": "high",
         "affectedPersonaIds": ["p2"], "alternatives": [{"proposedChange": "Make it a real anchor."}],
         "screenshotCrop": "data:image/png;base64,Zm9v"},
        {"title": "Visually apparent link is not programmatically detected", "severity": "low",
         "affectedPersonaIds": ["p3"], "alternatives": [{"proposedChange": "Expose it to assistive tech."}]},
        {"title": "Low contrast footer text", "severity": "medium", "affectedPersonaIds": ["p1"]},
    ])

    assert len(merged) == 2
    link_issue = next(item for item in merged if "link" in item["title"])
    # Led by the most severe phrasing, carrying what every phrasing contributed.
    assert link_issue["title"] == "Visually apparent link is not interactive"
    assert link_issue["affectedPersonas"] == 3
    assert sorted(link_issue["affectedPersonaIds"]) == ["p1", "p2", "p3"]
    assert len(link_issue["alternatives"]) == 2  # deduplicated by proposedChange
    assert link_issue["screenshotCrop"] == "data:image/png;base64,Zm9v"
    assert len(link_issue["mergedFrom"]) == 2


def test_unrelated_findings_are_not_merged():
    merged = JobExecutor._merge_similar_findings([
        {"title": "Low contrast footer text", "severity": "medium"},
        {"title": "Primary navigation hidden in a dropdown", "severity": "high"},
    ])
    assert len(merged) == 2


def test_near_duplicate_strengths_are_merged():
    """A real run produced these three as separate "elements to preserve"."""
    merged = JobExecutor._merge_strengths([
        {"title": "Clear and concise page purpose", "description": "The heading states the purpose plainly.",
         "personaId": "p1", "route": "https://example.com", "screenshotRef": "/a.png"},
        {"title": "Clear purpose statement", "description": "Short.", "personaId": "p2",
         "route": "https://example.com", "screenshotRef": "/b.png"},
        {"title": "Clear and concise purpose statement", "description": "Also short.", "personaId": "p3",
         "route": "https://example.com", "screenshotRef": "/c.png"},
        {"title": "Restrained colour palette", "description": "Few colours.", "personaId": "p1",
         "route": "https://example.com", "screenshotRef": "/a.png"},
    ])

    assert len(merged) == 2
    purpose = merged[0]
    assert purpose["observedByPersonas"] == 3
    # Keeps the fullest description rather than the shortest phrasing.
    assert purpose["description"] == "The heading states the purpose plainly."
    assert len(purpose["alsoDescribedAs"]) == 2


def test_criterion_findings_read_as_sentences_about_the_user():
    """"Pass criterion not-met: tasks-completed" is a machine label, not a
    usability finding."""
    findings = JobExecutor._pain_points_from_journeys([{
        "runId": "run_1", "profileId": "p1",
        "verdict": {"criteria": [
            {"id": "tasks-completed", "result": "not-met", "explanation": "The checkout never appeared."},
            {"id": "tasks-blocked", "result": "met", "explanation": "Blocked by a spinner."},
        ]},
    }])

    titles = [item["title"] for item in findings]
    assert "Users could not finish the tasks they came to do" in titles
    assert "The journey was blocked before completion" in titles
    assert not any("criterion" in title.lower() for title in titles)
    # The machine label is still available for anyone who needs it.
    assert {item["criterionId"] for item in findings} == {"tasks-completed", "tasks-blocked"}


def test_harness_failures_are_not_numbered_among_the_usability_findings():
    from apps.api.executor import _is_run_diagnostic

    assert _is_run_diagnostic({"title": "Pi director did not finish the journey", "summary": ""})
    assert _is_run_diagnostic({"title": "Run failed", "summary": "provider timeout after 3 attempts"})
    assert not _is_run_diagnostic({"title": "Low contrast footer text", "summary": "Hard to read."})


def test_flow_label_names_the_product_area_not_the_taxonomy():
    assert JobExecutor._flow_label({"route": "https://example.com/"}) == "Landing page"
    assert JobExecutor._flow_label({"route": "https://example.com/sign-up"}) == "Sign Up"
    assert JobExecutor._flow_label({"route": "https://example.com/account/settings"}) == "Account · Settings"
    # Only when there is no route at all does the category stand in.
    assert JobExecutor._flow_label({"category": "accessibility"}) == "Accessibility"


def test_praise_phrasings_group_on_the_design_property_not_the_adjective():
    """A real run produced seven "elements to preserve" that were three
    observations: quality adjectives ("High", "Excellent", "Clean") carry no
    information about *which* decision is being praised."""
    merged = JobExecutor._merge_strengths([
        {"title": t, "description": t, "personaId": f"p{index}"} for index, t in enumerate([
            "High contrast and distraction-free design",
            "Excellent visual contrast and simplicity",
            "High visual contrast and readability",
            "Clean visual hierarchy and layout",
            "Minimalist and distraction-free layout",
            "Clear and concise technical copy",
            "Clear typographic hierarchy",
        ])])

    titles = [item["title"] for item in merged]
    assert len(merged) == 3
    contrast = next(item for item in merged if "contrast" in item["title"].lower())
    assert contrast["observedByPersonas"] == 3
    # Genuinely different observations stay apart.
    assert any("copy" in title.lower() for title in titles)
    assert any("layout" in title.lower() for title in titles)


def test_preserve_section_is_capped_and_says_how_many_were_found():
    report = {
        "url": "https://example.com", "evidence_language": "observed",
        "critical_pain_points": [],
        "elements_to_preserve": [{"title": f"Strength {index}", "description": "d",
                                  "observedByPersonas": 1} for index in range(9)],
    }

    html = JobExecutor._slide_deck(report)

    assert "9 design decisions were noted as working" in html
    assert "Strength 0" in html and "Strength 5" in html
    assert "Strength 6" not in html  # capped at six


def test_the_same_link_text_issue_phrased_three_ways_merges():
    """The exact three titles a live run against example.com produced for one
    problem."""
    merged = JobExecutor._merge_similar_findings([
        {"title": "Generic link text ('Learn more')", "severity": "medium", "affectedPersonaIds": ["p1"]},
        {"title": "Ambiguous link text", "severity": "low", "affectedPersonaIds": ["p2"]},
        {"title": "Non-descriptive link text", "severity": "medium", "affectedPersonaIds": ["p1", "p3"]},
        {"title": "Duplicated page layout and content", "severity": "high", "affectedPersonaIds": ["p1"]},
        {"title": "Outdated revision metadata", "severity": "low", "affectedPersonaIds": ["p2"]},
        {"title": "Low contrast footer text", "severity": "medium", "affectedPersonaIds": ["p1"]},
    ])

    titles = [item["title"] for item in merged]
    # The three link-text phrasings become one issue; everything else stays put.
    assert len(merged) == 4
    link = next(item for item in merged if "link text" in item["title"].lower())
    assert sorted(link["affectedPersonaIds"]) == ["p1", "p2", "p3"]
    assert "Duplicated page layout and content" in titles
    assert "Outdated revision metadata" in titles
    assert "Low contrast footer text" in titles  # not merged with the link-text issue


def test_journeytest_praise_becomes_an_element_to_preserve_not_a_usability_issue():
    """JourneyTest's `uxFindings` bucket is mixed: a live run against
    leon4gr45-nova-test filed "Clear value proposition" and "Prominent sign-up
    entry point" there, and both were published as usability issues."""
    journeys = [{"runId": "run_1", "profileId": "persona_ada", "verdict": {"uxFindings": [
        {"title": "Clear value proposition",
         "description": "The hero states what the product does in one sentence."},
        {"title": "Prominent sign-up entry point",
         "description": "The primary call to action sits above the fold and is visually distinct."},
        {"title": "Form fields have no visible labels",
         "description": "Placeholders disappear on focus, leaving the field unlabelled."},
        {"title": "Clear labelling, but the submit control is too small",
         "description": "Labels read well; the button is under the minimum touch target."},
    ]}}]

    issues = [item["title"] for item in JobExecutor._pain_points_from_journeys(journeys)]
    praise = [item["title"] for item in JobExecutor._praise_from_verdicts(journeys)]

    assert issues == ["Form fields have no visible labels",
                      "Clear labelling, but the submit control is too small"]
    assert praise == ["Clear value proposition", "Prominent sign-up entry point"]


def test_a_finding_quoting_text_that_is_not_on_the_page_is_dropped():
    """The live nova-test run reported "Leftover debug text 'navbar.' visible on
    page"; the string only ever occurs mid-sentence inside real copy."""
    corpus = ["Sign up free", "Get started",
              "You will find it in the sidebar or navbar. You will be redirected shortly."]

    kept, rejected = JobExecutor._drop_unverifiable_quotes([
        {"title": "Leftover debug text 'navbar.' visible on page", "summary": "A stray token is rendered."},
        {"title": "Generic link text ('Sign up')", "summary": "The link names no destination."},
        {"title": "Low contrast body text", "summary": "Body copy sits near 3:1."},
    ], corpus)

    assert [item["title"] for item in kept] == ["Generic link text ('Sign up')", "Low contrast body text"]
    assert rejected[0]["quotes"] == ["navbar."]
    # With no snapshots captured there is nothing to check against, so nothing is dropped.
    assert len(JobExecutor._drop_unverifiable_quotes([{"title": "Quotes 'anything'", "summary": ""}], [])[0]) == 1


def test_screenshots_pair_with_the_dom_snapshot_journeytest_actually_writes(tmp_path):
    """journeytest-core names the semantic capture `<stem>-dom.json` beside
    `<stem>.png`. The previous stem rule stripped "-before"/"-after" from the
    screenshot but left "-dom" on the snapshot, so nothing ever matched and every
    vision finding was produced with an empty element list -- which is why every
    crop in a live run came back as a whole page."""
    import json as json_module

    def snapshot(name, label):
        path = tmp_path / name
        path.write_text(json_module.dumps({"elements": [
            {"selector": f"#{label}", "role": "button", "text": label,
             "boundingBox": {"x": 1, "y": 2, "width": 3, "height": 4}}]}))
        return str(path)

    snapshots = [snapshot("001-click-e21-before-dom.json", "first-before"),
                 snapshot("001-click-e21-after-dom.json", "first-after"),
                 snapshot("002-click-e4-before-dom.json", "second-before"),
                 snapshot("002-click-e4-after-dom.json", "second-after"),
                 str(tmp_path / "001-snapshot.txt")]

    def label_for(screenshot_name):
        elements = JobExecutor._elements_for_screenshot(str(tmp_path / screenshot_name), snapshots)
        return elements[0]["text"] if elements else None

    assert label_for("001-click-e21-after.png") == "first-after"
    assert label_for("001-click-e21-before.png") == "first-before"
    # A "change" frame has no DOM capture of its own; the action's post-action DOM
    # describes the same page state.
    assert label_for("001-click-e21-change-001.png") == "first-after"
    # The un-numbered framing shots are literally the page before the first action
    # and after the last one -- in capture order, not alphabetical order.
    assert label_for("initial-view.png") == "first-before"
    assert label_for("final-view.png") == "second-after"
    # Nothing to pair it with, and no guessing.
    assert label_for("after-nova-act-click.png") is None


def test_a_verdict_finding_shows_the_screenshot_journeytest_cited(tmp_path):
    """Only vision-synthesis findings carried an image before, so every slide built
    from JourneyTest's own verdict rendered with an empty "Current design" panel."""
    from PIL import Image

    cited = tmp_path / "after-nova-act-click.png"
    Image.new("RGB", (400, 300), color="white").save(cited)
    final_view = tmp_path / "final-view.png"
    Image.new("RGB", (400, 300), color="white").save(final_view)

    findings = [
        {"title": "Overwhelming number of buttons", "source": "uxFindings", "runId": "run_1",
         "evidenceScreenshot": str(cited)},
        {"title": "The journey was blocked before completion", "source": "criteria", "runId": "run_1",
         "evidenceScreenshot": None},
        {"title": "Already has its own region crop", "source": "eyeson-vision-synthesis", "runId": "run_1",
         "screenshotCrop": "data:image/png;base64,Zm9v", "screenshotIsRegion": True},
    ]
    JobExecutor._attach_verdict_screenshots(findings, [{"runId": "run_1", "artifacts": {
        "screenshots": [str(cited), str(final_view)]}}])

    assert findings[0]["screenshotRef"] == str(cited)
    assert findings[0]["screenshotCrop"].startswith("data:image/jpeg;base64,")
    assert findings[0]["screenshotIsRegion"] is False
    # No cited screenshot: a failed criterion is shown as the state the run ended in.
    assert findings[1]["screenshotRef"] == str(final_view)
    # An existing region crop is never overwritten with a whole page.
    assert findings[2]["screenshotCrop"] == "data:image/png;base64,Zm9v"


def test_one_issue_described_two_ways_merges_on_its_description():
    """A live run against leon4gr45-nova-test published "Ambiguous navigation
    hierarchy" and "Redundant and confusing navigation layers" as two findings.
    Both say the page offers several overlapping ways to navigate, but they share
    one content token in six -- far under the title threshold."""
    merged = JobExecutor._merge_similar_findings([
        {"title": "Ambiguous navigation hierarchy", "severity": "medium",
         "summary": "The page uses two different sets of navigation controls (the top header buttons and "
                    "the horizontal card carousel) that seem to represent similar or overlapping product "
                    "areas. This creates confusion about which control dictates the current view."},
        {"title": "Redundant and confusing navigation layers", "severity": "medium",
         "summary": "The page features three different ways to navigate between product sections: a top "
                    "header nav, a horizontal tab bar with arrows, and a grid of cards. This creates "
                    "cognitive load as the user isn't sure which control is the primary way to switch "
                    "contexts."},
        {"title": "Missing input labels", "severity": "medium",
         "summary": "Several input fields (Company, Product, Seed, Group Name) rely on placeholder text "
                    "or proximity rather than explicit label elements, which is poor for accessibility."},
        {"title": "Guided tour for new users", "severity": "low",
         "summary": "The product offers many features which could overwhelm new users."},
    ])

    titles = [item["title"] for item in merged]
    assert len(merged) == 3
    assert "Missing input labels" in titles
    assert "Guided tour for new users" in titles
    assert sum("navigation" in title.lower() for title in titles) == 1


def test_capture_references_read_as_names_not_container_paths():
    """A live deck rendered "snapshot: /home/user/artifacts/journeys/2026-08-30T10-57-
    43-548Z-job_08147074e9f648a58d3c/snapshots/005-snapshot.txt" as its root-cause
    analysis. The path says nothing to a reader and is gone with the container."""
    from apps.api.executor import _evidence_reference_summary

    summary = _evidence_reference_summary({
        "observation": "Initial snapshot shows more than 15 buttons without scrolling.",
        "screenshot": "/home/user/artifacts/journeys/2026-08-30T10-57-43-548Z-job_a/screenshots/initial-view.png",
        "snapshot": "/home/user/artifacts/journeys/2026-08-30T10-57-43-548Z-job_a/snapshots/005-snapshot.txt",
    })

    assert "/home/user/artifacts" not in summary
    assert "screenshot: initial-view.png" in summary
    assert "snapshot: 005-snapshot.txt" in summary
    assert summary.startswith("Initial snapshot shows more than 15 buttons")


def test_a_slide_never_heads_a_capture_reference_as_root_cause_analysis():
    with_observation = JobExecutor._finding_slide(
        {"title": "Overwhelming number of buttons", "summary": "Many controls compete for attention.",
         "observation": "Initial snapshot shows more than 15 buttons without scrolling.",
         "evidence": "snapshot: 001-snapshot.txt"}, 1, "Observed user issue")
    without = JobExecutor._finding_slide(
        {"title": "Guided tour for new users", "summary": "The product offers many features.",
         "evidence": "snapshot: 001-snapshot.txt"}, 1, "Observed user issue")

    assert "Initial snapshot shows more than 15 buttons" in with_observation
    assert "001-snapshot.txt" not in without


def test_one_design_decision_praised_two_ways_becomes_one_preserved_element():
    """A live run listed "Clear visual status indicators" and "Effective use of state
    indicators" separately; both describe the same ACTIVE badge."""
    merged = JobExecutor._merge_strengths([
        {"title": "Clear visual status indicators", "personaId": "p1",
         "description": "The 'ACTIVE' and 'READY' badges provide immediate feedback on module state."},
        {"title": "Effective use of state indicators", "personaId": "p2",
         "description": "The 'ACTIVE' badge and the green border communicate the user's current location."},
        {"title": "Effective progress indicator", "personaId": "p1",
         "description": "The top stepper shows the user's current location in the workflow."},
        {"title": "Consistent color palette", "personaId": "p1",
         "description": "A single accent colour for primary actions creates a cohesive feel."},
    ])

    titles = [item["title"] for item in merged]
    assert len(merged) == 3
    indicators = next(item for item in merged if "indicators" in item["title"])
    assert sorted(indicators["personaIds"]) == ["p1", "p2"]
    assert indicators["observedByPersonas"] == 2
    # The progress stepper is a different design decision, however similarly worded.
    assert "Effective progress indicator" in titles
    assert "Consistent color palette" in titles
