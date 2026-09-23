import base64
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from fastapi.testclient import TestClient

from apps.api.main import create_app
from apps.api.executor import JobExecutor, _reads_as_praise
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
    # Cited by the name the session lists the capture under, so the reader can
    # find it -- not by the file name the run happened to write ("003.png"),
    # which no artifact in the session is called.
    assert JobExecutor._download_name("browser.screenshot", job["job_id"], "003") in blocker["evidence"]
    assert "screenshot: 003.png" not in blocker["evidence"]
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


def test_vision_image_payload_fits_a_proxy_body_limit():
    """A full-page capture must not be sent at its original size.

    A live run failed with HTTP 413 "request entity too large" because the
    screenshot went to the model router as raw base64 PNG. JourneyTest writes
    full-page captures (one was 2.4 MB / 12000px), and base64 adds a third on
    top, so the body passed the proxy's cap before the model ever saw it.
    """
    pytest.importorskip("PIL")
    from io import BytesIO
    from PIL import Image

    # Photographic density: the case PNG cannot squeeze, which is how a real
    # capture reaches megabytes. A flat synthetic page would not reproduce it.
    import random
    random.seed(11)
    tall = Image.new("RGB", (1440, 6000))
    tall.putdata([(random.randrange(256), random.randrange(256), random.randrange(256))
                  for _ in range(1440 * 6000)])
    buffer = BytesIO()
    tall.save(buffer, format="PNG")
    raw = buffer.getvalue()

    budget = JobExecutor._vision_image_budget()
    assert len(raw) > budget, "fixture must be large enough to exercise the shrink path"

    encoded, mime = JobExecutor._vision_image_payload(raw)

    assert mime == "image/jpeg"
    assert len(encoded) * 3 // 4 <= budget
    # base64 of the original would have been several MB; the sent body is the
    # thing the proxy measures.
    assert len(encoded) < len(base64.b64encode(raw))


def test_vision_image_payload_leaves_a_small_capture_alone():
    """Nothing to gain from re-encoding a screenshot already under budget."""
    pytest.importorskip("PIL")
    small = b"x" * 128
    encoded, mime = JobExecutor._vision_image_payload(small)
    assert mime == "image/png"
    assert encoded == base64.b64encode(small).decode("ascii")


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
    assert "2 observations across 2 people" in finding["evidence"]
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


def test_vision_critique_is_given_what_the_persona_was_experiencing_at_that_screenshot(tmp_path, monkeypatch):
    """The vision critique used to judge every screenshot cold, with no idea
    what the persona actually expected or felt at that moment -- two
    independent pipelines merged only by severity-capping after the fact. It
    is now given the nearest persona.expectation/reflection/affect moment on
    the run's own elapsedMs clock (personaContext, in the request sent to the
    vision model) and the resulting finding carries that same moment's quote
    as personaEvidence, the same {quote, personaId, personaName} shape every
    other source in this report uses."""
    import json as json_module
    from PIL import Image

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "minibio": "An impatient persona",
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
    timeline = [
        {"type": "persona.expectation", "elapsedMs": 900,
         "data": {"expectation": "I expect the price to appear when I click this."}},
        {"type": "persona.reflection", "elapsedMs": 950,
         "data": {"matched": "no", "gap": "Clicking it did not reveal any price."}},
        {"type": "persona.affect", "elapsedMs": 990, "data": {"feeling": "That is annoying."}},
        # Taken after the moment above, so it resolves as the nearest -- proving
        # the match is by elapsedMs, not "the first/last moment in the run".
        {"type": "browser.screenshot", "elapsedMs": 1000, "data": {"path": str(screenshot_path)}},
    ]

    captured_payload = {}

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
                "timeline": timeline,
                "artifacts": {"screenshots": [str(screenshot_path)], "snapshots": [str(snapshot_path)]}}).encode())
        if req.full_url.endswith("/v1/journey-evidence-analyses"):
            captured_payload.update(payload)
            return Response(json_module.dumps({"schemaVersion": "1.0", "painPoints": [{
                "id": "pain_1", "runId": payload["runId"], "userId": payload["userId"], "route": "https://example.com",
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
                "grounding": {"status": "completed", "references": []},
                "alternatives": [], "overlays": [],
            }]}).encode())
        assert req.full_url.endswith("/v1/cohort-aggregation")
        runs = payload["runs"]
        all_points = [point for run in runs for point in run["painPoints"]]
        # The personaEvidence attached in Python before this call must survive
        # being sent through cohort-aggregation and read back by artifact_id.
        assert all_points[0]["personaEvidence"] == [
            {"quote": "That is annoying.", "personaId": "persona_ada", "personaName": "Ada"}]
        return Response(json_module.dumps({"schemaVersion": "1.0", "rootCauses": [{
            "id": "root_1", "signature": "sig", "category": "accessibility",
            "mechanism": "The label does not describe the action.", "elementIds": ["#buy-button"],
            "painPointIds": [point["id"] for point in all_points],
            "affectedUsers": ["persona_ada"], "affectedIterations": [run["runId"] for run in runs],
            "averageStateImpact": {"frustration": 0.4, "confusion": 0.3, "trust": -0.1}, "abandonmentCount": 0,
            "personaSusceptibility": {}, "alternatives": [],
        }]}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setenv("EYESON_WORKER_URL", "http://eyeson.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": [persona["artifact_id"]], "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": [persona["artifact_id"]],
                    "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"

    # The vision model was told what this persona was experiencing at this
    # exact moment -- not just the screenshot and a generic bio.
    assert captured_payload["personaContext"] == (
        'they expected: "I expect the price to appear when I click this."; '
        'what arrived instead: "Clicking it did not reveal any price."; '
        'how it left them: "That is annoying."')

    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))
    finding = next(item for item in report["critical_pain_points"] if item["source"] == "eyeson-vision-synthesis")
    assert finding["personaEvidence"] == [
        {"quote": "That is annoying.", "personaId": "persona_ada", "personaName": "Ada"}]


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


# --- RPT-6: the reader-facing lines --------------------------------------------

def test_the_intro_slide_states_scope_and_the_evidence_language_stamp():
    """F2: scope stated as intent up front, including what was not reviewed.
    G4: evidence_language printed verbatim, not only as "Observed"/"Inferred"
    prose -- the strongest sentence the report can write about itself."""
    report = {"url": "https://example.test/", "executive_summary": "s", "evidence_language": "observed",
             "journey_outcome": {"tasks": ["Buy an item"]}, "impact_analysis": {},
             "elements_to_preserve": [], "critical_pain_points": []}
    html = JobExecutor._slide_deck(report)

    assert "Scope: only the tasks below, against https://example.test/" in html
    assert "were not exercised and are not" in html
    assert "evidence_language: observed" in html


def test_the_intro_slide_prints_the_model_usage_summary():
    """BE-3: the economic case, on the one slide a reader would look for it."""
    report = {"url": "https://example.test/", "executive_summary": "s", "evidence_language": "observed",
             "journey_outcome": {"tasks": ["Buy an item"]}, "impact_analysis": {},
             "elements_to_preserve": [], "critical_pain_points": [],
             "model_usage": {"totalCalls": 2, "totalWallMs": 1500, "totalPromptTokens": 900,
                             "totalCompletionTokens": 150, "byRole": {}, "providers": [
                                 {"endpoint": "https://router.example", "model": "auto"}]}}
    html = JobExecutor._slide_deck(report)

    assert "2 model calls" in html and "1.5s wall time" in html and "1050 tokens" in html
    assert "auto (https://router.example)" in html


def test_severity_derivation_is_printed_beside_the_chip_and_degrades_honestly():
    """B7: why this severity, not just what it is -- built only from numbers a
    finding actually carries, never invented for a source that has none."""
    html = JobExecutor._finding_slide({
        "title": "Confusing checkout", "severity": "medium", "summary": "s",
        "affectedPersonas": 1, "claimedImpact": {"frustration": 0.2, "confusion": 0.1, "trust": 0.0},
    }, 1, "Observed user issue")

    assert "sev-why" in html
    assert "1 person" in html and "raised frustration 0.20" in html and "not blocking" in html

    # A verdict-level blocker carries none of that -- degrades to what it has.
    bare = JobExecutor._finding_slide({"title": "Blocked", "severity": "critical", "summary": "s",
                                       "category": "blocker"}, 1, "Observed user issue")
    assert "blocking" in bare and "1 person" not in bare


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) == 3:
        hex_color = "".join(ch * 2 for ch in hex_color)
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def channel(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = channel(r), channel(g), channel(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_ratio(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x's own formula (SC 1.4.3), not an approximation of it."""
    lum_a, lum_b = _relative_luminance(hex_a) + 0.05, _relative_luminance(hex_b) + 0.05
    return max(lum_a, lum_b) / min(lum_a, lum_b)


def test_e11_the_decks_own_palette_passes_wcag_aa_contrast():
    """E11: a contrast review that fails contrast would be embarrassing, and
    nothing checked it before this. Reads the pairs out of the deck's actual
    generated CSS -- not a hand-copied snapshot of it -- so a future palette
    edit is what this test checks, not what it was written against."""
    import re

    css = JobExecutor._slide_deck({"url": "https://example.com", "critical_pain_points": []})

    def rule(selector: str) -> str:
        match = re.search(re.escape(selector) + r"\{([^}]*)\}", css)
        assert match, f"selector {selector!r} not found in the deck's stylesheet"
        return match.group(1)

    def color_prop(block: str, prop: str) -> str:
        match = re.search(prop + r":\s*(#(?:[0-9a-fA-F]{3}){1,2})\b", block)
        assert match, f"no {prop!r} declared in {block!r}"
        return match.group(1)

    # Every severity chip: its own background against its own text colour.
    for selector in (".sev-critical", ".sev-high", ".sev-medium", ".sev-low"):
        block = rule(selector)
        background, color = color_prop(block, "background"), color_prop(block, "color")
        ratio = _contrast_ratio(background, color)
        assert ratio >= 4.5, f"{selector} contrast is {ratio:.2f}:1, below WCAG AA's 4.5:1 ({background} on {color})"

    # Body text against the deck's own default slide background (white), and
    # the dark title slide against its own declared background and colour.
    body_color = color_prop(rule("body"), "color")
    assert _contrast_ratio("#ffffff", body_color) >= 4.5, "default body text on a white slide"
    title_block = rule(".slide.title")
    title_background, title_color = color_prop(title_block, "background"), color_prop(title_block, "color")
    assert _contrast_ratio(title_background, title_color) >= 4.5, "title slide's own background and text colour"


def test_findings_are_ordered_by_the_step_they_occurred_at_not_by_severity():
    """F8: findings accumulate into the story of the run. Severity governs only
    impact_analysis's own "what to fix first" ordering, a separate list."""
    findings = [
        {"title": "Late issue", "severity": "critical", "screenshotRef": "/tmp/x/010-click-after.png"},
        {"title": "Early issue", "severity": "low", "screenshotRef": "/tmp/x/002-click-after.png"},
        {"title": "No derivable step", "severity": "high"},
        {"title": "Mid issue", "severity": "medium", "evidenceScreenshot": "/tmp/x/005-read.png"},
    ]

    ordered = JobExecutor._order_by_step(findings)

    assert [item["title"] for item in ordered] == ["Early issue", "Mid issue", "Late issue", "No derivable step"]


# --- BE-3/A9: cost, time, and reproducibility -----------------------------------

def test_model_usage_rolls_up_both_funnels_by_role():
    """BE-3: the two places a model call can originate -- a journey's own
    modelUsage (personaActor.js's completion()) and this report's own redesign
    calls (DirectLLMSemanticEngine) -- roll up into one summary, by role."""
    journeys = [
        {"runId": "run_1", "modelUsage": [
            {"role": "acting", "endpoint": "https://router.example", "model": "auto",
             "wallMs": 1200, "promptTokens": 800, "completionTokens": 120},
            {"role": "reflection", "endpoint": "https://router.example", "model": "alias-fast",
             "wallMs": 300, "promptTokens": 200, "completionTokens": 30},
        ]},
    ]
    redesign_usage = [{"role": "report.redesign", "endpoint": "https://router.example", "model": "auto",
                       "wallMs": 900, "promptTokens": 500, "completionTokens": 250}]

    summary = JobExecutor._model_usage_summary(journeys, redesign_usage)

    assert summary["totalCalls"] == 3
    assert summary["totalWallMs"] == 2400
    assert summary["totalPromptTokens"] == 1500 and summary["totalCompletionTokens"] == 400
    assert summary["byRole"]["acting"]["calls"] == 1
    assert summary["byRole"]["report.redesign"]["promptTokens"] == 500
    assert {"endpoint": "https://router.example", "model": "auto"} in summary["providers"]

    # Nothing measured: None, not a fabricated zero.
    assert JobExecutor._model_usage_summary([{"runId": "run_1"}], None) is None


def test_a_run_with_model_traffic_states_reproducibility_honestly(tmp_path, monkeypatch):
    """A9: the report says plainly that a persona's exact wording will not
    reproduce on a re-run -- only its disposition (the compiled profile) does."""
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed",
        "verdict": {"status": "passed", "criteria": [{"id": "tasks-completed", "result": "met"}],
                   "blockers": [], "uxFindings": [], "suggestedImprovements": []},
        "modelUsage": [{"role": "acting", "endpoint": "https://router.example", "model": "auto",
                        "wallMs": 500, "promptTokens": 100, "completionTokens": 20}],
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    assert report["model_usage"]["totalCalls"] == 1
    reproducibility = [line for line in report["limitations"] if "not reproduce" in line]
    assert reproducibility and "disposition" in reproducibility[0]


def test_persona_narration_carries_the_mental_model_end_to_end(tmp_path, monkeypatch):
    """RPT-2/B3, wired: a real combined_test run's timeline reaches
    persona_narration as a stated model, not just the isolated method."""
    timeline = []
    for expectation, matched in [("show the price", "yes"), ("show the total", "yes"),
                                 ("take me to checkout", "no")]:
        timeline.append({"type": "persona.expectation", "data": {"expectation": expectation}})
        timeline.append({"type": "persona.reflection", "data": {"matched": matched}})

    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed",
        "verdict": {"status": "passed", "criteria": [{"id": "tasks-completed", "result": "met"}],
                   "blockers": [], "uxFindings": [], "suggestedImprovements": []},
        "timeline": timeline,
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    narration = report["persona_narration"][0]
    assert "told something" in narration["mentalModel"]
    assert "held for 2 of 3" in narration["mentalModel"]


# --- RPT-3: how you would know it worked ----------------------------------------

def test_rpt3_a_finding_states_a_falsifiable_retest_prediction():
    """Every finding is a falsifiable prediction: fix this, and an identifiable
    persona's expectation should hold on the next run. No human review closes
    that loop -- a stated, checkable prediction is what does."""
    finding = {"title": "Promised more than it did: Start 3-day free trial",
              "affectedPersonaIds": ["p1"]}
    retest = JobExecutor._retest_prediction(finding, {"p1": "Friedrich Wolf"}, ["Buy an item"])

    assert "Friedrich Wolf" in retest
    assert "Buy an item" in retest
    assert "Promised more than it did: Start 3-day free trial" in retest
    assert "Falsifiable" in retest

    # Several affected personas: named as a group, not just the first one silently.
    several = JobExecutor._retest_prediction(
        {"title": "x", "affectedPersonaIds": ["p1", "p2"]}, {"p1": "Ada", "p2": "Lin"}, ["Buy an item"])
    assert "each of the 2 affected personas" in several

    # Nobody to re-run it against: no prediction rather than a fabricated one.
    assert JobExecutor._retest_prediction({"title": "No pain points detected"}, {}, ["Buy an item"]) == ""


def test_rpt3_the_retest_prediction_is_wired_into_the_report_end_to_end(tmp_path, monkeypatch):
    verdict = {"status": "failed", "confidence": "high", "summary": "Blocked.",
              "criteria": [{"id": "tasks-completed", "result": "not-met"}],
              "blockers": [{"id": "b1", "severity": "major", "category": "blocker",
                            "title": "Checkout never confirmed", "description": "The confirm button did nothing."}],
              "uxFindings": [], "suggestedImprovements": []}
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed", "verdict": verdict,
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    }, tasks=("Buy an item",))

    assert completed["status"] == "succeeded"
    blocker = next(item for item in report["critical_pain_points"] if item["title"] == "Checkout never confirmed")
    assert "Falsifiable" in blocker["retest"]
    assert "Buy an item" in blocker["retest"]
    assert "Checkout never confirmed" in blocker["retest"]


def test_rpt3_the_retest_line_is_printed_on_the_slide_and_in_the_presentation():
    slide = JobExecutor._finding_slide({"title": "Generic link text", "summary": "s",
                                        "retest": "Falsifiable: on a re-run, Ada should see this hold."},
                                       1, "Observed user issue")
    assert "How you would know it worked" in slide
    assert "Ada should see this hold" in slide

    presentation = JobExecutor._presentation({
        "critical_pain_points": [{"title": "Generic link text", "severity": "medium", "category": "ux",
                                  "summary": "s", "retest": "Falsifiable: on a re-run, Ada should see this hold."}],
        "elements_to_preserve": [], "impact_analysis": {}, "url": "https://example.com",
        "executive_summary": "", "evidence_language": "observed", "limitations": []})
    assert "Ada should see this hold" in presentation


# --- RPT-4/A2: the scorecard -----------------------------------------------------

def test_a2_the_scorecard_states_task_success_and_the_expectation_hit_rate():
    """A report that only shows misses hides its own hit rate. The scorecard
    draws misses from the same `matched` field the broken-promise findings do,
    so the two can never disagree about what a "miss" is."""
    def pair(matched):
        return [{"type": "persona.expectation", "data": {}}, {"type": "persona.reflection", "data": {"matched": matched}}]

    journeys = [
        {"runId": "run_1", "verdict": {"status": "passed", "summary": "Completed."},
         "timeline": pair("yes") + pair("yes") + pair("no")},
        {"runId": "run_2", "verdict": {"status": "failed", "summary": "Gave up at checkout."},
         "timeline": pair("no")},
    ]
    personas = [{"id": "p1"}, {"id": "p2"}]

    scorecard = JobExecutor._run_scorecard(journeys, personas, {"p1": "Ada", "p2": "Lin"})

    assert scorecard["tasksSucceeded"] == 1 and scorecard["tasksAttempted"] == 2
    assert scorecard["expectationsMet"] == 2 and scorecard["expectationsMissed"] == 2
    assert scorecard["expectationsMetRate"] == 0.5
    assert scorecard["runs"][0]["personaName"] == "Ada"
    assert scorecard["runs"][0]["actionsTaken"] == 3
    assert scorecard["runs"][1]["stoppedBecause"] == "Gave up at checkout."

    # No expectations recorded at all: None, not a fabricated 0%.
    empty = JobExecutor._run_scorecard([{"runId": "r", "verdict": {}, "timeline": []}], [{"id": "p1"}], {})
    assert empty["expectationsMetRate"] is None


def test_a2_the_scorecard_hit_rate_is_printed_on_the_intro_slide():
    html = JobExecutor._slide_deck({
        "url": "https://example.test/", "executive_summary": "s", "evidence_language": "observed",
        "journey_outcome": {"tasks": ["Buy an item"]}, "impact_analysis": {},
        "elements_to_preserve": [], "critical_pain_points": [],
        "scorecard": {"tasksSucceeded": 2, "tasksAttempted": 3, "expectationsMet": 6,
                     "expectationsMissed": 2, "expectationsMetRate": 0.75}})

    assert "2 of 3 tasks completed" in html
    assert "75% of expectations held" in html


# --- RPT-4/D9: say what worked, grounded in a met expectation -------------------

def test_d9_a_met_expectation_becomes_a_preserved_element_not_generic_praise():
    """A control that did exactly what a visitor expected, first try, is a
    design decision worth preserving -- grounded in the same `matched` field
    the misses use, not in generic praise."""
    journeys = [{"runId": "run_1", "profileId": "p1", "timeline": [
        {"type": "persona.expectation", "data": {"expectation": "clicking will show the price",
                                                  "action": {"type": "CLICK", "target": "e1"},
                                                  "targetName": "See pricing"}},
        {"type": "persona.reflection", "data": {"matched": "yes"}},
    ]}]

    preserved = JobExecutor._preserved_from_met_expectations(journeys)

    assert len(preserved) == 1
    assert preserved[0]["title"] == "“See pricing” does what it says"
    assert "clicking will show the price" in preserved[0]["description"]
    assert "delivered, first try" in preserved[0]["description"]
    assert preserved[0]["observedByPersonas"] == 1

    # Not a promising action (a READ changes nothing): not counted as a promise
    # kept, the same rule the misses use for what counts as a promise at all.
    not_a_promise = [{"runId": "run_1", "profileId": "p1", "timeline": [
        {"type": "persona.expectation", "data": {"expectation": "scrolling will reveal more",
                                                  "action": {"type": "SCROLL"}}},
        {"type": "persona.reflection", "data": {"matched": "yes"}},
    ]}]
    assert JobExecutor._preserved_from_met_expectations(not_a_promise) == []


def test_d9_a_control_kept_and_broken_elsewhere_groups_under_the_same_label():
    """The met and unmet cases share _promise_label, so a control preserved in
    one run and broken in another can never silently become two entries with
    different names for the same control."""
    action = {"type": "CLICK"}
    kept = JobExecutor._preserved_from_met_expectations([{"runId": "run_1", "profileId": "p1", "timeline": [
        {"type": "persona.expectation", "data": {"expectation": "will start the trial",
                                                  "action": action, "targetName": "Start free trial"}},
        {"type": "persona.reflection", "data": {"matched": "yes"}},
    ]}])
    broken_label = JobExecutor._promise_label("will start the trial", action, "Start free trial")
    assert kept[0]["title"] == f"“{broken_label}” does what it says"


# --- RPT-4/D7: grouped controls whose actions differ in kind --------------------

def test_d7_two_adjacent_controls_of_different_kinds_are_flagged(tmp_path):
    import json as json_module

    snapshot = tmp_path / "001-view-dom.json"
    snapshot.write_text(json_module.dumps({"elements": [
        {"selector": "#next", "role": "link", "name": "Continue",
         "box": {"x": 100, "y": 40, "width": 80, "height": 30}},
        {"selector": "#delete", "role": "button", "name": "Delete account",
         "box": {"x": 184, "y": 40, "width": 80, "height": 30}},
        {"selector": "#far", "role": "button", "name": "Far away button",
         "box": {"x": 900, "y": 900, "width": 80, "height": 30}},
    ]}))
    journeys = [{"runId": "run_1", "profileId": "p1", "artifacts": {"snapshots": [str(snapshot)]}}]

    findings = JobExecutor._grouped_controls_with_differing_actions(journeys)

    assert len(findings) == 1
    assert "Continue" in findings[0]["title"] and "Delete account" in findings[0]["title"]
    assert "navigates" in findings[0]["summary"] and "acts" in findings[0]["summary"]
    assert findings[0]["source"] == "layout.grouped"
    # The far-away button is its own cluster of one -- never flagged, and never
    # pulled into the same finding as the adjacent pair.
    assert "Far away" not in findings[0]["title"]


def test_d7_controls_of_the_same_kind_grouped_together_are_not_flagged(tmp_path):
    """Proximity alone is not the defect -- a row of same-kind buttons (three
    links, say) is an ordinary menu, not an inconsistency."""
    import json as json_module

    snapshot = tmp_path / "001-view-dom.json"
    snapshot.write_text(json_module.dumps({"elements": [
        {"selector": "#a", "role": "link", "name": "Home", "box": {"x": 0, "y": 0, "width": 40, "height": 20}},
        {"selector": "#b", "role": "link", "name": "About", "box": {"x": 44, "y": 0, "width": 40, "height": 20}},
    ]}))
    journeys = [{"runId": "run_1", "profileId": "p1", "artifacts": {"snapshots": [str(snapshot)]}}]

    assert JobExecutor._grouped_controls_with_differing_actions(journeys) == []


def test_d7_cluster_by_proximity_flood_fills_a_chain_of_adjacent_boxes():
    elements = [
        {"selector": "a", "box": {"x": 0, "y": 0, "width": 20, "height": 20}},
        {"selector": "b", "box": {"x": 25, "y": 0, "width": 20, "height": 20}},   # touches a
        {"selector": "c", "box": {"x": 50, "y": 0, "width": 20, "height": 20}},   # touches b, not a directly
        {"selector": "d", "box": {"x": 500, "y": 500, "width": 20, "height": 20}},  # isolated
    ]
    clusters = JobExecutor._cluster_by_proximity(elements)
    sizes = sorted(len(cluster) for cluster in clusters)
    assert sizes == [1, 3]


# --- RPT-4/D4: a deterministic sweep for target size -----------------------------

def test_d4_a_target_below_the_wcag_minimum_is_flagged(tmp_path):
    import json as json_module

    snapshot = tmp_path / "001-view-dom.json"
    snapshot.write_text(json_module.dumps({"elements": [
        {"selector": "#tiny", "role": "button", "name": "X",
         "box": {"x": 10, "y": 10, "width": 16, "height": 16}},
        {"selector": "#fine", "role": "button", "name": "Submit",
         "box": {"x": 100, "y": 10, "width": 48, "height": 32}},
        {"selector": "#text", "role": "text", "name": "Some paragraph",
         "box": {"x": 10, "y": 100, "width": 10, "height": 10}},
    ]}))
    journeys = [{"runId": "run_1", "profileId": "p1", "artifacts": {"snapshots": [str(snapshot)]}}]

    findings = JobExecutor._small_touch_targets(journeys)

    assert len(findings) == 1
    assert findings[0]["title"] == 'Target below the WCAG minimum: "X"'
    assert "16x16px" in findings[0]["summary"] and "24x24px" in findings[0]["summary"]
    assert findings[0]["source"] == "layout.targetSize"
    # Not flagged: comfortably above the minimum, and non-interactive text
    # (never a "target" to begin with, whatever size it measures).
    assert "Submit" not in str(findings)
    assert "Some paragraph" not in str(findings)


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

    assert "2 usability issues were identified" in summary
    assert "1 of them high-severity or blocking" in summary
    assert "1 design decision is working" in summary

    empty = JobExecutor._executive_summary("https://example.com", ["Buy"], [{"id": "p1"}],
                                           [{"title": "No pain points detected", "severity": "low"}], [])
    assert "0 usability issues were identified" in empty


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


def test_deck_bounds_evidence_images_to_the_slide():
    """An evidence image must not be taller than the slide showing it.

    .slide is exactly 100vh with overflow-y:auto, so an image with only a width
    rule renders at its natural height and scrolls off a landscape screen -- a
    600x3000 crop measured 3020px tall inside a 900px slide. The sibling
    iframe.redesign was already capped; the img was not.
    """
    deck = JobExecutor._slide_deck({
        "url": "https://example.com", "executive_summary": "s",
        "critical_pain_points": [{
            "title": "Nav is unclear", "summary": "s", "severity": "high",
            "screenshotCrop": "data:image/png;base64,Zm9v", "screenshotIsRegion": True,
        }],
        "synthetic_users": [{"id": "p1"}],
    })

    image_rule = next(rule for rule in deck.split("}") if rule.strip().startswith(".shot img{"))
    assert "max-height" in image_rule, "evidence image needs a height bound"
    # Without object-fit the height clamp squashes the image instead of scaling it.
    assert "object-fit:contain" in image_rule


def test_element_crop_is_capped_so_a_large_region_cannot_dominate_a_slide():
    pytest.importorskip("PIL")
    from io import BytesIO
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (1600, 4000), (10, 20, 30)).save(buffer, format="PNG")
    box = {"x": 0, "y": 0, "width": 1600, "height": 4000}

    uri = JobExecutor._crop_element_data_uri(buffer.getvalue(), box, max_edge=1200)

    assert uri is not None
    payload = base64.b64decode(uri.split(",", 1)[1])
    with Image.open(BytesIO(payload)) as cropped:
        assert max(cropped.width, cropped.height) <= 1200
        # Proportions must survive the cap.
        assert abs((cropped.width / cropped.height) - (1600 / 4000)) < 0.01


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
    assert "Re-design" in html and "working code, not a mockup" in html
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

    def fake_fragment(finding, url, providers=None, usage_sink=None):
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
        def __init__(self, reply): self.reply, self.usage_log = reply, []
        def complete_text(self, system, user, **kwargs): return self.reply

    import services.persona_service.semantic as semantic

    for reply, expected in [("<html><body>whole page</body></html>", None),
                            ("Sorry, I cannot do that.", None),
                            ("```html\n<div>ok</div>\n```", "<div>ok</div>")]:
        monkeypatch.setattr(semantic, "DirectLLMSemanticEngine",
                            lambda r=reply, **kwargs: Engine(r))
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


# --- CAP-4: redacting a screenshot's sensitive boxes before it ships -----------

def _decoded_data_uri(data_uri):
    from io import BytesIO
    from PIL import Image
    header, encoded = data_uri.split(",", 1)
    return Image.open(BytesIO(base64.b64decode(encoded)))


def test_redact_boxes_in_image_blanks_only_the_given_region():
    from io import BytesIO
    from PIL import Image

    image = Image.new("RGB", (200, 100), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    redacted_bytes = JobExecutor._redact_boxes_in_image(
        buffer.getvalue(), [{"x": 10, "y": 10, "width": 40, "height": 20}])
    redacted = Image.open(BytesIO(redacted_bytes))

    assert redacted.getpixel((20, 20)) == (0, 0, 0), "inside the box is blanked"
    assert redacted.getpixel((100, 80)) == (255, 255, 255), "outside the box is untouched"
    # No boxes: the original bytes come back unchanged, not a re-encode.
    assert JobExecutor._redact_boxes_in_image(buffer.getvalue(), []) == buffer.getvalue()


def test_boxes_to_redact_matches_by_selector_and_needs_a_box():
    elements = [
        {"selector": ".account-menu", "box": {"x": 1, "y": 2, "width": 3, "height": 4}},
        {"selector": ".no-box-here"},
        {"selector": "#buy-button", "box": {"x": 9, "y": 9, "width": 9, "height": 9}},
    ]

    assert JobExecutor._boxes_to_redact(elements, [".account-menu", ".no-box-here"]) == [
        {"x": 1, "y": 2, "width": 3, "height": 4}]
    assert JobExecutor._boxes_to_redact(elements, []) == []
    assert JobExecutor._boxes_to_redact(elements, None) == []


def test_redact_element_fields_blanks_name_text_value_for_listed_selectors_only():
    elements = [
        {"selector": ".account-menu", "role": "button", "name": "Signed in as jane.doe@example.com",
         "text": "jane.doe@example.com", "value": "jane.doe@example.com"},
        {"selector": "#buy-button", "role": "button", "name": "Buy now"},
    ]

    redacted = JobExecutor._redact_element_fields(elements, [".account-menu"])

    assert redacted[0]["name"] == redacted[0]["text"] == redacted[0]["value"] == "[REDACTED]"
    assert redacted[0]["selector"] == ".account-menu", "the selector itself is not a secret"
    assert redacted[0]["role"] == "button", "an unrelated field is untouched"
    assert redacted[1]["name"] == "Buy now", "an element off the list is untouched"
    assert JobExecutor._redact_element_fields(elements, []) == elements


def test_a_verdict_screenshot_is_blanked_before_it_is_cropped_when_its_region_is_listed(tmp_path):
    from PIL import Image
    import json as json_module

    screenshot = tmp_path / "final-view.png"
    Image.new("RGB", (200, 100), color="red").save(screenshot)
    snapshot = tmp_path / "final-view-dom.json"
    snapshot.write_text(json_module.dumps({"elements": [
        {"selector": ".account-menu", "role": "button", "name": "Signed in as jane.doe@example.com",
         "box": {"x": 0, "y": 0, "width": 200, "height": 100}}]}))

    findings = [{"title": "Account menu shows the wrong state", "source": "uxFindings", "runId": "run_1",
                "evidenceScreenshot": None, "elementBox": {"x": 0, "y": 0, "width": 200, "height": 100}}]
    JobExecutor._attach_verdict_screenshots(
        findings, [{"runId": "run_1", "artifacts": {"screenshots": [str(screenshot)], "snapshots": [str(snapshot)]}}],
        redact_selectors=[".account-menu"])

    decoded = _decoded_data_uri(findings[0]["screenshotCrop"]).convert("RGB")
    assert decoded.getpixel((decoded.width // 2, decoded.height // 2)) == (0, 0, 0), (
        "the whole cited region was the redacted box, so no red survives")

    # The same run, with no redact selectors, keeps the real pixels.
    findings_unredacted = [{"title": "Account menu shows the wrong state", "source": "uxFindings", "runId": "run_1",
                            "evidenceScreenshot": None, "elementBox": {"x": 0, "y": 0, "width": 200, "height": 100}}]
    JobExecutor._attach_verdict_screenshots(
        findings_unredacted, [{"runId": "run_1", "artifacts": {"screenshots": [str(screenshot)],
                                                                "snapshots": [str(snapshot)]}}])
    decoded_unredacted = _decoded_data_uri(findings_unredacted[0]["screenshotCrop"]).convert("RGB")
    assert decoded_unredacted.getpixel((decoded_unredacted.width // 2, decoded_unredacted.height // 2)) == (255, 0, 0)


# --- RPT-5/E7: annotating the evidence -----------------------------------------

def test_a_numbered_marker_is_drawn_on_the_elements_own_box():
    from io import BytesIO
    from PIL import Image

    image = Image.new("RGB", (200, 100), color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    crop = JobExecutor._crop_element_data_uri(
        buffer.getvalue(), {"x": 100, "y": 40, "width": 40, "height": 20}, number=3)

    decoded = _decoded_data_uri(crop).convert("RGB")
    # The badge is centred on the box's own top-left corner (offset by the crop's
    # own padding), not the crop's -- a badge in the crop's corner would point at
    # empty margin rather than the control itself.
    pad = 12
    badge_x, badge_y = pad, pad
    # A few pixels off centre: solid marker colour, clear of the number glyph's
    # own anti-aliased edge at the exact centre pixel.
    sample = (badge_x - 8, badge_y)
    assert decoded.getpixel(sample) == JobExecutor._EVIDENCE_MARKER_COLOR
    # No number: no marker drawn, and the crop is otherwise unchanged.
    plain = _decoded_data_uri(JobExecutor._crop_element_data_uri(
        buffer.getvalue(), {"x": 100, "y": 40, "width": 40, "height": 20})).convert("RGB")
    assert plain.getpixel(sample) == (255, 255, 255)


def test_evidence_numbers_are_unique_across_verdict_and_vision_findings(tmp_path):
    """The deck prints the same number beside a finding's title that its image
    carries, so two findings in one report must never draw the same digit --
    proven here by continuing the counter from a start other than 1, the way
    executor.py continues it past whatever _synthesize_pain_points already used."""
    from PIL import Image
    import json as json_module

    screenshot = tmp_path / "final-view.png"
    Image.new("RGB", (200, 100), color="white").save(screenshot)
    snapshot = tmp_path / "final-view-dom.json"
    snapshot.write_text(json_module.dumps({"elements": [
        {"selector": "#a", "box": {"x": 0, "y": 0, "width": 20, "height": 20}},
        {"selector": "#b", "box": {"x": 40, "y": 0, "width": 20, "height": 20}}]}))
    findings = [
        {"title": "First issue", "source": "uxFindings", "runId": "run_1", "evidenceScreenshot": None,
         "elementBox": {"x": 0, "y": 0, "width": 20, "height": 20}},
        {"title": "Second issue", "source": "uxFindings", "runId": "run_1", "evidenceScreenshot": None,
         "elementBox": {"x": 40, "y": 0, "width": 20, "height": 20}},
    ]
    JobExecutor._attach_verdict_screenshots(
        findings, [{"runId": "run_1", "artifacts": {"screenshots": [str(screenshot)],
                                                     "snapshots": [str(snapshot)]}}],
        start_evidence_number=5)

    assert [item["evidenceNumber"] for item in findings] == [5, 6]


def test_the_deck_prints_the_same_number_beside_the_title():
    html = JobExecutor._presentation({
        "critical_pain_points": [{"title": "Ambiguous label", "severity": "medium", "category": "ux",
                                  "summary": "s", "evidenceNumber": 2}],
        "elements_to_preserve": [], "impact_analysis": {}, "url": "https://example.com",
        "executive_summary": "", "evidence_language": "observed", "limitations": []})

    assert ">2<" in html


# --- RPT-5/C4: the re-design drawn in the page's own palette --------------------

def test_the_redesign_prompt_is_grounded_in_the_screenshots_own_colours(tmp_path, monkeypatch):
    from PIL import Image

    screenshot = tmp_path / "shot.png"
    image = Image.new("RGB", (200, 100), color=(30, 60, 90))
    image.paste((0, 0, 0), (0, 0, 40, 40))
    image.save(screenshot)

    monkeypatch.setenv("OPENAI_API_KEY", "fixture")
    captured = {}

    class FakeEngine:
        def __init__(self, **kwargs): self.usage_log = []
        def complete_text(self, system_prompt, user_prompt, **kwargs):
            captured["user_prompt"] = user_prompt
            return "<div>fixed</div>"

    import services.persona_service.semantic as semantic
    monkeypatch.setattr(semantic, "DirectLLMSemanticEngine", FakeEngine)

    finding = {"title": "Generic button", "summary": "s", "elements": [
        {"elementId": "#buy", "role": "button", "box": {"x": 0, "y": 0, "width": 40, "height": 40}}],
        "screenshotRef": str(screenshot), "alternatives": [{"proposedChange": "Make it blue"}]}

    fragment = JobExecutor._generate_redesign_fragment(finding, "https://example.com")

    assert fragment == "<div>fixed</div>"
    assert "#000000" in captured["user_prompt"], "the element's own measured colour reaches the prompt"
    assert "#1e3c5a" in captured["user_prompt"], "the page background, sampled from a corner, reaches the prompt"


def test_the_redesign_is_labelled_as_working_code_not_a_mockup():
    html = JobExecutor._finding_slide({
        "title": "Generic link text", "summary": "The link says only 'Learn more'.",
        "screenshotCrop": "data:image/png;base64,Zm9v", "screenshotIsRegion": True,
        "redesignHtml": '<div class="fix"><style>.fix a{font-weight:600}</style>'
                        '<a href="#">Read the IANA domain policy</a></div>',
    }, 1, "Observed user issue")

    assert "working code, not a mockup" in html


def test_a_redacted_element_never_leaves_this_process_in_the_vision_critique_request(tmp_path, monkeypatch):
    """The vision-critique request body is the one thing built here that
    actually leaves the deployment. An account name in its element list, or
    its sensitive region still visible in the pixels, is exactly the leak
    CAP-4 exists to close."""
    import json as json_module
    from PIL import Image

    screenshot = tmp_path / "step1.png"
    Image.new("RGB", (200, 100), color="red").save(screenshot)
    snapshot = tmp_path / "step1-dom.json"
    snapshot.write_text(json_module.dumps({"elements": [
        {"selector": ".account-menu", "role": "button", "name": "Signed in as jane.doe@example.com",
         "box": {"x": 0, "y": 0, "width": 200, "height": 100}}]}))

    captured = {}

    def urlopen(call, timeout):
        class Response:
            def __enter__(self_): return self_
            def __exit__(self_, *args): pass
            def read(self_): return json_module.dumps({"painPoints": []}).encode()
        captured["payload"] = json_module.loads(call.data)
        return Response()

    monkeypatch.setattr("apps.api.executor.request.urlopen", urlopen)
    journeys = [{"runId": "run_1", "artifacts": {"screenshots": [str(screenshot)], "snapshots": [str(snapshot)]}}]
    JobExecutor._collect_vision_pain_points(
        journeys, ["Buy an item"], [{"id": "persona_ada"}], "https://example.com",
        vision=[("https://mine.example/v1", "sk-mine", "vision-model")], send_options=True,
        redact_selectors=[".account-menu"])

    payload = captured["payload"]
    assert payload["elements"][0]["name"] == "[REDACTED]"
    assert "jane.doe" not in json_module.dumps(payload)
    decoded = _decoded_data_uri(f"data:{payload['imageMimeType']};base64,{payload['imageBase64']}").convert("RGB")
    assert decoded.getpixel((decoded.width // 2, decoded.height // 2)) == (0, 0, 0), (
        "the sensitive region is blanked in the pixels the model actually receives")


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


def test_be5_a_finding_seen_in_two_runs_is_reproduced_in_two_not_one():
    """BE-5: a finding seen in 2 of 2 runs is a different claim from 1 of 2.
    Real once a cohort runs any persona more than once (repeat seeds); on a
    cohort that does not, every finding is honestly reproducedIn: 1."""
    merged = JobExecutor._merge_similar_findings([
        {"title": "Ambiguous navigation hierarchy", "severity": "medium", "runId": "run_1",
         "summary": "The page uses two different sets of navigation controls that seem to overlap."},
        {"title": "Redundant and confusing navigation layers", "severity": "medium", "runId": "run_2",
         "summary": "The page uses two different sets of navigation controls that seem to overlap."},
        {"title": "Missing input labels", "severity": "medium", "runId": "run_1",
         "summary": "Several input fields rely on placeholder text rather than explicit labels."},
    ])

    by_title = {item["title"]: item for item in merged}
    navigation = next(item for title, item in by_title.items() if "navigation" in title.lower())
    assert navigation["reproducedIn"] == 2
    assert by_title["Missing input labels"]["reproducedIn"] == 1

    # The same run's own findings merging (e.g. a duplicate phrasing within one
    # journey) must not be counted as two separate reproductions of the claim.
    same_run = JobExecutor._merge_similar_findings([
        {"title": "Generic link text", "severity": "medium", "runId": "run_1", "summary": "Says only Learn more."},
        {"title": "Ambiguous link text", "severity": "medium", "runId": "run_1", "summary": "Says only Learn more."},
    ])
    assert same_run[0]["reproducedIn"] == 1


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


def test_a_cited_capture_names_the_artifact_a_reader_can_download():
    """A live report's only finding cited "snapshot: 003-snapshot.txt". The session
    held that capture -- as "browser-snapshot-<job>-003-snapshot.json" -- and no
    artifact was called what the report called it. Evidence a reader cannot resolve
    from the citation is evidence the report did not really produce."""
    from apps.api.executor import _evidence_reference_summary

    summary = _evidence_reference_summary({
        "screenshot": "/run/screenshots/003-click-e2-after.png",
        "snapshot": "/run/snapshots/003-snapshot.txt",
        "uiChangeTimeline": "/run/ui-changes/003-click-e2.json",
    }, "job_abc")

    for kind, stem in (("browser.screenshot", "003-click-e2-after"),
                       ("browser.snapshot", "003-snapshot"),
                       ("browser.ui-change", "003-click-e2")):
        expected = JobExecutor._download_name(kind, "job_abc", stem)
        assert expected in summary, f"{expected} is how the session lists it"
    # The run-local name is not what the artifact is called, so it must not be
    # what the report cites.
    assert "003-snapshot.txt" not in summary


def test_a_slide_never_heads_a_capture_reference_as_root_cause_analysis():
    """RPT-2: no fallback to `observation` or `mechanism` -- only an explicit
    `rootCause` a finding's own source actually named fills this panel. A panel
    that cannot be filled honestly is left out, not filled with the symptom
    (or a bare capture reference) wearing a different heading."""
    with_root_cause = JobExecutor._finding_slide(
        {"title": "Overwhelming number of buttons", "summary": "Many controls compete for attention.",
         "rootCause": "Fifteen buttons share one visual weight, so none reads as primary.",
         "observation": "Initial snapshot shows more than 15 buttons without scrolling.",
         "evidence": "snapshot: 001-snapshot.txt"}, 1, "Observed user issue")
    no_root_cause = JobExecutor._finding_slide(
        {"title": "Guided tour for new users", "summary": "The product offers many features.",
         "observation": "Initial snapshot shows more than 15 buttons without scrolling.",
         "evidence": "snapshot: 001-snapshot.txt"}, 1, "Observed user issue")

    assert "Fifteen buttons share one visual weight" in with_root_cause
    assert "Root cause analysis" not in no_root_cause
    assert "001-snapshot.txt" not in with_root_cause and "001-snapshot.txt" not in no_root_cause
    assert "Initial snapshot shows more than 15 buttons" not in no_root_cause


def test_e8_a_root_cause_that_paraphrases_the_symptom_is_refused_not_just_an_exact_repeat():
    """RPT-2/E8: refused when it substantially repeats the issue panel, not only
    when the two strings are byte-identical -- a paraphrase of the symptom says
    nothing new, just harder to catch than an exact copy."""
    paraphrased = JobExecutor._finding_slide({
        "title": "Confusing checkout", "summary": "Many controls compete for the visitor's attention on the page.",
        "rootCause": "Many controls are competing for the visitor's attention on this page.",
    }, 1, "Observed user issue")
    real_cause = JobExecutor._finding_slide({
        "title": "Confusing checkout", "summary": "Many controls compete for the visitor's attention on the page.",
        "rootCause": "Every control shares the same size and colour, so none reads as more important.",
    }, 1, "Observed user issue")

    assert "Root cause analysis" not in paraphrased
    assert "Root cause analysis" in real_cause
    assert "Every control shares the same size and colour" in real_cause


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


def test_the_quote_corpus_includes_non_interactive_page_text(tmp_path):
    """The ".json" DOM captures carry only interactive elements, so checking a quote
    against those alone would reject a true finding that quotes a heading. The
    ".txt" accessibility trees journeytest-core writes beside them include the
    non-interactive nodes, one per line with its visible text quoted."""
    import json as json_module

    dom = tmp_path / "001-click-e9-after-dom.json"
    dom.write_text(json_module.dumps({"elements": [
        {"selector": "#signin", "role": "button", "text": "Sign in with HF"}]}))
    tree = tmp_path / "001-snapshot.txt"
    tree.write_text('- generic "Run audits with synthetic users" [ref=e1] clickable\n'
                    '  - heading "What UserSync does" [ref=e2]\n'
                    '  - button "Sign in with HF" [ref=e9]\n')

    corpus = JobExecutor._visible_text_corpus([{"artifacts": {"snapshots": [str(dom), str(tree)]}}])

    assert "What UserSync does" in corpus  # a heading, absent from the DOM capture
    assert JobExecutor._quote_is_on_page("What UserSync does", corpus)
    assert JobExecutor._quote_is_on_page("Run audits", corpus)  # the start of a longer node
    assert not JobExecutor._quote_is_on_page("Simulation Results", corpus)


def test_a_worker_failure_is_reported_with_what_the_worker_said():
    """A live run's report explained a missing vision critique with nothing but
    "failed: HTTP Error 422: Unprocessable Entity" -- urllib's rendering of the
    status line. The worker's own explanation was in the response body, and the
    body was being thrown away."""
    import json as json_module
    from io import BytesIO
    from urllib import request as urllib_request

    detailed = urllib_request.HTTPError(
        "http://127.0.0.1:8081/v1/journey-evidence-analyses", 502, "Bad Gateway", {},
        BytesIO(json_module.dumps({"error": "vision_upstream_failed",
                                   "message": "vision critique failed after 3 attempts: fetch failed"}).encode()))
    bodyless = urllib_request.HTTPError(
        "http://127.0.0.1:8081/v1/journey-evidence-analyses", 500, "Server Error", {}, BytesIO(b"not json"))

    assert JobExecutor._worker_error(detailed) == (
        "HTTP 502 from the eyeson worker: vision critique failed after 3 attempts: fetch failed")
    assert "500" in JobExecutor._worker_error(bodyless)
    assert JobExecutor._worker_error(OSError("connection refused")) == "connection refused"


def test_the_client_waits_out_the_workers_own_retries(monkeypatch):
    """visionCritique.js makes up to 3 attempts at a 60s timeout with backoff --
    about 186s in the worst case. The previous 90s wait cut the worker off
    mid-retry and turned a slow-but-recoverable call into a client-side timeout."""
    monkeypatch.delenv("EYESON_VISION_TIMEOUT", raising=False)
    assert JobExecutor._vision_timeout() >= 186
    monkeypatch.setenv("EYESON_VISION_TIMEOUT", "45")
    assert JobExecutor._vision_timeout() == 45


def test_vision_stage_praise_is_preserved_not_filed_as_an_issue():
    """The vision model has a "strengths" array of its own and still puts praise in
    "issues": a live run published "Familiar and clean layout" as a medium-severity
    usability issue alongside a real navigation problem."""
    praise = {"title": "Familiar and clean layout", "severity": "medium",
              "summary": "The login interface is centered, clean, and uses highly recognizable form "
                         "patterns, which reduces cognitive friction for returning users.",
              "source": "eyeson-vision-synthesis", "affectedPersonaIds": ["p1", "p2"],
              "route": "https://example.com", "screenshotRef": "/run/shot.png", "elements": []}
    issue = {"title": "Confusing workflow navigation", "severity": "medium",
             "summary": "The page features two different sets of navigation controls for the same "
                        "workflow steps, which creates cognitive load and confusion.",
             "source": "eyeson-vision-synthesis", "affectedPersonaIds": ["p1"]}

    assert _reads_as_praise(praise["title"], praise["summary"])
    assert not _reads_as_praise(issue["title"], issue["summary"])

    strengths = JobExecutor._praise_as_strengths([praise])
    # One entry per persona the synthesis credited, so _merge_strengths can count them.
    assert [item["personaId"] for item in strengths] == ["p1", "p2"]
    assert strengths[0]["description"].startswith("The login interface is centered")

    merged = JobExecutor._merge_strengths(strengths)
    assert len(merged) == 1
    assert merged[0]["observedByPersonas"] == 2


def test_persona_thoughts_prefer_the_models_real_reasoning_over_verdict_prose():
    """The report used to quote the agent's end-of-run verdict prose, which reads as
    generic UX commentary written after the fact rather than what the model was
    thinking while it drove the browser. journeytest-core keeps only `text` content
    blocks when recording an assistant turn and drops the `thinking` blocks a
    reasoning model returns, so the journey worker now captures the reasoning from
    the completions responses themselves."""
    journey = {
        "runId": "run_1",
        "reasoning": [
            {"elapsedMs": 4200, "text": "The header says 'SyncUsers' which tells me nothing about "
                                        "what this does. I will click it to find out.", "model": "auto"},
            {"elapsedMs": 900, "text": "The page has loaded. I need to find a way in.", "model": "auto"},
        ],
        "timeline": [{"type": "browser.click", "summary": "Clicked 'SyncUsers'", "elapsedMs": 5000}],
        "verdict": {"summary": "Completed all tasks.",
                    "uxFindings": [{"title": "Jargon", "description": "The heading uses technical jargon."}]},
    }

    thoughts = JobExecutor._persona_thoughts(journey)
    reasoning = [item for item in thoughts if item["kind"] == "reasoning"]

    assert [item["source"] for item in reasoning] == ["model.reasoning", "model.reasoning"]
    # In the order the model produced it, and it is the model's words, not the verdict's.
    assert reasoning[0]["text"].startswith("The header says 'SyncUsers'")
    assert all("technical jargon" not in item["text"] for item in reasoning)
    # The browser action is still there, so the log reads as a journey.
    assert any(item["kind"] == "action" for item in thoughts)


def test_verdict_prose_is_still_used_when_no_reasoning_was_captured():
    """A run whose provider returned no reasoning must not report that the persona
    thought nothing -- but it must say where the words came from."""
    journey = {"runId": "run_1", "reasoning": [], "timeline": [],
               "verdict": {"summary": "Completed all tasks.",
                           "uxFindings": [{"title": "Jargon", "description": "The heading uses jargon."}]}}

    sources = {item["source"] for item in JobExecutor._persona_thoughts(journey)}

    assert sources == {"verdict", "verdict.uxFindings"}
    assert "model.reasoning" not in sources


def _run_journey_job(tmp_path, monkeypatch, worker_payload, *, tasks=("Judge the offers",)):
    """Drive one combined_test job against a stubbed Journey worker and return the report."""
    import json as json_module
    from urllib import error as error_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_fw", "persona": {"name": "Friedrich Wolf"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}})

    class WorkerResponse:
        def __init__(self, request): self.request = request
        def __enter__(self):
            payload = json_module.loads(self.request.data)
            body = dict(worker_payload)
            body.setdefault("runId", payload["runId"])
            body.setdefault("profileId", "persona_fw")
            body.setdefault("simulationProfile", payload["profile"])
            self.payload = json_module.dumps(body).encode()
            return self
        def __exit__(self, *args): pass
        def read(self): return self.payload

    def urlopen(call, timeout):
        # The vision stage has its own worker and its own URL. It is best-effort by
        # design, so an unreachable one exercises the Journey path on its own.
        if "/v1/runs" not in call.full_url:
            raise error_module.URLError("vision worker not configured for this test")
        return WorkerResponse(call)

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.delenv("EYESON_WORKER_URL", raising=False)
    monkeypatch.setattr("apps.api.executor.request.urlopen", urlopen)
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": list(tasks)},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    report = (json_module.loads(store.read_artifact(completed["output_artifacts"][0]))
              if completed["output_artifacts"] else None)
    return completed, report


def test_run_that_errored_after_recording_its_verdict_is_still_reported(tmp_path, monkeypatch):
    """A live run browsed for 19 minutes, produced a verdict, and then failed at
    `agent-browser record stop` because ffmpeg was missing from the image. The
    verdict was already written to run.json, yet the job reported nothing but the
    error -- the whole run was thrown away over a bookkeeping step that runs after
    the browsing is done. The verdict is the run's own answer and must survive."""
    verdict = {
        "status": "failed", "confidence": "high", "summary": "The offers were never explained.",
        "criteria": [{"id": "tasks-completed", "result": "not-met", "explanation": "No pricing was found."},
                     {"id": "tasks-blocked", "result": "not-met", "explanation": "Nothing blocked the run."}],
        "blockers": [], "suggestedImprovements": [],
        "uxFindings": [{"id": "finding-1", "severity": "major", "category": "content",
                        "title": "Offers are never priced",
                        "description": "No page states what any plan costs."}],
    }
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "error",
        "error": {"message": "agent-browser command failed: record stop -- ffmpeg not found"},
        "verdict": verdict,
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    assert "Offers are never priced" in {item["title"] for item in report["critical_pain_points"]}
    # The run is not presented as a whole one: the status and a limitation both
    # say it was cut short, and the limitation names the failure.
    assert report["journey_outcome"]["status"] == "partial"
    assert report["evidence_language"] == "observed"
    cut = [line for line in report["limitations"] if "did not finish cleanly" in line]
    assert cut and "ffmpeg not found" in cut[0]
    assert "its verdict was recorded before the failure and is included" in cut[0]


def test_run_that_died_before_any_verdict_keeps_its_screenshots(tmp_path, monkeypatch):
    """The director's connection dropped 14 minutes in ("Pi director provider error:
    terminated"), so no verdict was reached -- but 37 screenshots and a video were
    already on disk. Those are still real evidence for the vision critique, and a
    report that says "no pain points detected" about them would be a false clean
    bill of health."""
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "error",
        "error": {"message": "Pi director provider error: terminated"},
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png", "/tmp/run/screenshots/002.png"]},
    })

    assert completed["status"] == "succeeded"
    assert report["journey_outcome"]["status"] == "partial"
    titles = {item["title"] for item in report["critical_pain_points"]}
    assert "Journey ended early -- no findings collected" in titles
    assert "No pain points detected" not in titles
    cut = [line for line in report["limitations"] if "did not finish cleanly" in line]
    assert cut and "no verdict was reached" in cut[0]


def test_run_that_produced_neither_verdict_nor_evidence_fails_the_job(tmp_path, monkeypatch):
    """Salvage is not a licence to report on nothing. A run that never reached a
    page has no evidence to stand on, and a report built from it would be fiction."""
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "error",
        "error": {"message": "agent-browser failed to launch: no usable Chromium"},
        "artifacts": {"screenshots": []},
    })

    assert completed["status"] == "failed"
    assert report is None
    assert "no usable Chromium" in completed["error"]["message"]


def test_a_never_looked_at_finding_carries_the_scan_memory_caveat(tmp_path, monkeypatch):
    """CAP-0: before the scan carried alreadySeen across steps, "on screen and
    never looked at" partly measured the scan re-fixating the same few elements
    every step rather than the page's prominence. The report says so, in both
    directions, whenever it publishes one of these findings."""
    missed = {"selector": "p.price", "name": "From EUR 49 per month", "goalAffinity": 0.85,
              "box": {"x": 40, "y": 73, "width": 300, "height": 26}}
    perception_step = {"eyes": {"acuity": 1.0, "contrastSensitivity": 1.0, "blurPx": 0.0},
                       "scan": {"pattern": "spotted", "fixationBudget": 6,
                                "why": ["little patience, so they hunt for the one thing they came for"]},
                       "counts": {"elements": 15, "fixated": 6},
                       "notPerceived": [], "notLookedAt": ["e2", "e4"],
                       "missedWhatTheyCameFor": [missed]}
    timeline = [{"type": "persona.perception", "data": perception_step} for _ in range(2)]
    timeline.append({"type": "persona.reflection", "data": {"matched": "no", "gap": "No price seen."}})
    verdict = {"status": "failed", "criteria": [], "blockers": [], "uxFindings": [], "suggestedImprovements": []}

    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed", "verdict": verdict, "timeline": timeline,
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    assert "On screen and never looked at" in {item["title"].split(": ")[0]
                                               for item in report["critical_pain_points"]}
    caveat = [line for line in report["limitations"] if "remembers what each persona" in line]
    assert caveat, "a report publishing this finding class must say what changed about it"
    assert "same few elements on every step" in caveat[0]


def test_no_scan_memory_caveat_when_nothing_from_that_class_is_published(tmp_path, monkeypatch):
    """The caveat is not boilerplate on every report -- only on the ones that
    actually carry a finding it is about."""
    verdict = {"status": "passed", "criteria": [{"id": "tasks-completed", "result": "met"}],
              "blockers": [], "uxFindings": [], "suggestedImprovements": []}
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed", "verdict": verdict,
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    assert not [line for line in report["limitations"] if "remembers what each persona" in line]


def test_a_mid_run_session_expiry_is_a_run_diagnostic_not_a_finding_about_the_page(tmp_path, monkeypatch):
    """CAP-4: a run whose authenticated session stopped holding reviewed the
    logged-out product without knowing it. The director ends the run there
    (personaDirector.js) rather than continuing, with an "inconclusive" verdict
    and no blocker -- this proves the report reads that as a harness diagnostic,
    the same class as persona.perception_unavailable, never as a usability
    finding about the page."""
    timeline = [{"type": "journey.session_expired",
                "data": {"reason": 'saw a "Sign in" prompt where the session was expected to still be '
                                   "authenticated", "sinceStep": 3, "url": "https://example.com/account"}}]
    verdict = {"status": "inconclusive", "confidence": "low",
              "summary": "Stopped after 3 actions -- the authenticated session expired mid-run.",
              "criteria": [{"id": "tasks-completed", "result": "not-observed"},
                           {"id": "tasks-blocked", "result": "not-observed"}],
              "blockers": [], "uxFindings": [], "suggestedImprovements": []}

    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed", "verdict": verdict, "timeline": timeline,
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    diagnostics = report["run_diagnostics"]
    expired = [item for item in diagnostics if item["title"].startswith("The authenticated session")]
    assert expired, "the expiry must reach the reader as a diagnostic, not silence"
    assert expired[0]["category"] == "harness"
    assert "signed in" in expired[0]["summary"] or "logged-out" in expired[0]["summary"]
    # Never counted or titled as a usability problem with the page itself.
    assert not any("session" in item.get("title", "").lower() for item in report["critical_pain_points"])


def test_clean_run_is_still_reported_as_completed(tmp_path, monkeypatch):
    """The salvage path must not relabel healthy runs."""
    completed, report = _run_journey_job(tmp_path, monkeypatch, {
        "runStatus": "completed",
        "verdict": {"status": "passed", "confidence": "high", "summary": "All good.",
                    "criteria": [{"id": "tasks-completed", "result": "met", "explanation": "Done."}],
                    "blockers": [], "uxFindings": [], "suggestedImprovements": []},
        "artifacts": {"screenshots": ["/tmp/run/screenshots/001.png"]},
    })

    assert completed["status"] == "succeeded"
    assert report["journey_outcome"]["status"] == "completed"
    assert not any("did not finish cleanly" in line for line in report["limitations"])
    assert "No pain points detected" in {item["title"] for item in report["critical_pain_points"]}


def test_verdict_is_read_from_disk_when_the_worker_answer_times_out(tmp_path, monkeypatch):
    """A live two-task journey took 855s and another took 1159s, both past the old
    600s client timeout. The run keeps going and writes its result to disk either
    way, so a timed-out socket is not a lost verdict -- the artifact tree is shared
    between the API and the worker in the Space, and the file is right there."""
    import json as json_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_fw", "persona": {"name": "Friedrich Wolf"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}})
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Judge the offers"]},
        "idempotency_key": None})

    # The layout journeytest-core actually writes: a timestamp-prefixed directory,
    # and a runId inside the file that carries the same prefix.
    run_id = f"{job['job_id']}_persona_fw"
    root = tmp_path / "journeys"
    (root / f"2026-09-10T00-33-40-422Z-{run_id}").mkdir(parents=True)
    (root / f"2026-09-10T00-33-40-422Z-{run_id}" / "run.json").write_text(json_module.dumps({
        "runId": f"2026-09-10T00-33-40-422Z-{run_id}", "runStatus": "completed",
        "artifacts": {"screenshots": []},
        "verdict": {"status": "failed", "confidence": "high", "summary": "No pricing anywhere.",
                    "criteria": [{"id": "tasks-completed", "result": "not-met", "explanation": "No pricing."}],
                    "blockers": [{"id": "b1", "severity": "major", "category": "content",
                                  "title": "Plans are never priced",
                                  "description": "No page states what a plan costs."}],
                    "uxFindings": [], "suggestedImprovements": []},
    }))
    monkeypatch.setenv("JOURNEY_ARTIFACT_ROOT", str(root))
    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")

    def urlopen(call, timeout):
        raise TimeoutError("timed out")
    monkeypatch.setattr("apps.api.executor.request.urlopen", urlopen)

    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "succeeded"
    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))
    assert "Plans are never priced" in {item["title"] for item in report["critical_pain_points"]}
    # Salvaged from disk, but the run itself finished cleanly -- nothing to caveat.
    assert report["journey_outcome"]["status"] == "completed"
    # The persona the job asked for is re-attached, since the file records the run
    # and not who the caller was running it as.
    assert report["journey_outcome"]["runs"][0]["profileId"] == "persona_fw"


def test_timeout_with_nothing_on_disk_fails_with_an_actionable_message(tmp_path, monkeypatch):
    """No file means the run never got to write one. Say what to turn up rather than
    reporting a bare socket error."""
    import json as json_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_fw", "persona": {"name": "Friedrich Wolf"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}})
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Judge the offers"]},
        "idempotency_key": None})
    monkeypatch.setenv("JOURNEY_ARTIFACT_ROOT", str(tmp_path / "empty"))
    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen",
                        lambda call, timeout: (_ for _ in ()).throw(TimeoutError("timed out")))

    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "failed"
    assert "JOURNEY_RUN_TIMEOUT" in completed["error"]["message"]


def test_a_refused_connection_is_not_treated_as_a_timeout(tmp_path, monkeypatch):
    """Only "the answer did not arrive in time" justifies going to disk. A refused
    or unresolvable worker never started a run, and its own error is the useful one."""
    from urllib import error as error_module
    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_fw", "persona": {"name": "Friedrich Wolf"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}})
    ids = [persona["artifact_id"]]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Judge the offers"]},
        "idempotency_key": None})
    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setattr("apps.api.executor.request.urlopen",
                        lambda call, timeout: (_ for _ in ()).throw(
                            error_module.URLError(ConnectionRefusedError("connection refused"))))

    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    assert completed["status"] == "failed"
    assert "refused" in completed["error"]["message"]
    assert "JOURNEY_RUN_TIMEOUT" not in completed["error"]["message"]


def test_journey_run_timeout_default_covers_measured_run_lengths(monkeypatch):
    """Both live runs of the sample journey outlasted the old 600s default."""
    monkeypatch.delenv("JOURNEY_RUN_TIMEOUT", raising=False)
    assert JobExecutor._journey_run_timeout() >= 1159
    monkeypatch.setenv("JOURNEY_RUN_TIMEOUT", "45")
    assert JobExecutor._journey_run_timeout() == 45
    monkeypatch.setenv("JOURNEY_RUN_TIMEOUT", "not-a-number")
    assert JobExecutor._journey_run_timeout() >= 1159


def _png(image):
    from io import BytesIO
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_a_capture_that_repeats_one_band_is_trimmed_to_the_band_that_is_real():
    """A live run against a real customer site produced a 1280x8620 full-page
    capture holding the same header-and-hero band about fourteen times -- what a
    stitched screenshot does when the page pins its layout to the viewport. The
    vision model reported a CRITICAL "infinite repeating page content ... makes
    the site look completely broken" defect, and it went into the report as the
    single thing to fix first. The site is fine; the capture was not."""
    from io import BytesIO
    from PIL import Image
    from apps.api.executor import JobExecutor

    band = Image.new("RGB", (1280, 600), (250, 250, 250))
    band.paste(Image.new("RGB", (1280, 64), (12, 40, 90)), (0, 0))          # a header
    band.paste(Image.new("RGB", (900, 200), (30, 120, 70)), (190, 180))     # a hero
    stitched = Image.new("RGB", (1280, 600 * 14))
    for index in range(14):
        stitched.paste(band, (0, index * 600))

    trimmed, original_height = JobExecutor._trim_repeated_capture(_png(stitched))
    assert original_height == 8400
    with Image.open(BytesIO(trimmed)) as kept:
        assert kept.width == 1280
        # One band, give or take the resolution the detector works at.
        assert 500 <= kept.height <= 700


def test_a_page_that_merely_repeats_its_own_cards_is_left_alone():
    """Repetition is not the signature -- plenty of real pages stack identical
    rows. What identifies a stitch is that the image resembles itself more a whole
    band apart than one row apart, which a page with a header and varied content
    cannot do."""
    from PIL import Image
    from apps.api.executor import JobExecutor

    page = Image.new("RGB", (1280, 5000), (250, 250, 250))
    page.paste(Image.new("RGB", (1280, 300), (12, 40, 90)), (0, 0))         # header, once
    for y in range(300, 5000, 200):
        page.paste(Image.new("RGB", (1100, 160), (220, 225, 235)), (90, y))  # identical cards
    assert JobExecutor._trim_repeated_capture(_png(page))[1] is None

    varied = Image.new("RGB", (1280, 6000))
    for y in range(0, 6000, 40):
        varied.paste(Image.new("RGB", (1280, 40), (y % 255, (y * 3) % 255, (y * 7) % 255)), (0, y))
    assert JobExecutor._trim_repeated_capture(_png(varied))[1] is None


def test_an_ordinary_viewport_screenshot_is_never_considered():
    """The artifact only exists in stitched full-page captures, and the check
    should cost nothing on the screenshots that are not."""
    from PIL import Image
    from apps.api.executor import JobExecutor
    assert JobExecutor._trim_repeated_capture(_png(Image.new("RGB", (1280, 720), (30, 40, 50))))[1] is None
    # A blank capture repeats nothing, rather than repeating everything.
    assert JobExecutor._trim_repeated_capture(_png(Image.new("RGB", (1280, 6000), (255, 255, 255))))[1] is None


# A profile in the bottom few percent of corrected vision, and a typical one.
RARE_EYES = {"acuity": 0.35, "contrastSensitivity": 0.25, "blurPx": 1.95}
TYPICAL_EYES = {"acuity": 1.0, "contrastSensitivity": 1.0, "blurPx": 0.0}

# The same element, measured on the page as drawn, either side of the WCAG line.
FAILS_WCAG = {"selector": "p.fine", "role": "text",
              "name": "Prices exclude VAT. Enterprise terms apply to seats over 50.",
              "box": {"x": 40, "y": 223, "width": 460, "height": 18},
              "reason": "too little contrast to make anything out",
              "internalContrast": 0.035, "edgeContrast": 0.0028, "ink": 0.0,
              "contrast": {"ratio": 2.85, "required": 4.5, "passes": False,
                           "measured": "text against its own background"}}
PASSES_WCAG = {**FAILS_WCAG, "selector": "p.ok", "name": "Choose the plan that fits how you work",
               "contrast": {"ratio": 7.1, "required": 4.5, "passes": True,
                            "measured": "text against its own background"}}
MISSED_PRICE = {"selector": "p.price", "name": "From EUR 49 per month", "goalAffinity": 0.85,
                "box": {"x": 40, "y": 73, "width": 300, "height": 26}}


def _perception_journey(run_id="run_1", persona="friedrich_wolf", eyes=None,
                        unreadable=(), missed=(), gap="No price was visible anywhere.",
                        steps=2, seen_image=None):
    """One run that looked at a page, repeated over `steps` steps."""
    step = {"eyes": eyes or RARE_EYES,
            "scan": {"pattern": "spotted", "fixationBudget": 6,
                     "why": ["little patience, so they hunt for the one thing they came for"]},
            "counts": {"elements": 15, "fixated": 6},
            "notPerceived": list(unreadable), "notLookedAt": ["e2", "e4"],
            "missedWhatTheyCameFor": list(missed), "seenImage": seen_image}
    timeline = [{"type": "persona.perception", "data": step} for _ in range(steps)]
    timeline.append({"type": "persona.reflection", "data": {"matched": "no", "gap": gap}})
    return {"runId": run_id, "profileId": persona, "timeline": timeline}


def test_an_element_that_fails_wcag_is_an_accessibility_defect_whoever_found_it():
    """The contrast is measured on the page as drawn, so it is a fact about the
    site and true for every visitor. It stands on its own however rare the profile
    that happened to surface it."""
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[FAILS_WCAG], eyes=RARE_EYES)])
    assert len(findings) == 1
    finding = findings[0]

    assert finding["severity"] == "high" and finding["category"] == "accessibility"
    assert "Fails WCAG AA contrast" in finding["title"]
    assert "2.85:1" in finding["summary"] and "4.5:1" in finding["summary"]
    assert finding["wcagPasses"] is False and finding["contrastRatio"] == 2.85
    # And a fix that says where not to look.
    assert "declared CSS colours is not enough" in finding["recommendation"]
    # Backed by what the persona actually said.
    assert finding["personaEvidence"][0]["quote"] == "No price was visible anywhere."


def test_a_compliant_element_missed_by_one_rare_profile_is_not_called_a_defect():
    """The rule that keeps the report believable. A run that happened to include
    one very short-sighted profile must not turn a compliant page into a failing
    one -- so it is said, and kept out of the numbered problems."""
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[PASSES_WCAG], eyes=RARE_EYES)])
    finding = findings[0]

    assert finding["severity"] == "info", "never ranked or counted among the problems"
    assert finding["category"] == "profile-specific"
    assert "one low-vision profile only" in finding["title"]
    assert "0.35" in finding["summary"], "and it says which profile"
    assert "No change is required for compliance" in finding["recommendation"]
    assert JobExecutor._SEVERITY_RANK["info"] < JobExecutor._SEVERITY_RANK["low"]
    assert "info" in JobExecutor._NOT_A_PROBLEM


def test_a_compliant_element_missed_by_several_profiles_is_a_finding_about_the_page():
    """Consistency is what turns one visitor's trouble into evidence about the
    element -- and it is still not a compliance claim."""
    findings = JobExecutor._pain_points_from_perception([
        _perception_journey("r1", "low_vision", RARE_EYES, [PASSES_WCAG], gap="Could not read it."),
        _perception_journey("r2", "typical", TYPICAL_EYES, [PASSES_WCAG], gap="Hard to make out."),
        _perception_journey("r3", "hurried", {"acuity": 0.8, "contrastSensitivity": 0.7},
                            [PASSES_WCAG], gap="Missed the terms."),
    ])
    assert len(findings) == 1, "one element, one finding, however many personas met it"
    finding = findings[0]

    assert finding["severity"] == "medium" and finding["category"] == "legibility"
    assert finding["affectedPersonas"] == 3
    assert set(finding["affectedPersonaIds"]) == {"low_vision", "typical", "hurried"}
    assert "3 different personas" in finding["summary"]
    assert "about the element rather than about one visitor" in finding["summary"]
    assert "Meeting the minimum is not the same as being easy to read" in finding["recommendation"]


def test_a_typical_profile_missing_something_compliant_is_a_hint_not_an_info_note():
    """Only an unusual profile earns the "not a defect" downgrade. A typical
    visitor failing to read compliant text is worth more attention, not less."""
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[PASSES_WCAG], eyes=TYPICAL_EYES)])
    assert findings[0]["severity"] == "low"
    assert findings[0]["category"] == "legibility"


def test_something_they_came_for_and_missed_gets_worse_as_more_people_miss_it():
    one = JobExecutor._pain_points_from_perception(
        [_perception_journey(missed=[MISSED_PRICE])])[0]
    assert one["severity"] == "medium" and one["category"] == "findability"
    assert "prominence problem, not a wording one" in one["recommendation"]

    several = JobExecutor._pain_points_from_perception([
        _perception_journey("r1", "a", RARE_EYES, missed=[MISSED_PRICE]),
        _perception_journey("r2", "b", TYPICAL_EYES, missed=[MISSED_PRICE]),
    ])[0]
    assert several["severity"] == "high", "several people coming for it and not seeing it is worse"
    assert "2 different personas missed it" in several["summary"]


def test_the_same_element_across_every_step_and_run_is_one_finding():
    """A low-contrast caption is unreadable on every step of every visit. Reported
    per step it would bury everything else in the report."""
    findings = JobExecutor._pain_points_from_perception([
        _perception_journey("r1", "a", RARE_EYES, [FAILS_WCAG], steps=20),
        _perception_journey("r2", "b", TYPICAL_EYES, [FAILS_WCAG], steps=20),
    ])
    assert len(findings) == 1
    assert "40 steps" in findings[0]["evidence"]
    assert findings[0]["affectedPersonas"] == 2


def test_a_run_that_saw_everything_produces_no_perception_findings():
    """The model has to find real problems, not make every page a defect."""
    assert JobExecutor._pain_points_from_perception([_perception_journey()]) == []
    assert JobExecutor._pain_points_from_perception([{"runId": "old", "timeline": []}]) == []


def test_an_element_with_no_name_is_still_reportable():
    nameless = {**FAILS_WCAG, "selector": "div.badge", "role": "img", "name": "",
                "box": {"x": 950, "y": 760, "width": 300, "height": 100}}
    finding = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[nameless])])[0]
    assert "950,760" in finding["title"], "located by where it is when it cannot be named"


def test_an_eyesight_finding_cites_the_page_as_they_actually_saw_it():
    """A clean screenshot beside "they could not read this" invites the reader to
    disagree with the finding, correctly."""
    finding = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[FAILS_WCAG],
                             seen_image="/tmp/aux/shots/003-as-they-saw-it.jpg")])[0]
    assert finding["evidenceScreenshot"] == "/tmp/aux/shots/003-as-they-saw-it.jpg"
    assert finding["evidenceIsAsTheySawIt"] is True
    # And the box, so the report can crop to the element rather than show the page.
    assert finding["elementBox"] == FAILS_WCAG["box"]


def test_the_summary_names_the_worst_finding_rather_than_only_counting():
    """"12 issues, 3 high-severity" is true of almost any report and tells a
    reader nothing they can act on."""
    findings = [
        {"severity": "high", "title": 'On screen and never looked at: "From EUR 49 per month"',
         "source": "perception.missed"},
        {"severity": "high", "title": "Not readable to this person: \"Prices exclude VAT\"",
         "source": "perception.notPerceived"},
        {"severity": "medium", "title": "Vague call to action", "source": "uxFindings"},
    ]
    summary = JobExecutor._executive_summary("https://example.test/", ["a", "b"],
                                             [{"id": "fw"}], findings, [{"title": "Clear value"}])

    assert "The one thing to change: On screen and never looked at" in summary
    # F1: the judgement leads; "what works" is named too when there is one.
    assert summary.index("The one thing to change") < summary.index("3 usability issues")
    assert "What works: Clear value." in summary
    # The two classes a reader would not know to look for are called out by name.
    assert "not legible once these users' eyesight is applied" in summary
    assert "never looked at -- a prominence problem" in summary
    assert "3 usability issues" in summary and "2 of them high-severity" in summary


def test_the_summary_of_a_clean_run_does_not_invent_a_worst_finding():
    summary = JobExecutor._executive_summary("https://example.test/", ["a"], [{"id": "fw"}],
                                             [{"title": "No pain points detected"}], [])
    assert "The one thing to change" not in summary
    assert "0 usability issues" in summary


def test_a_run_from_before_the_degraded_capture_existed_still_reports():
    """Old runs carry no seenImage. The finding is still worth making; it just
    falls back to a run screenshot like every other finding."""
    finding = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[FAILS_WCAG])])[0]
    assert finding["evidenceScreenshot"] is None
    assert finding["evidenceIsAsTheySawIt"] is False


def test_a_report_quotes_the_person_not_the_models_working():
    """A live report published this as Friedrich Wolf's evidence for its only
    finding: "We have completed the tasks: 1. ... We read the homepage ... However,
    the snapshot does not show any price numbers. So we can say the page does not
    tell you the exact cost." That is the model arguing with itself about refs and
    evidence capture, in the first person plural. The persona director records the
    person's own account -- what they expected, what arrived, how it left them --
    and it was ignored in favour of the completion tokens."""
    journey = {
        "profileId": "persona_1",
        "reasoning": [{"elapsedMs": 4687, "model": "some-router",
                       "text": "We need screenshot evidence. We'll click the Pricing link (ref=e6). "
                               "However, the snapshot does not show any price numbers."}],
        "timeline": [
            {"type": "persona.expectation", "elapsedMs": 2400,
             "data": {"expectation": "The Pricing link should take me to the numbers."}},
            {"type": "persona.reflection", "elapsedMs": 4700,
             "data": {"matched": False, "observed": "A pricing page with plan names.",
                      "gap": "The page loaded, but the prices I came for are not on it."}},
            {"type": "persona.affect", "elapsedMs": 4800,
             "data": {"feeling": "mildly irritated and unsure where to look next"}},
            {"type": "agent.message.end", "elapsedMs": 5000, "data": {"text": "Assistant working."}},
        ],
    }

    thoughts = JobExecutor._persona_thoughts(journey)
    quoted = [item["text"] for item in thoughts if item["kind"] == "reasoning"]

    assert "The page loaded, but the prices I came for are not on it." in quoted
    assert "The Pricing link should take me to the numbers." in quoted
    assert "mildly irritated and unsure where to look next" in quoted
    # The machinery is not the person, and must not be published as them.
    assert not any("ref=e6" in text for text in quoted)
    assert not any(text.startswith("We ") for text in quoted)
    assert "Assistant working." not in quoted
    # Every quote says which event it came from, so nothing presents an expectation
    # as a reflection.
    assert {item["source"] for item in thoughts if item["kind"] == "reasoning"} == {
        "persona.expectation", "persona.reflection", "persona.affect"}


def test_an_agent_run_still_quotes_the_models_reasoning():
    """The persona voice is a preference, not a requirement. A run driven by the
    competent-agent director records no persona.* events at all, and its completion
    tokens remain the only account it has -- dropping them there would leave every
    finding from such a run with no evidence."""
    journey = {
        "profileId": "persona_1",
        "reasoning": [{"elapsedMs": 900, "model": "some-router",
                       "text": "The pricing page shows plan names but no amounts."}],
        "timeline": [{"type": "browser.click", "summary": "Clicked 'Pricing'", "elapsedMs": 800}],
    }

    thoughts = JobExecutor._persona_thoughts(journey)

    assert [item["text"] for item in thoughts if item["kind"] == "reasoning"] == [
        "The pricing page shows plan names but no amounts."]
    assert {item["source"] for item in thoughts if item["kind"] == "reasoning"} == {"model.reasoning"}


def test_an_instrument_that_stopped_answering_is_reported_not_inferred():
    """A live report came back with `run_diagnostics: []` for a run in which the
    entire perception path never executed. The mechanism was not broken: it filters
    *findings* by their wording, and an instrument that stops answering produces no
    finding to filter. The reader was left unable to tell "this page has no eyesight
    problems" from "nothing looked"."""
    from apps.api.executor import _instrument_diagnostics

    diagnostics = _instrument_diagnostics([{
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [
            {"type": "persona.perception_unavailable", "elapsedMs": 3000,
             "data": {"reason": "perception service returned HTTP 503", "sinceStep": 2}},
            {"type": "persona.adherence_unavailable", "elapsedMs": 4000,
             "data": {"reason": "two consecutive judge failures", "sinceStep": 3}},
            {"type": "browser.click", "summary": "Clicked 'Pricing'", "elapsedMs": 5000},
        ]}])

    titles = [item["title"] for item in diagnostics]
    assert "The run stopped seeing the page through this person's eyes" in titles
    assert "Nothing checked whether the actions sounded like this person" in titles
    # The reason the service gave is the actionable part, so it is carried through.
    assert any("HTTP 503" in item["summary"] for item in diagnostics)
    # An absence of findings after the instrument died must not read as a clean page.
    assert any("not evidence that the page has none" in item["summary"] for item in diagnostics)
    # A diagnostic is about the harness, never numbered among the product's issues.
    assert {item["category"] for item in diagnostics} == {"harness"}
    assert all(item["runId"] == "run_1" for item in diagnostics)
    # A healthy run reports nothing.
    assert _instrument_diagnostics([{"runId": "run_2", "timeline": [
        {"type": "persona.reflection", "data": {"gap": "no prices"}}]}]) == []


def test_a_plural_and_its_singular_stem_to_the_same_word():
    """The stemmer's whole job, and it got this pair wrong. "prices" is six letters,
    so it cleared `len > len("es") + 3` and stemmed to "pric"; "price" is five,
    cleared nothing, and stayed "price". A live report discarded the one quote that
    was genuinely about its finding -- "No price was visible anywhere." under a
    finding about text reading "Prices exclude VAT" -- because the two shared no
    stem."""
    from apps.api.executor import _stem

    for singular, plural in [("price", "prices"), ("control", "controls"), ("link", "links"),
                             ("button", "buttons"), ("box", "boxes"), ("class", "classes"),
                             ("address", "addresses"), ("pass", "passes"),
                             ("policy", "policies"), ("heading", "headings")]:
        assert _stem(singular) == _stem(plural), f"{singular}/{plural} must compare equal"
    # A word that is not a plural keeps its own stem: "access" and "is" end in s.
    assert _stem("access") == "access"
    assert _stem("is") == "is"


def test_a_perception_finding_only_quotes_what_the_persona_said_about_it():
    """A live report put "Clicking 'How it works' did not navigate to a detailed
    service explanation" and "No price or selection indicator appeared after
    clicking the annual button" under a contrast finding about the site's own logo.
    An irrelevant quote under a finding does not read as unrelated -- it reads as
    evidence."""
    findings = JobExecutor._pain_points_from_perception([{
        "runId": "run_1", "profileId": "persona_1",
        "simulationProfile": {"persona": {"name": "Friedrich Wolf"}},
        "timeline": [
            {"type": "persona.perception", "data": {
                "eyes": RARE_EYES,
                "scan": {"pattern": "spotted", "fixationBudget": 6, "why": ["in a hurry"]},
                "counts": {"elements": 15, "fixated": 6},
                "notPerceived": [FAILS_WCAG], "notLookedAt": [], "missedWhatTheyCameFor": []}},
            {"type": "persona.reflection", "data": {
                "matched": "no", "gap": "Clicking 'How it works' did not navigate anywhere new."}},
            {"type": "persona.reflection", "data": {
                "matched": "no", "gap": "No price was visible anywhere."}},
        ]}])

    assert len(findings) == 1
    quotes = [item["quote"] for item in findings[0]["personaEvidence"]]
    assert quotes == ["No price was visible anywhere."], (
        "only the quote about this element's text may be published under it")
    # And it is said by somebody: personaName was never set, so the presentation
    # rendered every persona quote as "Synthetic user".
    assert findings[0]["personaEvidence"][0]["personaName"] == "Friedrich Wolf"


def test_a_report_says_so_when_a_capture_it_cites_was_never_kept():
    """Evidence a reader cannot resolve from its citation is worse than no
    citation: it reads as corroborated. A live report cited "snapshot:
    003-snapshot.txt" for its only finding and no artifact in the session was
    called that."""
    from apps.api.executor import cited_captures, unresolvable_citations

    report = {
        "critical_pain_points": [
            {"title": "Spinner never resolves",
             "evidence": f"screenshot: {JobExecutor._download_name('browser.screenshot', 'job_a', '003')}"},
            {"title": "Low-contrast label",
             "evidence": f"snapshot: {JobExecutor._download_name('browser.snapshot', 'job_a', '004-snapshot')}"},
        ],
        "elements_to_preserve": [{"description": "nothing cited here"}],
    }
    kept = {JobExecutor._download_name("browser.screenshot", "job_a", "003")}

    # Citations are read off the rendered prose, wherever in the report it sits.
    assert cited_captures(report) == {
        JobExecutor._download_name("browser.screenshot", "job_a", "003"),
        JobExecutor._download_name("browser.snapshot", "job_a", "004-snapshot"),
    }
    missing = unresolvable_citations(report, kept)
    assert missing == [JobExecutor._download_name("browser.snapshot", "job_a", "004-snapshot")]
    # Nothing is flagged when everything cited was kept.
    assert unresolvable_citations(report, cited_captures(report)) == []
    # A report citing nothing has nothing to resolve.
    assert unresolvable_citations({"executive_summary": "All clear."}, set()) == []


def test_a_contrast_fix_names_the_change_rather_than_the_guideline():
    """"Raise the contrast to at least 4.5:1" restates the minimum the finding has
    already quoted. It is not a fix. The measurement knows both luminances and the
    WCAG definition gives the target exactly, so the report can say how far the
    darker side has to move."""
    from apps.api.executor import contrast_fix

    fix = contrast_fix({"inkLuminance": 0.45, "paperLuminance": 1.0,
                        "needsLuminanceBelow": 0.1833})

    assert "0.45" in fix and "0.1833" in fix
    assert "#767676" in fix, "and offer a colour that actually gets there"
    # Offered as a worked example, not as the colour the page must use: many
    # colours share one luminance.
    assert "any colour at or below that luminance does" in fix


def test_a_suggested_colour_always_clears_the_bar_it_was_derived_from():
    """Rounding to nearest returned #777777 for a target of 0.1833 -- one step
    above it, at 0.1845 -- so the colour offered as the fix would itself have
    failed the check it was calculated to pass."""
    from apps.api.executor import _grey_at_luminance

    def luminance(hex_colour: str) -> float:
        channel = int(hex_colour[1:3], 16) / 255
        channel = channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        return channel

    for target in (0.1833, 0.3, 0.05, 0.5, 1.0, 0.0):
        suggested = _grey_at_luminance(target)
        assert luminance(suggested) <= target + 1e-9, (
            f"{suggested} is above the {target} it was derived from, so it fails too")
    # The canonical grey for 4.5:1 on white, as a sanity check against the spec.
    assert _grey_at_luminance(0.1833) == "#767676"


def test_a_background_no_text_colour_can_survive_is_said_as_such():
    """When black itself would fall short, "darken the text" is advice that cannot
    be taken."""
    from apps.api.executor import contrast_fix

    fix = contrast_fix({"inkLuminance": 0.02, "paperLuminance": 0.15,
                        "needsLuminanceBelow": None})

    assert "black text would still fall short" in fix
    assert "background is what has to change" in fix


def test_pixels_that_were_never_drawn_are_not_a_contrast_ratio():
    """A live report filed "Fails WCAG AA contrast: 'Sourcing' -- 1.01:1" against a
    486x21 region that was blank page below a chat bubble: an element of the site's
    animated mock-up conversation that had not painted yet. The same element was
    reported 200px higher one step later, which is what an animation looks like
    from here.

    The DOM saying there is text and the capture having no ink at all is the two
    sources disagreeing about what exists. Reporting it as a measured ratio states
    a number about pixels that are not there."""
    blank = {"selector": "span@316,533", "role": "span", "name": "Sourcing",
             "box": {"x": 316, "y": 533, "width": 486, "height": 21},
             "reason": "the region and everything around it are the same flat colour",
             "internalContrast": 0.0078, "edgeContrast": 0.0099, "ink": 0.0,
             "nothingDrawn": True,
             "contrast": {"ratio": 1.01, "required": 4.5, "passes": False,
                          "measured": "text against its own background"}}

    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[blank], eyes=RARE_EYES)])

    assert len(findings) == 1
    finding = findings[0]
    assert "Fails WCAG AA contrast" not in finding["title"]
    assert finding["title"] == 'Declared but not drawn: "Sourcing"'
    # No ratio is claimed, because there are no pixels to measure.
    assert finding["contrastRatio"] is None and finding["wcagPasses"] is None
    assert "1.01" not in finding["summary"]
    # And it is said quietly: mid-animation is the likelier explanation than a defect.
    assert finding["severity"] == "info"
    assert "still animating" in finding["summary"]
    # Still worth saying: text a page declares and never draws is real.
    assert "never sees" in finding["recommendation"]


def test_faint_but_real_ink_is_still_a_contrast_finding():
    """The guard must not swallow the thing it sits next to. Text that is genuinely
    drawn and genuinely too pale is exactly what the WCAG finding is for."""
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[FAILS_WCAG], eyes=RARE_EYES)])

    assert len(findings) == 1
    assert "Fails WCAG AA contrast" in findings[0]["title"]
    assert findings[0]["contrastRatio"] == 2.85


# FND-1 (docs/parallel-development-spec.md): a real live run measured "Fails WCAG
# AA contrast: 'Video' -- 1.13:1" against a nav-bar icon whose capture was blank
# page over a faint background pattern -- internal contrast 0.6941 (real variance,
# so nothingDrawn's own internal<0.02 gate does not fire) with ink 0.0015, well
# under legibility()'s own 0.005 bar for counting as text. Reproduced here from
# last_runs/artifacts/journey_log__*.json's actual recorded values.
UNVERIFIED_LOW_RATIO = {"selector": "e138", "role": "link", "name": "Video",
                        "box": {"x": 43, "y": 361, "width": 1212, "height": 36},
                        "reason": "nothing in the region stands out from its background",
                        "internalContrast": 0.6941, "edgeContrast": 0.0091, "ink": 0.0015,
                        "contrast": {"ratio": 1.13, "required": 3, "passes": False,
                                     "measured": "text against its own background"}}


def test_a_low_ratio_with_no_confirmed_ink_is_not_a_contrast_claim():
    """The false positive FND-1 exists to close: nothingDrawn's dual gate
    (internal<0.02 AND edge<0.02) does not catch a faint background pattern
    that carries real internal variance but no actual ink, and a ratio this
    close to 1.0 is not itself evidence that any ink was found."""
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[UNVERIFIED_LOW_RATIO], eyes=RARE_EYES)])

    assert len(findings) == 1
    finding = findings[0]
    assert "Fails WCAG AA contrast" not in finding["title"]
    assert finding["title"] == 'Contrast measured, ink not confirmed: "Video"'
    assert finding["source"] == "perception.unverifiedContrast"
    # No claim is made, the same rule nothingDrawn's own branch follows.
    assert finding["contrastRatio"] is None and finding["wcagPasses"] is None
    assert finding["severity"] == "info"
    # The real numbers still reach the reader, in the evidence line, not as a
    # WCAG claim.
    assert "1.13" in finding["evidence"] and "0.0015" in finding["evidence"]
    # No leaked temporary field used only for _fold_unverified_contrast.
    assert not any(key.startswith("_") for key in finding)


def test_a_low_ratio_right_at_the_ink_floor_still_files_as_a_contrast_defect():
    """The boundary the guard must not swallow: ink at or above 0.005 -- the
    same bar legibility() uses to call something text -- is confirmed ink,
    however low the ratio."""
    at_floor = {**UNVERIFIED_LOW_RATIO, "selector": "e_floor", "ink": 0.005}
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[at_floor], eyes=RARE_EYES)])

    assert len(findings) == 1
    assert "Fails WCAG AA contrast" in findings[0]["title"]
    assert findings[0]["contrastRatio"] == 1.13


def test_a_low_confirmed_ink_ratio_right_at_1_2_still_files_as_a_contrast_defect():
    """The other boundary: 1.2:1 itself is not "unverified" territory -- only
    strictly below it."""
    at_bound = {**UNVERIFIED_LOW_RATIO, "selector": "e_bound", "ink": 0.0,
                "contrast": {**UNVERIFIED_LOW_RATIO["contrast"], "ratio": 1.2}}
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=[at_bound], eyes=RARE_EYES)])

    assert len(findings) == 1
    assert "Fails WCAG AA contrast" in findings[0]["title"]


def test_several_unverified_contrast_regions_are_grouped_with_instances():
    """FND-1's other half: several elements with this shape are one
    observation about the capture, not one high-severity finding each --
    the exact live count from last_runs/ (four language-switcher entries and
    a nav icon)."""
    regions = [
        {**UNVERIFIED_LOW_RATIO, "selector": f"e_{i}", "name": name,
         "contrast": {**UNVERIFIED_LOW_RATIO["contrast"], "ratio": ratio}}
        for i, (name, ratio) in enumerate([
            ("Video", 1.13), ("Italiano", 1.03), ("RUРусский", 1.03),
            ("ESEspañol", 1.04),
        ])
    ]
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=regions, eyes=RARE_EYES)])

    grouped = [f for f in findings if f["source"] == "perception.unverifiedContrast"]
    assert len(grouped) == 1
    finding = grouped[0]
    assert finding["title"] == "4 regions measured a low contrast ratio with unconfirmed ink"
    assert len(finding["instances"]) == 4
    assert {i["name"] for i in finding["instances"]} == {
        "Video", "Italiano", "RUРусский", "ESEspañol"
    }
    assert {i["measuredRatio"] for i in finding["instances"]} == {1.13, 1.03, 1.04}
    assert not any(key.startswith("_") for key in finding)
    assert not any("Fails WCAG AA contrast" in f["title"] for f in findings)


def test_a_couple_of_unverified_contrast_regions_are_named_individually():
    """Below the folding threshold, each stays its own finding -- the same
    "worth naming individually" cutoff _fold_undrawn already uses, applied
    to this class with its own constant."""
    regions = [
        {**UNVERIFIED_LOW_RATIO, "selector": f"e_{i}", "name": f"Region {i}"}
        for i in range(2)
    ]
    findings = JobExecutor._pain_points_from_perception(
        [_perception_journey(unreadable=regions, eyes=RARE_EYES)])

    grouped = [f for f in findings if f["source"] == "perception.unverifiedContrast"]
    assert len(grouped) == 2
    assert all("instances" not in f for f in grouped)
    assert all(not any(key.startswith("_") for key in f) for f in grouped)


# SEC-1 (docs/parallel-development-spec.md): a run that hits its own step
# budget (journeytest.js's stepBudget(), min(40, max(12, tasks*8)) -- 12 for
# one task) ends "inconclusive" with tasks-completed:not-met and a
# persona-stopped blocker, and a live run filed both as high/critical
# usability findings with run_diagnostics empty.
def _budget_journey(run_id="run_1", num_actions=12, status="inconclusive",
                    criterion_result="not-met", blocker_id="persona-stopped"):
    return {
        "runId": run_id, "profileId": "persona_1",
        "timeline": [{"type": "persona.expectation",
                      "data": {"expectation": "x", "action": {"type": "CLICK", "target": f"e{i}"}}}
                     for i in range(num_actions)],
        "verdict": {
            "status": status,
            "criteria": [{"id": "tasks-completed", "result": criterion_result,
                         "explanation": f"Still going after {num_actions} actions without finishing."}],
            "blockers": [{"id": blocker_id, "severity": "minor", "category": "blocker",
                         "title": "The visitor did not get there",
                         "description": f"Still going after {num_actions} actions without finishing."}],
        },
    }


def _assembled(journeys, tasks=("Understand the product",)):
    return JobExecutor.assemble_report(
        url="https://example.com", tasks=list(tasks),
        personas=[{"id": "persona_1", "persona": {"name": "Alex"}}],
        persona_artifacts=[], journeys=journeys, worker_configured=True, job_id="job_x",
        vision=[], redesign=[])


def test_a_budget_hit_criteria_finding_is_a_run_diagnostic_not_a_pain_point():
    report = _assembled([_budget_journey()])
    titles = {f["title"] for f in report["critical_pain_points"]}
    diagnostic_titles = {f["title"] for f in report["run_diagnostics"]}
    assert "Users could not finish the tasks they came to do" not in titles
    assert "Users could not finish the tasks they came to do" in diagnostic_titles


def test_a_budget_hit_blocker_finding_is_a_run_diagnostic_too():
    """The same run, reported twice by JourneyTest's own verdict -- once as
    a pass criterion, once as a blocker with id "persona-stopped". Both are
    the same harness limit and both must be excluded, or the second title
    ("The visitor did not get there") survives as a usability finding under
    a different name."""
    report = _assembled([_budget_journey()])
    titles = {f["title"] for f in report["critical_pain_points"]}
    diagnostic_titles = {f["title"] for f in report["run_diagnostics"]}
    assert "The visitor did not get there" not in titles
    assert "The visitor did not get there" in diagnostic_titles


def test_a_genuine_give_up_below_budget_is_a_real_finding():
    """A persona who decides to leave partway through -- ending the run
    "failed", well under the budget -- produced a genuine finding
    (docs/next-cycle-worksheet.md's own "the failed run produced a real
    finding"). SEC-1 must not sweep that up too. The two titles merge into
    one here (identical "Still going after 3 actions..." summaries clear
    _merge_similar_findings' own, unrelated threshold) -- pre-existing
    behaviour this test pins as unaffected by SEC-1, not a SEC-1 outcome:
    "The visitor did not get there" survives in mergedFrom, and neither
    title is a run diagnostic."""
    report = _assembled([_budget_journey(num_actions=3, status="failed")])
    titles = {f["title"] for f in report["critical_pain_points"]}
    assert titles == {"Users could not finish the tasks they came to do"}
    merged_from = {
        item for f in report["critical_pain_points"] for item in (f.get("mergedFrom") or [])
    }
    assert "The visitor did not get there" in merged_from
    assert report["run_diagnostics"] == []


def test_a_blocked_criterion_is_not_swept_up_as_budget_limited():
    """"blocked" (the run could not even assess the criterion) is a
    different failure from running out of steps, even on an inconclusive
    run at the budget -- scoped narrowly on purpose, matching
    scripts/cycle/measure.py's own check."""
    report = _assembled([_budget_journey(criterion_result="blocked")])
    titles = {f["title"] for f in report["critical_pain_points"]}
    assert "The journey was blocked before the tasks could be judged" in titles


def test_a_run_well_under_budget_that_is_still_inconclusive_is_a_real_finding():
    """Inconclusive alone is not the signal -- only inconclusive *at* the
    budget is. A run that stopped early for some other reason and never
    reached a verdict is a real, if unusual, thing to report."""
    report = _assembled([_budget_journey(num_actions=3, status="inconclusive")])
    titles = {f["title"] for f in report["critical_pain_points"]}
    assert "Users could not finish the tasks they came to do" in titles
    assert report["run_diagnostics"] == []


def test_blocker_id_is_not_threaded_onto_other_buckets():
    """blockerId is meaningful only for the blockers bucket; a uxFinding or
    suggestedImprovement item must not carry a stray None-valued field that
    looks like it means something."""
    journey = {
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [],
        "verdict": {"status": "completed",
                    "uxFindings": [{"title": "Small tap target", "description": "d",
                                    "severity": "medium", "category": "usability"}]},
    }
    findings = JobExecutor._pain_points_from_journeys([journey])
    assert len(findings) == 1
    assert "blockerId" not in findings[0]


# SEC-5 (spec.md §30.5, docs/parallel-development-spec.md): videoTimestampMs
# and step, joined from data every run already records -- a live run's own
# capture events, not a new measurement.
def _screenshot_event(path, video_ms, kind="browser.screenshot"):
    data = {"path": path} if kind == "browser.screenshot" else {"seenImage": path}
    return {"type": kind, "videoTimeMs": video_ms, "data": data}


def test_video_timestamps_come_from_the_matching_capture_event():
    journey = {
        "runId": "run_1",
        "timeline": [
            _screenshot_event("/shots/001-arrived.png", 8198),
            _screenshot_event("/shots/001-as-they-saw-it.jpg", 10355, kind="persona.perception"),
        ],
    }
    table = JobExecutor._screenshot_video_timestamps([journey])
    assert table["run_1"] == {
        "/shots/001-arrived.png": 8198,
        "/shots/001-as-they-saw-it.jpg": 10355,
    }


def test_video_timestamps_keep_the_first_sighting_of_a_reread_screenshot():
    """A persona can look at the same capture twice (re-reading it); the
    moment it was actually taken, not the last time it was glanced at
    again, is what a reader wants to find in the recording."""
    journey = {
        "runId": "run_1",
        "timeline": [
            _screenshot_event("/shots/002-page-1.png", 24998, kind="persona.perception"),
            _screenshot_event("/shots/002-page-1.png", 40000, kind="persona.perception"),
        ],
    }
    table = JobExecutor._screenshot_video_timestamps([journey])
    assert table["run_1"]["/shots/002-page-1.png"] == 24998


def test_attach_video_timestamps_matches_by_run_and_either_screenshot_field():
    journeys = [
        {"runId": "run_1", "timeline": [_screenshot_event("/shots/001-a.png", 100)]},
        {"runId": "run_2", "timeline": [_screenshot_event("/shots/001-a.png", 999)]},
    ]
    findings = [
        {"runId": "run_1", "evidenceScreenshot": "/shots/001-a.png"},
        {"runId": "run_2", "screenshotRef": "/shots/001-a.png"},  # same path, other run
        {"runId": "run_1", "evidenceScreenshot": "/shots/missing.png"},
        {"runId": "run_1"},
    ]
    JobExecutor._attach_video_timestamps(findings, journeys)
    assert findings[0]["videoTimestampMs"] == 100
    # Same path, but run_2's own table -- never run_1's value by accident.
    assert findings[1]["videoTimestampMs"] == 999
    assert "videoTimestampMs" not in findings[2]
    assert "videoTimestampMs" not in findings[3]


def test_step_and_video_timestamp_reach_a_real_finding_end_to_end():
    """The full join, through assemble_report, on paths shaped like a real
    run's own capture filenames (not the renamed local files a downloaded
    snapshot uses -- see replay_report.py's module docstring, category 6,
    for why that distinction matters for step specifically)."""
    journey = {
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [
            _screenshot_event("/shots/001-as-they-saw-it.jpg", 10355, kind="persona.perception"),
            {"type": "persona.perception", "videoTimeMs": 10355, "data": {
                "seenImage": "/shots/001-as-they-saw-it.jpg",
                "notPerceived": [{**FAILS_WCAG, "selector": "p.step1"}],
            }},
        ],
        "verdict": {"status": "completed"},
    }
    report = _assembled([journey], tasks=["t"])
    finding = next(f for f in report["critical_pain_points"] if f["title"].startswith("Fails WCAG"))
    assert finding["step"] == 1
    assert finding["videoTimestampMs"] == 10355


# SEC-2 (spec.md §30.4, docs/parallel-development-spec.md): the experience
# trajectory -- the one report-contract section that was missing outright,
# built from data every persona.affect event already carries.
def _affect_event(step, frustration, confusion, trust, fatigue, coping="retry",
                  cognitive=None, physical=None, elapsed_ms=1000, video_ms=900,
                  consecutive_failures=0, abandoned=False):
    return {"type": "persona.affect", "elapsedMs": elapsed_ms, "videoTimeMs": video_ms,
            "data": {"state": {"step": step, "frustration": frustration, "confusion": confusion,
                               "trust": trust, "fatigue": fatigue, "cognitiveEffort": cognitive,
                               "physicalEffort": physical, "consecutiveFailures": consecutive_failures,
                               "abandoned": abandoned},
                     "coping": {"type": coping}}}


def test_experience_trajectory_reads_the_affect_state_directly():
    journey = {"runId": "run_1", "profileId": "persona_1", "timeline": [
        _affect_event(1, 0.13, 0.21, 0.98, 0.06, cognitive=0.07, physical=0.0),
        _affect_event(2, 1.00, 1.00, 0.81, 0.55, coping="explore", cognitive=0.54, physical=0.02),
    ]}
    trajectories = JobExecutor._experience_trajectory([journey], findings=[], persona_names={"persona_1": "Alex"})

    assert len(trajectories) == 1
    t = trajectories[0]
    assert t["runId"] == "run_1" and t["personaId"] == "persona_1" and t["personaName"] == "Alex"
    assert len(t["points"]) == 2
    first, last = t["points"]
    assert (first["frustration"], first["confusion"], first["trust"], first["fatigue"]) == (0.13, 0.21, 0.98, 0.06)
    assert first["effort"] == 0.07  # max(cognitive, physical)
    assert last["coping"] == "explore" and last["abandoned"] is False


def test_experience_trajectory_effort_is_the_max_of_cognitive_and_physical():
    journey = {"runId": "run_1", "profileId": "p1", "timeline": [
        _affect_event(1, 0.1, 0.1, 0.9, 0.1, cognitive=0.2, physical=0.6),
    ]}
    points = JobExecutor._experience_trajectory([journey], findings=[], persona_names={})[0]["points"]
    assert points[0]["effort"] == 0.6
    assert points[0]["cognitiveEffort"] == 0.2 and points[0]["physicalEffort"] == 0.6


def test_experience_trajectory_effort_is_none_when_neither_is_recorded():
    journey = {"runId": "run_1", "profileId": "p1", "timeline": [_affect_event(1, 0.1, 0.1, 0.9, 0.1)]}
    points = JobExecutor._experience_trajectory([journey], findings=[], persona_names={})[0]["points"]
    assert points[0]["effort"] is None


def test_experience_trajectory_marks_findings_by_matching_step():
    journey = {"runId": "run_1", "profileId": "p1", "timeline": [
        _affect_event(1, 0.1, 0.1, 0.9, 0.1),
        _affect_event(2, 0.2, 0.2, 0.8, 0.2),
    ]}
    findings = [{"step": 2, "title": "Fails WCAG AA contrast: X"}, {"step": None, "title": "A blocker, no step"}]
    points = JobExecutor._experience_trajectory([journey], findings=findings, persona_names={})[0]["points"]
    assert points[0]["findingTitles"] == []
    assert points[1]["findingTitles"] == ["Fails WCAG AA contrast: X"]


def test_experience_trajectory_omits_a_run_with_no_affect_events():
    journey = {"runId": "run_1", "profileId": "p1", "timeline": [
        {"type": "persona.expectation", "data": {}},
    ]}
    assert JobExecutor._experience_trajectory([journey], findings=[], persona_names={}) == []


def test_experience_trajectory_reaches_a_real_run_end_to_end():
    """The full field, through assemble_report, cross-referencing a real
    finding's own SEC-5 step -- the join this section exists to make."""
    journey = {
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [
            {"type": "persona.perception", "videoTimeMs": 10355, "data": {
                "seenImage": "/shots/001-as-they-saw-it.jpg",
                "notPerceived": [{**FAILS_WCAG, "selector": "p.step1"}]}},
            _affect_event(1, 0.5, 0.4, 0.9, 0.2),
        ],
        "verdict": {"status": "completed"},
    }
    report = _assembled([journey], tasks=["t"])
    assert len(report["experience_trajectory"]) == 1
    point = report["experience_trajectory"][0]["points"][0]
    assert point["frustration"] == 0.5
    assert "Fails WCAG AA contrast" in point["findingTitles"][0]


def test_a_blocked_journey_says_where_the_patience_went():
    """A live report's most serious finding was "The journey was blocked before
    completion", severity critical, recommendation None. A critical finding with no
    fix is one a reader cannot act on -- and the run knew exactly what had happened:
    the persona clicked the same pricing toggle three separate times expecting a
    price, was told each time that nothing appeared, and left."""
    journey = {
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [
            {"type": "persona.expectation", "data": {
                "expectation": "Clicking the 'Annual · save 17%' button will reveal the price.",
                "action": {"type": "CLICK", "target": "e17"}}},
            {"type": "persona.reflection", "data": {
                "matched": "no", "gap": "Click did not reveal any annual price information."}},
            {"type": "persona.expectation", "data": {
                "expectation": "Scrolling will show the plan details.",
                "action": {"type": "SCROLL", "content": "down"}}},
            {"type": "persona.reflection", "data": {"matched": "yes", "gap": ""}},
            {"type": "persona.expectation", "data": {
                "expectation": "Clicking the 'Annual · save 17%' button will reveal the price.",
                "action": {"type": "CLICK", "target": "e17"}}},
            {"type": "persona.reflection", "data": {
                "matched": "no", "gap": "The expected price information or modal did not appear."}},
        ],
    }

    said = JobExecutor._what_stopped_them(journey)

    # Named the way a person would, not by the ref the agent used: nobody reading a
    # report knows what e17 is, and the persona said what it was.
    assert '"Annual · save 17%"' in said
    assert "e17" not in said
    assert "3 times" not in said and "2 times" in said
    assert "The expected price information or modal did not appear" in said
    # The quote's own full stop is not doubled.
    assert 'appear".' in said and 'appear.".' not in said
    # An action that worked is not the cause.
    assert "scroll" not in said.lower()
    # A control is somewhere to go and look.
    assert "Start there" in said


def test_what_stopped_them_reads_right_for_something_that_is_not_a_control():
    """"Start there -- that is where this visitor's patience went" points at a
    control. It does not parse for a scroll, where what the run shows is somebody
    hunting and not finding. A SCROLL also carries "down" as its target, which is
    not a thing on the page to go and look at, so the wording is chosen from the
    verb rather than from whether a target string happens to be present."""
    runs = [_expectation_run("run_1", "friedrich", [
        ("Scrolling down will reveal the prices.",
         {"type": "SCROLL", "content": "down"}, "no", "No prices appeared.", 0.20),
        ("Scrolling down will reveal the prices.",
         {"type": "SCROLL", "content": "down"}, "no", "Still no prices.", 0.40)])]

    said = JobExecutor._what_stopped_them(runs[0])

    assert "Start there" not in said
    assert "scroll their way to it 2 times" in said
    assert "not where they kept looking for it" in said
    # And never "the down control".
    assert "down" not in said.split("expected")[0]


def test_a_journey_that_did_not_repeat_itself_gets_no_invented_cause():
    """There is no honest single cause to name when nothing was tried twice, and a
    guess is worse than the silence it replaces."""
    journey = {"runId": "run_1", "timeline": [
        {"type": "persona.expectation", "data": {"expectation": "A price.",
                                                 "action": {"type": "CLICK", "target": "e1"}}},
        {"type": "persona.reflection", "data": {"matched": "no", "gap": "No price."}},
        {"type": "persona.expectation", "data": {"expectation": "A plan.",
                                                 "action": {"type": "CLICK", "target": "e2"}}},
        {"type": "persona.reflection", "data": {"matched": "no", "gap": "No plan."}},
    ]}

    assert JobExecutor._what_stopped_them(journey) == ""
    assert JobExecutor._what_stopped_them({"timeline": []}) == ""


def _expectation_run(run_id, persona, steps):
    """A run as the persona director records it: expectation, reflection, affect."""
    timeline = []
    for expectation, action, matched, gap, frustration in steps:
        timeline.append({"type": "persona.expectation",
                         "data": {"expectation": expectation, "action": action}})
        timeline.append({"type": "persona.reflection", "data": {"matched": matched, "gap": gap}})
        timeline.append({"type": "persona.affect", "data": {"state": {"frustration": frustration}}})
    return {"runId": run_id, "profileId": persona,
            "simulationProfile": {"persona": {"name": persona.title()}}, "timeline": timeline}


def test_a_control_that_promised_more_than_it_did_becomes_a_finding():
    """Three consecutive live runs against the same page each recorded that
    clicking "How it works" did not navigate anywhere and that the "Annual - save
    17%" toggle showed no price -- one of them abandoning the journey over it --
    and all three reports said nothing about either. One said "No pain points
    detected" over a run that ended at 0.49 frustration and 0.52 confusion.

    A reflection that comes back `matched: "no"` is a first-hand, falsifiable
    observation of a control that promised something and did not deliver, which is
    the most common real usability defect and one no check against the DOM can
    find."""
    runs = [
        _expectation_run("run_1", "friedrich", [
            ("Clicking the 'How it works' link will explain the product.",
             {"type": "CLICK", "target": "e3"}, "no",
             "Click did not navigate anywhere; the landing page remained.", 0.20),
            ("Scrolling will reveal the prices.",
             {"type": "SCROLL", "content": "down"}, "yes", "", 0.20),
        ]),
        _expectation_run("run_2", "sophie", [
            ("Clicking the 'How it works' link will explain the product.",
             {"type": "CLICK", "target": "e6"}, "no",
             "Nothing happened when I clicked it.", 0.24),
        ]),
    ]

    findings = JobExecutor._pain_points_from_expectations(runs)

    assert len(findings) == 1, "one control, one finding, however many runs hit it"
    finding = findings[0]
    assert finding["title"] == "Promised more than it did: How it works"
    # Two different people losing patience over one control is the page, not them.
    assert finding["severity"] == "high"
    assert finding["affectedPersonas"] == 2
    # Priced by what it actually cost, read from the run's own affect rather than
    # assigned from a table.
    assert "0.44" in finding["evidence"] or "0.44" in finding["summary"]
    # Both halves, in the persona's own words: what they expected before touching
    # it, and what arrived.
    assert "will explain the product" in finding["summary"]
    assert "Nothing happened when I clicked it" in finding["summary"]
    # An expectation that was met is not a finding.
    assert "Scrolling" not in finding["summary"]


def test_only_a_control_can_promise_something():
    """A READ that returns something unexpected is about what the persona could
    take in, which the perception findings measure properly. A SCROLL that does not
    reveal what was hoped for is a guess about a page, not a promise it made.
    Reporting those here files "the paragraph at 321,417 promised more than it
    did", which is not a sentence about the product."""
    runs = [_expectation_run("run_1", "friedrich", [
        ("I will see the full paragraph describing what this does.",
         {"type": "READ", "target": "p@321,417"}, "no", "The paragraph was not there.", 0.20),
        ("Scrolling down will reveal pricing.",
         {"type": "SCROLL", "content": "down"}, "no", "No pricing appeared.", 0.40),
    ])]

    assert JobExecutor._pain_points_from_expectations(runs) == []


def test_one_control_named_two_ways_is_one_finding():
    """One persona quotes "Annual - save 17%" and the next writes "the Annual
    button", and the page has one toggle. Left split, the report says a control was
    hit once when it was hit twice, and prices each half at half the patience it
    actually cost -- which is what severity is read from."""
    runs = [
        _expectation_run("run_1", "friedrich", [
            ("Clicking the 'Annual · save 17%' button will show the price.",
             {"type": "CLICK", "target": "e17"}, "no", "No price appeared.", 0.28)]),
        _expectation_run("run_2", "sophie", [
            ("Clicking the Annual button will display the annual price.",
             {"type": "CLICK", "target": "e17"}, "no", "Only the button remains.", 0.21)]),
    ]

    findings = JobExecutor._pain_points_from_expectations(runs)

    assert len(findings) == 1
    # The specific label survives -- it is the one a reader can find on the page.
    assert findings[0]["title"] == "Promised more than it did: Annual · save 17%"
    assert findings[0]["affectedPersonas"] == 2

    # But two genuinely different controls stay two findings: "Annual" and
    # "Monthly" are close by most string measures and are not the same toggle.
    apart = JobExecutor._pain_points_from_expectations([
        _expectation_run("run_1", "friedrich", [
            ("Clicking the 'Annual' button will show the price.",
             {"type": "CLICK", "target": "e17"}, "no", "No price.", 0.20),
            ("Clicking the 'Monthly' button will show the price.",
             {"type": "CLICK", "target": "e18"}, "no", "Still no price.", 0.40)]),
    ])
    assert len(apart) == 2


def test_a_deck_table_renders_an_em_dash_not_the_word_for_one():
    """`escape(... or "&mdash;")` escapes the entity it was trying to emit, so the
    Personas column of a live deck's summary table read "&mdash;" as literal text
    where the finding affected nobody countable."""
    report = {
        "url": "https://example.test/", "executive_summary": "One issue.",
        "critical_pain_points": [
            {"severity": "critical", "category": "blocker", "title": "The journey was blocked",
             "summary": "They left.", "affectedPersonas": 0},
            {"severity": "high", "category": "expectation", "title": "Promised more than it did",
             "summary": "It did not.", "affectedPersonas": 2},
        ],
        "elements_to_preserve": [], "journey_outcome": {"runs": []}, "limitations": [],
        # The table the entity appears in is built from the priority order.
        "impact_analysis": {"priorityOrder": [
            {"title": "The journey was blocked", "severity": "critical", "affectedPersonas": 0},
            {"title": "Promised more than it did", "severity": "high", "affectedPersonas": 2},
        ]},
    }

    deck = JobExecutor._slide_deck(report)

    assert "&amp;mdash;" not in deck, "the dash is markup and must not be escaped"
    assert "&mdash;" in deck
    assert "<td>2</td>" in deck


def test_a_broken_promise_summary_does_not_double_the_full_stop():
    """Both quotes carry the persona's own full stop; adding another reads as a
    typo, and a live deck rendered `as expected.".`"""
    runs = [_expectation_run("run_1", "friedrich", [
        ("Clicking the 'Annual' button will reveal the price.",
         {"type": "CLICK", "target": "e17"}, "no",
         "Clicking the button did not reveal any annual price as expected.", 0.25)])]

    summary = JobExecutor._pain_points_from_expectations(runs)[0]["summary"]

    assert '.".' not in summary
    assert 'as expected."' in summary
    assert 'reveal the price."' in summary


def test_a_quote_is_attributed_to_whoever_actually_said_it():
    """Quotes and names were kept in two parallel lists and zipped by position, so
    one persona's sentence appeared under another's name as soon as they
    contributed unequal numbers of them."""
    runs = [
        _expectation_run("run_1", "friedrich", [
            ("Clicking the 'Annual' button will show the price.",
             {"type": "CLICK", "target": "e17"}, "no", "Friedrich saw no price.", 0.20),
            ("Clicking the 'Annual' button will show the price.",
             {"type": "CLICK", "target": "e17"}, "no", "Friedrich still saw no price.", 0.40)]),
        _expectation_run("run_2", "sophie", [
            ("Clicking the 'Annual' button will show the price.",
             {"type": "CLICK", "target": "e17"}, "no", "Sophie saw no price either.", 0.30)]),
    ]

    quotes = JobExecutor._pain_points_from_expectations(runs)[0]["personaEvidence"]

    assert quotes, "a finding this well evidenced must carry the evidence"
    for quote in quotes:
        said_by = quote["quote"].split()[0]
        assert quote["personaName"].startswith(said_by), (
            f'{quote["personaName"]} is credited with "{quote["quote"]}"')


def test_an_element_that_resolved_on_another_capture_is_not_called_unreadable():
    """A heading is not drawn black on one step and invisible on the next. When the
    same element reads legible on one capture and blank on another, the blank one
    caught it mid-render -- and the one that found text is the one to believe.

    A live report published "Fails WCAG AA contrast: 'Individual' -- 1.05:1, high"
    against a pricing-card heading that is plainly dark, from a capture taken while
    the card was still fading in: ink luminance 0.9437 against paper at 0.993, both
    near-white, and no marks found at all."""
    mid_animation = {"selector": "e19", "role": "heading", "name": "Individual",
                     "box": {"x": 172, "y": 426, "width": 262, "height": 36},
                     "reason": "too little contrast to make anything out",
                     "internalContrast": 0.0235, "edgeContrast": 0.0353, "ink": 0.0,
                     "contrast": {"ratio": 1.05, "required": 3, "passes": False,
                                  "measured": "text against its own background"}}

    def step(unreadable, legible):
        return {"type": "persona.perception", "data": {
            "eyes": RARE_EYES,
            "scan": {"pattern": "spotted", "fixationBudget": 6, "why": ["in a hurry"]},
            "counts": {"elements": 15, "fixated": 6},
            "notPerceived": unreadable, "notLookedAt": [], "missedWhatTheyCameFor": [],
            "legible": legible}}

    # Blank on one capture, resolved on another: no finding.
    settled = JobExecutor._pain_points_from_perception([{
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [step([mid_animation], []), step([], ["e19"])]}])
    assert settled == []

    # Never resolved anywhere: still reported, because that is a page that never
    # draws it and the guard must not swallow the real case.
    never = JobExecutor._pain_points_from_perception([{
        "runId": "run_1", "profileId": "persona_1",
        "timeline": [step([mid_animation], []), step([mid_animation], ["e20"])]}])
    assert len(never) == 1
    assert "Individual" in never[0]["title"]

    # And a different run resolving it is enough: the page is the same page.
    across = JobExecutor._pain_points_from_perception([
        {"runId": "run_1", "profileId": "persona_1", "timeline": [step([mid_animation], [])]},
        {"runId": "run_2", "profileId": "persona_2", "timeline": [step([], ["e19"])]},
    ])
    assert across == []


def test_findings_about_different_elements_are_not_merged_into_one():
    """Every measured finding titles itself the same way -- "Fails WCAG AA
    contrast: X" -- so the boilerplate alone clears the title-similarity threshold.
    A live run's nineteen perception findings collapsed into three, losing "£200"
    and "Let's talk" into "Individual". Three different elements, three different
    fixes, and a page with ten pale labels has ten of them."""
    findings = [
        {"title": 'Fails WCAG AA contrast: "Individual"', "elementName": "Individual",
         "summary": "It is too pale.", "severity": "high"},
        {"title": 'Fails WCAG AA contrast: "£200"', "elementName": "£200",
         "summary": "It is too pale.", "severity": "high"},
        {"title": 'Fails WCAG AA contrast: "Let\'s talk"', "elementName": "Let's talk",
         "summary": "It is too pale.", "severity": "high"},
    ]

    assert len(JobExecutor._merge_similar_findings(findings)) == 3

    # Findings that name no element still merge on wording, which is what that
    # machinery was built for: a live run published "Generic link text", "Ambiguous
    # link text" and "Non-descriptive link text" as three numbered issues.
    worded = [
        {"title": "Generic link text", "summary": "Links say 'Learn more' everywhere."},
        {"title": "Ambiguous link text", "summary": "Links say 'Learn more' everywhere."},
    ]
    assert len(JobExecutor._merge_similar_findings(worded)) == 1


def test_a_screenful_of_undrawn_elements_is_one_observation():
    """A live run produced twelve "Declared but not drawn" entries -- the entire
    navigation bar, one at a time -- from a single capture taken mid-render. Each
    was individually correct, and together they buried the three findings a reader
    needed. Twelve elements blank on one capture is a fact about the capture."""
    def undrawn(name):
        return {"source": "perception.notDrawn", "severity": "info",
                "category": "profile-specific", "title": f'Declared but not drawn: "{name}"',
                "summary": "Nothing was painted there.", "elementName": name,
                "affectedPersonaIds": ["persona_1"], "personaEvidence": []}

    many = JobExecutor._fold_undrawn([undrawn(name) for name in
                                      ["Home", "Install", "Research", "Pricing", "Sign in"]]
                                     + [{"source": "perception.notPerceived", "title": "Too pale",
                                         "severity": "high"}])

    titles = [item["title"] for item in many]
    assert "5 elements were declared and not drawn" in titles
    assert not any(title.startswith("Declared but not drawn") for title in titles)
    assert "Too pale" in titles, "the fold must not touch anything else"
    folded = next(item for item in many if item["title"].endswith("declared and not drawn"))
    assert '"Home"' in folded["summary"] and "one event" in folded["summary"]

    # Two or three are worth naming individually -- that is the case the finding
    # was written for.
    few = JobExecutor._fold_undrawn([undrawn("Home"), undrawn("Install")])
    assert [item["title"] for item in few] == [
        'Declared but not drawn: "Home"', 'Declared but not drawn: "Install"']


def _finished_run(legible_per_capture, summary="Completed what they came to do. It costs £200."):
    return {"runId": "run_1", "profileId": "persona_1",
            "verdict": {"status": "passed", "summary": summary,
                        "criteria": [{"id": "tasks-completed", "result": "met"}]},
            "timeline": [{"type": "persona.perception", "data": {"legible": items}}
                         for items in legible_per_capture]}


def test_a_vision_claim_the_run_disproves_does_not_lead_the_report():
    """A live report led with "Repeated page layout rendering bug", critical -- "the
    entire header and hero section repeats three times vertically ... looks highly
    broken" -- and second with "Pricing cards are cut off ... preventing users from
    seeing the actual price", high. The capture was correct, every section
    rendered, and the same run's verdict reads "The page does state the pricing
    clearly. £200 per user per year".

    A confident, specific, wrong claim at critical severity is the most damaging
    thing this report can carry."""
    findings = [
        {"source": "eyeson-vision-synthesis", "severity": "critical",
         "title": "Repeated page layout rendering bug",
         "summary": "The entire header and hero section repeats three times vertically."},
        {"source": "eyeson-vision-synthesis", "severity": "high",
         "title": "Pricing cards are cut off and hide actual costs",
         "summary": "The cards are cut off, preventing users from seeing the actual price."},
        {"source": "eyeson-vision-synthesis", "severity": "high",
         "title": "Vague value proposition",
         "summary": "The hero copy is abstract and hard to act on."},
    ]
    run = _finished_run([["e1", "e2", "e3"], ["e1", "e2", "e3", "e4"]])

    notes = JobExecutor._temper_contradicted_findings(findings, [run])

    assert [item["severity"] for item in findings] == ["medium", "medium", "high"], (
        "only the contradicted claims are capped; the rest of the critique stands")
    assert "rendered more than once" in findings[0]["summary"]
    assert "completed the tasks it came to do" in findings[1]["summary"]
    # Kept, not deleted: the visual observation may still be worth a look.
    assert "repeats three times" in findings[0]["summary"]
    # And the report says what it did, rather than quietly rewriting a severity.
    assert len(notes) == 2
    assert all("reported as" in note and "carried at medium" in note for note in notes)


def test_a_duplication_claim_stands_when_the_walk_saw_a_duplicate():
    """The guard must not swallow a real one. If an element really is on the page
    twice, the walk lists it twice, and the claim is corroborated rather than
    contradicted."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "critical",
               "title": "Header repeats", "summary": "The header is duplicated on the page."}
    doubled = _finished_run([["e1", "e2", "e1"]])

    JobExecutor._temper_contradicted_findings([finding], [doubled])

    assert finding["severity"] == "critical"
    assert "not supported by this run" not in finding["summary"]


def test_a_blocking_claim_stands_when_the_run_did_not_finish():
    """And a page that really did stop somebody keeps its severity."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "high",
               "title": "Cards hide the price",
               "summary": "The cards are cut off, preventing users from seeing the actual price."}
    gave_up = {"runId": "run_1", "verdict": {
        "status": "failed", "summary": "Walked away.",
        "criteria": [{"id": "tasks-completed", "result": "not-met"}]}, "timeline": []}

    JobExecutor._temper_contradicted_findings([finding], [gave_up])

    assert finding["severity"] == "high"

    # A finding from anywhere but the vision critique is never touched: the other
    # sources are measurements, not readings of a picture.
    measured = {"source": "perception.notPerceived", "severity": "high",
                "title": "Fails WCAG AA contrast", "summary": "It repeats and prevents reading."}
    JobExecutor._temper_contradicted_findings([measured], [_finished_run([["e1"]])])
    assert measured["severity"] == "high"


def _run_that_read_a_price(prices=("£200 / user / year", "£100 / user / year")):
    """A run whose persona said, before acting, that it could see these sums."""
    return {"runId": "run_1", "profileId": "persona_1",
            "verdict": {"status": "passed",
                        "summary": "Completed what they came to do.",
                        "criteria": [{"id": "tasks-completed", "result": "met"}]},
            "timeline": [{"type": "persona.expectation",
                          "data": {"visible": f"a paragraph: 3-day free trial, then {price}."}}
                         for price in prices]}


def test_a_missing_price_claim_falls_to_what_the_persona_read_off_the_page():
    """Cycle 14 shipped "Missing pricing details on pricing cards" at critical --
    "they do not display any actual prices ... cut off at the bottom, making it
    impossible for users to determine cost" -- in a run whose own verdict reads
    "it lists two options -- £200 per user per year ... and £100 per user per
    year", and whose persona had read both off the page before acting.

    A report that contradicts itself in two directions is worth less than one
    that says nothing."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "critical",
               "title": "Missing pricing details on pricing cards",
               "summary": "The cards do not display any actual prices or currency amounts."}

    notes = JobExecutor._temper_contradicted_findings([finding], [_run_that_read_a_price()])

    assert finding["severity"] == "medium"
    assert "£200" in finding["summary"] and "persona\'s own eyes" in finding["summary"]
    assert len(notes) == 1
    # Kept, not deleted: the cards may well be worth redrawing.
    assert "do not display any actual prices" in finding["summary"]


def test_a_missing_price_claim_stands_when_nobody_ever_saw_a_price():
    """The guard must not swallow a real one. A page that genuinely never shows a
    number leaves no number in anything the persona said it could see."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "critical",
               "title": "Missing pricing details on pricing cards",
               "summary": "The cards do not display any actual prices or currency amounts."}
    priceless = {"runId": "run_1", "verdict": {
        "status": "passed", "summary": "Never found what it costs.",
        "criteria": [{"id": "tasks-completed", "result": "met"}]},
        "timeline": [{"type": "persona.expectation",
                      "data": {"visible": "a heading and a 'Contact sales' button"}}]}

    JobExecutor._temper_contradicted_findings([finding], [priceless])

    assert finding["severity"] == "critical"


def test_an_absence_claim_about_something_other_than_money_is_left_alone():
    """The rebuttal is only as good as the thing it can spot. A price is
    unambiguous in free text; "the trust signals are missing" is not, and a
    guard that cannot check a claim must not temper it."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "high",
               "title": "No social proof", "summary": "Customer logos are missing from the page."}

    JobExecutor._temper_contradicted_findings([finding], [_run_that_read_a_price()])

    assert finding["severity"] == "high"


def test_a_finding_cannot_claim_more_distress_than_the_page_ever_caused():
    """The vision reviewer estimates frustration, confusion and trust erosion from
    a single screenshot, and those numbers reach the report as the finding's stated
    impact. Measured against the runs that produced them they are not close: a run
    whose peak frustration was 0.29, and which passed, carried three findings
    claiming 0.90, 0.90 and 0.60. A run that peaked at 0.20 carried a finding
    claiming 0.90 -- and that was the finding the element walk disproved."""
    run = {"runId": "run_1", "timeline": [
        {"type": "persona.affect", "data": {"state": {"frustration": 0.19, "confusion": 0.17}}},
        {"type": "persona.affect", "data": {"state": {"frustration": 0.29, "confusion": 0.31}}},
        {"type": "persona.affect", "data": {"state": {"frustration": 0.22, "confusion": 0.20}}},
    ]}
    findings = [
        {"title": "Repeated page layout rendering bug", "observations": 1, "affectedPersonas": 1,
         "claimedImpact": {"frustration": 0.90, "confusion": 0.90, "trust": 0.95}},
        {"title": "Vague value proposition", "observations": 1, "affectedPersonas": 1,
         "claimedImpact": {"frustration": 0.10, "confusion": 0.20, "trust": 0.10}},
    ]

    assert JobExecutor._what_the_page_actually_cost([run]) == {"frustration": 0.29, "confusion": 0.31}
    notes = JobExecutor._cap_claimed_impact(findings, [run])

    # Held to what the page was measured to cost anyone, across every step.
    assert findings[0]["claimedImpact"]["frustration"] == 0.29
    assert findings[0]["claimedImpact"]["confusion"] == 0.31
    # Capped, not replaced: a claim inside the ceiling is the model's to make.
    assert findings[1]["claimedImpact"] == {"frustration": 0.10, "confusion": 0.20, "trust": 0.10}
    # The prose is written from the numbers after the cap, so it cannot disagree.
    assert "frustration 0.29" in findings[0]["evidence"]
    assert "0.90" not in findings[0]["evidence"]
    assert "frustration 0.10" in findings[1]["evidence"]
    # And the report says it did this.
    assert len(notes) == 1
    assert "estimated frustration at 0.90" in notes[0]
    assert "measured at most 0.29" in notes[0]


def test_with_no_measured_affect_there_is_no_ceiling_to_impose():
    """A ceiling nobody measured is not a ceiling. An agent-director run records no
    affect at all, and capping its findings against zero would report every one of
    them as costing nothing."""
    findings = [{"title": "Low contrast", "observations": 2, "affectedPersonas": 1,
                 "claimedImpact": {"frustration": 0.80, "confusion": 0.60, "trust": 0.40}}]

    notes = JobExecutor._cap_claimed_impact(findings, [{"runId": "run_1", "timeline": []}])

    assert notes == []
    assert findings[0]["claimedImpact"]["frustration"] == 0.80
    # The evidence line is still written, so every finding states its impact the
    # same way whether or not there was anything to cap it against.
    assert "frustration 0.80" in findings[0]["evidence"]
    assert "2 observations across 1 person" in findings[0]["evidence"]


def test_a_summary_says_when_the_runs_did_not_finish():
    """A live report opened "1 synthetic user(s) attempted 2 task(s) ... 10
    usability issue(s) were identified" over a run that errored after a single
    action on a 429 from the model endpoint. Every other part of the report was
    honest about it -- journey_outcome.status said "partial", a limitation named
    the error -- but the one line most readers read presented a collapsed run as a
    finished review. A caveat five items into a limitations array is a caveat
    nobody reads."""
    cut_short = [{"runId": "run_1", "harnessError": "persona actor endpoint returned HTTP 429",
                  "timeline": [{"type": "persona.expectation", "data": {}}]}]
    findings = [{"title": "Unclear pricing", "severity": "high"}]

    summary = JobExecutor._executive_summary(
        "https://example.test/", ["Find the price", "Say what it does"],
        [{"id": "persona_1"}], findings, [], cut_short)

    assert "stopped early and did not finish the tasks" in summary
    assert "got 1 action in" in summary
    assert "not a full review" in summary
    # Said before the count of what was found, not after it.
    assert summary.index("stopped early") < summary.index("usability issue")

    # A clean run says nothing of the kind.
    clean = JobExecutor._executive_summary(
        "https://example.test/", ["Find the price"], [{"id": "persona_1"}], findings, [],
        [{"runId": "run_1", "timeline": []}])
    assert "stopped early" not in clean
    # And so does a report built without the runs to hand.
    assert "stopped early" not in JobExecutor._executive_summary(
        "https://example.test/", ["Find the price"], [{"id": "persona_1"}], findings, [])


def test_evidence_paired_to_its_own_step_is_not_replaced_by_a_title_match():
    """Two mechanisms write personaEvidence, and the general one was overwriting
    the specific one. The broken-promise finding pairs each quote to the exact step
    that produced it -- the reflection recorded immediately after that action --
    and _attach_persona_evidence then replaced it with the best title-similarity
    match across the whole run.

    In a live report that put the persona's *expectation* under the finding as
    evidence of what went wrong: "Clicking the Monthly toggle button will display
    the specific monthly cost amounts" quoted as the complaint, when the complaint
    the run recorded was "monthly cost amounts for the tiers are not shown". A
    prediction presented as an observation -- and the expectation scored better
    only because the title is made from it."""
    findings = [{
        "title": 'Promised more than it did: Monthly', "personaId": "persona_1",
        "summary": "Clicking Monthly showed nothing.",
        "personaEvidence": [{"quote": "monthly cost amounts for the tiers are not shown",
                             "personaName": "Friedrich Wolf", "personaId": "persona_1"}],
    }, {
        "title": "Monthly toggle shows no cost amounts", "personaId": "persona_1",
        "summary": "The monthly cost amounts are not shown for the tiers.",
    }]
    thoughts = {"persona_1": [
        {"kind": "reasoning", "source": "persona.expectation",
         "text": "Clicking the Monthly toggle button will display the specific monthly cost amounts."},
        {"kind": "reasoning", "source": "persona.reflection",
         "text": "monthly cost amounts for the tiers are not shown"},
    ]}

    JobExecutor._attach_persona_evidence(findings, thoughts, {"persona_1": "Friedrich Wolf"})

    assert findings[0]["personaEvidence"][0]["quote"] == (
        "monthly cost amounts for the tiers are not shown"), "paired evidence is the better evidence"
    # A finding that arrived with none still gets the best match available.
    assert findings[1].get("personaEvidence"), "the matcher still works where nothing was paired"


def test_a_finding_is_titled_by_what_the_walk_read_off_the_control():
    """The label was recovered by pattern-matching the persona's prose, which works
    right up until the persona writes "The Pricing page will load and display the
    company's pricing details" -- naming no control at all. Cycle 19 published
    "Promised more than it did: e6" as a report headline while the element walk
    had known it was the Pricing link the whole time.

    A ref groups nothing and means nothing: the same control is e6 in one run and
    e17 in another."""
    prose = ("The Pricing page will load and display the company's pricing details "
             "and plan options.")
    click = {"type": "CLICK", "target": "e6"}

    assert JobExecutor._promise_label(prose, click) == "e6", "this is what it did"
    assert JobExecutor._promise_label(prose, click, "Pricing") == "Pricing"
    # A measured name that is blank or absent changes nothing: old runs carry none.
    assert JobExecutor._promise_label(prose, click, "   ") == "e6"
    # And the persona's own quoted label still wins over the ref when there is no
    # measured name, which is what made this work at all for fifteen cycles.
    assert JobExecutor._promise_label(
        "Clicking the 'Annual - save 17%' button will show prices",
        {"type": "CLICK", "target": "e17"}) == "Annual - save 17%"


def _promise_group(**over):
    """A broken-promise group in the shape cycle 26 actually produced."""
    group = {
        "label": "Start 3-day free trial", "hits": 1, "cost": 0.22,
        "personas": ["p1"], "names": ["Friedrich Wolf"], "runs": ["r1"],
        "expectations": ["Clicking the 'Start 3-day free trial' button will open a sign-up modal "
                         "that displays the pricing details for the service"],
        "gaps": [{"quote": "Clicked button led to generic content rather than the expected sign-up "
                           "modal showing pricing.", "personaId": "p1", "personaName": "Friedrich Wolf"}],
        "actions": [{"type": "CLICK", "target": "e22"}],
        "boxes": [{"x": 320, "y": 540, "width": 210, "height": 48}],
        "sightings": [{"quote": "I see a 'Start 3-day free trial' button under each plan, and two "
                                "pricing paragraphs.", "personaId": "p1", "personaName": "Friedrich Wolf"}],
        "roles": ["CLICK"],
    }
    group.update(over)
    return group


def test_a_finding_says_one_thing_once():
    """The slide prints four panels. "Clicked button led to generic content rather than the
    expected sign-up modal showing pricing" used to fill three of them: Observed user
    issue, Root cause analysis, and In the user's words. Three headings, one sentence,
    and the panel meant to carry the thinking carried none."""
    finding = JobExecutor._broken_promise_finding(_promise_group())
    gap = "Clicked button led to generic content"

    assert gap in finding["summary"], "the observation still reports what happened"
    assert gap not in finding["rootCause"], "the root cause is not the symptom said again"
    assert gap not in finding["personaEvidence"][0]["quote"], "nor is the quote"
    # And the root cause does not simply move the duplication to the expectation.
    assert "will open a sign-up modal" not in finding["rootCause"]
    # The quote is the person's own first-person account of what they could see --
    # the one thing on the slide that is not already elsewhere on it.
    assert finding["personaEvidence"][0]["quote"].startswith("I see")


def test_b2_the_root_cause_names_the_convention_and_marks_it_as_inference():
    """RPT-2/B2: the benchmark's best sentences name the convention an expectation
    rests on ("as this is the case on other free apps"). Named here too, but
    marked explicitly as an inference about a general convention -- nothing in
    this run measured another site, so it must never read as though it did."""
    root_cause = JobExecutor._why_they_expected_that(_promise_group())

    assert "general web convention" in root_cause
    assert "not something this run measured" in root_cause


def test_b3_a_persona_s_expectations_summarise_into_one_stated_model():
    """RPT-2/B3: not per-control (that is what the broken-promise findings are
    for) but the pattern across the whole run -- a persona whose expectations
    mostly held is a different report from one whose mostly did not."""
    def pair(expectation, matched):
        return [{"type": "persona.expectation", "data": {"expectation": expectation}},
                {"type": "persona.reflection", "data": {"matched": matched}}]

    mostly_navigation = {"timeline": pair("open the pricing page", "yes")
                         + pair("take me to checkout", "no") + pair("navigate to the cart", "yes")}
    assert "taken somewhere" in JobExecutor._persona_mental_model(mostly_navigation)
    assert "held for 2 of 3" in JobExecutor._persona_mental_model(mostly_navigation)

    all_held = {"timeline": pair("show the price", "yes") + pair("display the total", "yes")}
    assert "never held" not in JobExecutor._persona_mental_model(all_held)
    assert "held for" not in JobExecutor._persona_mental_model(all_held), "no partial phrasing when all of them held"

    # Too little to support a stated pattern: no model is honest, a guessed one is not.
    assert JobExecutor._persona_mental_model({"timeline": pair("show the price", "yes")}) == ""
    assert JobExecutor._persona_mental_model({"timeline": []}) == ""


def test_the_root_cause_names_a_mechanism_and_it_depends_on_what_happened():
    """"The click only moves the visitor instead" is the wrong lesson for a control that
    did nothing at all. The mechanism is read from the visitor's own verb and from the
    way the run described what followed."""
    # The fixture's own expectation is "will open a modal that displays pricing": the
    # verb that governs it is "open", and the run recorded that the click did navigate,
    # just not to what was named.
    moved_else = JobExecutor._why_they_expected_that(_promise_group())
    assert "expected to be taken somewhere" in moved_else
    assert "somewhere it has named" in moved_else

    told_else = JobExecutor._why_they_expected_that(_promise_group(
        expectations=["Reading the pricing section will show me what the plans cost"],
        gaps=[{"quote": "the section carried plan names but no amounts"}]))
    assert "expected to be told something" in told_else
    assert "the label is the defect" in told_else

    # "open a page showing the plan" is a request to be taken somewhere: the verb that
    # governs the sentence is the one that comes first, not whichever pattern is tested first.
    moved_silent = JobExecutor._why_they_expected_that(_promise_group(
        label="Monthly",
        expectations=["Clicking Monthly will open a page showing the monthly plan"],
        gaps=[{"quote": "The view did not change and the button is still present."}]))
    assert "expected to be taken somewhere" in moved_silent
    assert "reads as a door" in moved_silent
    assert "nothing they could see" in moved_silent

    told_silent = JobExecutor._why_they_expected_that(_promise_group(
        expectations=["Clicking will show the annual price"],
        gaps=[{"quote": "no price amounts were displayed; nothing changed"}]))
    assert "Silence reads as a control that is broken" in told_silent

    # Nothing to reason from, nothing asserted.
    assert JobExecutor._why_they_expected_that(_promise_group(expectations=[])) == ""


def test_a_finding_knows_where_its_control_was():
    """The report crops evidence to the element a finding is about -- but only when the
    finding knows the box, and the one finding built from what a person actually did
    carried none. So the best-evidenced finding in the report illustrated itself with a
    whole-page screenshot captioned "page context"."""
    finding = JobExecutor._broken_promise_finding(_promise_group())
    assert finding["elementBox"] == {"x": 320, "y": 540, "width": 210, "height": 48}
    assert finding["elementName"] == "Start 3-day free trial"


def test_f5_the_quoted_evidence_prefers_how_it_felt_over_what_they_could_see():
    """RPT-2/F5: the factual gap is already quoted verbatim in the summary above
    "In the user's words" -- requoting it there read as one observation in fancy
    dress. What this cost them, in their own words (persona.affect's `feeling`,
    already recorded by the director), says something the summary did not."""
    with_feeling = JobExecutor._broken_promise_finding(_promise_group(
        feelings=[{"quote": "That was annoying -- I was sure that button would work.",
                  "personaId": "p1", "personaName": "Friedrich Wolf"}]))
    without_feeling = JobExecutor._broken_promise_finding(_promise_group())

    assert with_feeling["personaEvidence"][0]["quote"] == "That was annoying -- I was sure that button would work."
    # No feeling recorded: falls back to what they could see, never straight to
    # the factual gap that is already quoted in the summary.
    assert without_feeling["personaEvidence"][0]["quote"].startswith("I see a 'Start 3-day free trial' button")


def test_measured_cost_arrives_with_the_scale_it_is_measured_on():
    """"0.22 of this visitor's patience on a 0-1 scale" is a real number in a unit nobody
    knows, which reads as less credible than a vague sentence."""
    summary = JobExecutor._broken_promise_finding(_promise_group())["summary"]
    assert "0.22" in summary, "the measurement stays"
    assert "calm to walking away" in summary, "and arrives with something to hold it against"

    assert "most of the way" in JobExecutor._patience_in_words(0.8)
    assert "about a third" in JobExecutor._patience_in_words(0.4)
    assert "small but measurable" in JobExecutor._patience_in_words(0.03)
    # Out-of-range input is clamped rather than described as impossible.
    assert JobExecutor._patience_in_words(-1).startswith("0.00")


def test_the_report_writes_plurals_like_a_person():
    """"1 usability issue(s) were identified" tells the reader, in its own first sentence,
    that the document was assembled rather than written."""
    assert JobExecutor._plural(1, "run") == "1 run"
    assert JobExecutor._plural(2, "run") == "2 runs"
    assert JobExecutor._plural(1, "person", "people") == "1 person"
    assert JobExecutor._plural(3, "person", "people") == "3 people"
    assert "(s)" not in JobExecutor._broken_promise_finding(_promise_group())["evidence"]


def test_traits_are_claimed_only_where_the_encounter_shows_them():
    """A run with three deliberately different visitors reported its findings as though
    they had happened to a generic one, because susceptibleTraits shipped None."""
    assert JobExecutor._traits_behind(_promise_group()) == [], "one calm touch claims nothing"
    assert "low patience" in JobExecutor._traits_behind(_promise_group(hits=3))
    assert "high irritability" in JobExecutor._traits_behind(_promise_group(cost=0.5))
    assert "shared across dispositions" in JobExecutor._traits_behind(
        _promise_group(personas=["p1", "p2"]))


# --- RPT-1: commit to one concrete change --------------------------------------
#
# "Either make {label} do what it reads as doing, or stop it reading that way"
# restated the problem as a choice and handed the thinking back to the reader.
# These pin the replacement: a committed recommendation with a real noun and verb
# from the page, and the rejected half moved to `alternatives` rather than
# dropped.

def test_the_recommendation_commits_instead_of_offering_a_choice():
    finding = JobExecutor._broken_promise_finding(_promise_group())

    assert "Either" not in finding["recommendation"], \
        "a recommendation that hands the choice back to the reader is not a recommendation"
    assert not finding["recommendation"].lower().startswith(("either", "or "))
    # A concrete noun and verb: add, move, relabel, remove -- some verb of that
    # shape, not a restatement of the problem.
    assert any(verb in finding["recommendation"] for verb in ("Relabel", "Make", "Reword"))


def test_a_recommendation_carries_a_noun_drawn_from_the_page_under_test():
    """The acceptance test the plan names: reject any recommendation that would
    read identically on a different page. Two different pages -- two different
    control labels -- must produce two different sentences, both naming their own
    control."""
    label_a = JobExecutor._broken_promise_finding(_promise_group(label="Start 3-day free trial"))
    label_b = JobExecutor._broken_promise_finding(_promise_group(label="See annual pricing"))

    assert "Start 3-day free trial" in label_a["recommendation"]
    assert "See annual pricing" in label_b["recommendation"]
    assert label_a["recommendation"] != label_b["recommendation"]


def test_the_rejected_half_of_the_commitment_lands_in_alternatives_not_nowhere():
    """RPT-1: `_finding_slide` only synthesises `alternatives` from `recommendation`
    when the field is empty -- that fallback existed because this finding type
    never filled it. It is filled now, with the option not committed to above,
    never an echo of the recommendation itself."""
    finding = JobExecutor._broken_promise_finding(_promise_group())

    assert finding["alternatives"], "the field the audit found shipping None must carry something"
    proposed = finding["alternatives"][0]["proposedChange"]
    assert proposed != finding["recommendation"], \
        "an alternative that repeats the recommendation is not an alternative"
    assert finding["alternatives"][0].get("rationale")


def test_something_happening_is_a_relabel_nothing_happening_is_a_build():
    """The rule the commitment turns on: nothing visible happened (a likely
    implementation bug) commits to building the behaviour the label already
    promises; something happened, just not what was promised (the behaviour
    exists and evidently works) commits to fixing the label instead."""
    nothing_happened = JobExecutor._broken_promise_finding(_promise_group(
        label="Monthly",
        expectations=["Clicking Monthly will open a page showing the monthly plan"],
        gaps=[{"quote": "The view did not change and the button is still present.", "personaId": "p1"}]))
    assert nothing_happened["recommendation"].startswith("Make “Monthly”")

    something_else_happened = JobExecutor._broken_promise_finding(_promise_group())  # default fixture
    assert something_else_happened["recommendation"].startswith("Relabel “Start 3-day free trial”")


def test_nothing_to_reason_from_commits_to_nothing():
    """The same honesty `_why_they_expected_that` already has: a group with no
    expectation to classify produces no recommendation and no alternatives,
    rather than a generic sentence with no noun to hang it on."""
    recommendation, alternatives = JobExecutor._committed_recommendation(_promise_group(expectations=[]))
    assert recommendation == ""
    assert alternatives == []


def test_a_run_that_saw_less_than_it_tried_to_says_so():
    """Cycle 26 lost four walks in one journey and shipped run_diagnostics: [], so a reader
    had no way to know the review was made on ten steps of twelve."""
    from apps.api.executor import _coverage_diagnostics

    timeline = ([{"type": "persona.expectation"}] * 12
                + [{"type": "persona.perception"}] * 10
                + [{"type": "persona.perception_fallback",
                    "data": {"reason": "the perception service returned nothing"}}] * 4
                + [{"type": "persona.reflection_unavailable"}] * 3)
    (entry,) = _coverage_diagnostics([{"runId": "r1", "profileId": "p1", "timeline": timeline}])

    assert entry["severity"] == "medium"
    assert "10 of 12 steps" in entry["summary"]
    assert "the perception service returned nothing (4×)" in entry["summary"]
    assert "3 actions drew no conclusion" in entry["summary"]
    assert "unknown rather than absent" in entry["recommendation"]

    # A run that saw everything says nothing, and a run that lost most of it says more.
    assert _coverage_diagnostics([{"runId": "r2", "timeline":
        [{"type": "persona.expectation"}] * 5 + [{"type": "persona.perception"}] * 5}]) == []
    (bad,) = _coverage_diagnostics([{"runId": "r3", "timeline":
        [{"type": "persona.expectation"}] * 12 + [{"type": "persona.perception"}] * 4
        + [{"type": "persona.perception_fallback", "data": {"reason": "the page moved under the walk"}}] * 8}])
    assert bad["severity"] == "high"


def test_no_reader_facing_string_writes_a_machine_plural():
    """`_plural` was added as a method on JobExecutor and fixed exactly one of the
    eighteen places that needed it -- the same mistake in a different costume: a rule
    written where the problem was noticed rather than where it applies. Two more crept
    into the coverage diagnostic while that fix was being written.

    So the rule is checked over the whole module rather than at the sites someone
    happened to look at. Docstrings and comments quoting the old behaviour are exempt;
    they are the record of why this exists.
    """
    import ast
    import inspect
    import re

    from apps.api import executor

    source = inspect.getsource(executor)
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            text = ast.get_docstring(node)
            if text:
                docstrings.update(text.splitlines())

    offenders = []
    for number, line in enumerate(source.splitlines(), start=1):
        bare = line.strip().strip('"')
        if line.strip().startswith("#") or bare in docstrings or line in docstrings:
            continue
        if re.search(r"\w\(s\)", line):
            offenders.append(f"{number}: {bare[:90]}")
    assert not offenders, "machine plurals in reader-facing strings:\n" + "\n".join(offenders)


def test_the_deck_says_how_much_of_the_run_it_could_see():
    """An absent finding and an unmeasured one look identical on a slide. The coverage
    diagnostic was reaching the JSON and a limitations line that reads "see
    run_diagnostics" -- which a reader of the deck cannot do."""
    from apps.api.executor import _coverage_diagnostics

    diagnostics = _coverage_diagnostics([{"runId": "r1", "timeline":
        [{"type": "persona.expectation"}] * 12 + [{"type": "persona.perception"}] * 10
        + [{"type": "persona.perception_fallback",
            "data": {"reason": "the perception service returned nothing"}}] * 4}])
    note = JobExecutor._coverage_note({"run_diagnostics": diagnostics})

    assert "10/12 steps perceived" in note
    assert "unknown rather than ruled out" in note
    # A run that saw everything says nothing, rather than printing a reassuring zero.
    assert JobExecutor._coverage_note({"run_diagnostics": []}) == ""


def _run_that_measured(captures, summary="Completed what they came to do. It costs £200."):
    """A run whose captures carry what the perception service measured on them."""
    return {"runId": "run_1", "profileId": "persona_1",
            "verdict": {"status": "passed", "summary": summary,
                        "criteria": [{"id": "tasks-completed", "result": "met"}]},
            "timeline": [{"type": "persona.perception",
                          "data": {"legible": ["e1", "e2"], "capture": capture}}
                         for capture in captures]}


def test_a_cut_off_claim_is_checked_against_what_ran_past_the_edge():
    """"The pricing cards are cut off" is a statement about clipping, and the
    perception service measures clipping per element on every capture. Until now
    the only thing that answered it was whether the run happened to finish."""
    clean = [{"measured": 20, "clipped": 0, "blankShare": 0.0, "smallestFontPx": 14.0},
             {"measured": 18, "clipped": 0, "blankShare": 0.0, "smallestFontPx": 14.0}]
    finding = {"source": "eyeson-vision-synthesis", "severity": "high",
               "title": "Pricing cards are cut off",
               "summary": "The cards are cut off at the bottom of the viewport."}

    JobExecutor._temper_contradicted_findings([finding], [_run_that_measured(clean)])

    assert finding["severity"] == "medium"
    assert "nothing on the page was cut off" in finding["summary"]

    # And it stands when something really did run past the edge.
    real = [{"measured": 20, "clipped": 3, "blankShare": 0.0, "smallestFontPx": 14.0}]
    stands = {"source": "eyeson-vision-synthesis", "severity": "high",
              "title": "Pricing cards are cut off",
              "summary": "The cards are cut off at the bottom of the viewport."}
    JobExecutor._temper_contradicted_findings([stands], [_run_that_measured(real)])
    assert stands["severity"] == "high"


def test_a_tiny_text_claim_is_checked_against_the_type_the_walk_measured():
    """The walk reads the computed font size off every element it reports, so the
    page's own number answers this rather than an impression of one."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "high",
               "title": "Body text is too small to read",
               "summary": "The text is too small to read comfortably."}
    roomy = [{"measured": 20, "clipped": 0, "blankShare": 0.0, "smallestFontPx": 14.0}]

    JobExecutor._temper_contradicted_findings([finding], [_run_that_measured(roomy)])

    assert finding["severity"] == "medium"
    assert "14px" in finding["summary"]

    # A page that really is set in 9px keeps the finding.
    small = [{"measured": 20, "clipped": 0, "blankShare": 0.0, "smallestFontPx": 9.0}]
    stands = {"source": "eyeson-vision-synthesis", "severity": "high",
              "title": "Body text is too small to read",
              "summary": "The text is too small to read comfortably."}
    JobExecutor._temper_contradicted_findings([stands], [_run_that_measured(small)])
    assert stands["severity"] == "high"


def test_an_empty_sections_claim_is_checked_against_the_blank_share():
    """"Massive empty vertical sections ... a major rendering bug" was filed at
    critical severity against our own capture. The share of regions with nothing
    drawn in them is measured on every capture and answers it directly."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "critical",
               "title": "Massive empty sections",
               "summary": "There are massive empty vertical sections down the page."}
    drawn = [{"measured": 30, "clipped": 0, "blankShare": 0.0, "smallestFontPx": 14.0}]

    JobExecutor._temper_contradicted_findings([finding], [_run_that_measured(drawn)])

    assert finding["severity"] == "medium"
    assert "no part of the page was blank" in finding["summary"]


def test_a_check_that_cannot_run_does_not_pass():
    """A run whose captures carry no measurement must not read as a clean one --
    the commonest way a guard comes to report that it ran when it did not."""
    finding = {"source": "eyeson-vision-synthesis", "severity": "high",
               "title": "Pricing cards are cut off",
               "summary": "The cards are cut off at the bottom of the viewport."}
    nothing = {"runId": "run_1", "profileId": "persona_1",
               "verdict": {"status": "failed", "summary": "", "criteria": []},
               "timeline": [{"type": "persona.perception", "data": {"legible": ["e1"]}}]}

    JobExecutor._temper_contradicted_findings([finding], [nothing])

    assert finding["severity"] == "high"
    assert "not supported by this run" not in finding["summary"]


# --- BE-5: concurrency -----------------------------------------------------------

def test_be5_persona_runs_are_dispatched_concurrently_and_stay_in_persona_order(tmp_path, monkeypatch):
    """A bounded pool, not one persona at a time -- proven by two runs actually
    overlapping in wall time, not merely by both completing. journeys must stay
    in the same order as personas even when the slower run (persona_ada, whose
    fake request sleeps longer) finishes after the faster one, because
    everything downstream (thoughts_by_persona, the scorecard, impact_analysis)
    zips journeys against personas positionally."""
    import json as json_module
    import threading
    import time

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    personas = [store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": pid, "persona": {"name": name}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}}) for pid, name in [("persona_ada", "slow"), ("persona_lin", "fast")]]

    in_flight = []
    lock = threading.Lock()
    overlapped = threading.Event()

    def dispatch(req, timeout):
        payload = json_module.loads(req.data)
        with lock:
            in_flight.append(payload["profile"]["id"])
            if len(in_flight) >= 2:
                overlapped.set()
        # persona_ada takes longer, and finishes its (fake) request after
        # persona_lin despite being submitted first.
        time.sleep(0.15 if payload["profile"]["id"] == "persona_ada" else 0.02)
        with lock:
            in_flight.remove(payload["profile"]["id"])

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        return Response(json_module.dumps({
            "runId": payload["runId"], "runStatus": "completed",
            "profileId": payload["profile"]["id"], "simulationProfile": payload["profile"],
            "verdict": {"status": "passed", "criteria": [{"id": "tasks-completed", "result": "met"}],
                       "blockers": [], "uxFindings": [], "suggestedImprovements": []},
            "artifacts": {"screenshots": [], "snapshots": []}}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.delenv("EYESON_WORKER_URL", raising=False)
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    ids = [persona["artifact_id"] for persona in personas]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])
    report = json_module.loads(store.read_artifact(completed["output_artifacts"][0]))

    assert completed["status"] == "succeeded"
    assert overlapped.is_set(), "both requests must have been in flight at once, not sequential"
    runs = report["journey_outcome"]["runs"]
    assert [run["profileId"] for run in runs] == ["persona_ada", "persona_lin"], (
        "journeys must stay in persona order regardless of which request actually finished first")


def test_be5_a_rejected_persona_run_still_fails_the_whole_job(tmp_path, monkeypatch):
    """Matches the old sequential loop's behaviour: one persona's run being
    rejected by the worker fails the job, with the same 422 message."""
    import json as json_module
    from urllib.error import HTTPError
    from io import BytesIO

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    personas = [store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": pid, "persona": {"name": name}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}}) for pid, name in [("persona_ada", "a"), ("persona_lin", "b")]]

    def dispatch(req, timeout):
        payload = json_module.loads(req.data)
        if payload["profile"]["id"] == "persona_ada":
            raise HTTPError(req.full_url, 422, "Unprocessable Entity", {}, BytesIO(b"allowIrreversibleActions required"))

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        return Response(json_module.dumps({
            "runId": payload["runId"], "runStatus": "completed",
            "profileId": payload["profile"]["id"], "simulationProfile": payload["profile"],
            "verdict": {"status": "passed", "criteria": [], "blockers": [], "uxFindings": [],
                       "suggestedImprovements": []},
            "artifacts": {"screenshots": [], "snapshots": []}}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.delenv("EYESON_WORKER_URL", raising=False)
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    ids = [persona["artifact_id"] for persona in personas]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])

    assert completed["status"] == "failed"
    assert "allowIrreversibleActions" in completed["error"]["message"]


def test_be5_the_pool_is_bounded_by_max_concurrent_model_calls(tmp_path, monkeypatch):
    """The pool never exceeds MAX_CONCURRENT_MODEL_CALLS in-flight requests at
    once, whatever the cohort size -- concurrency against a provider whose
    fallback does not work multiplies exactly the failure mode BE-1 exists to
    fix, which is why this knob exists at all."""
    import json as json_module
    import threading
    import time

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    session = store.create_session({"metadata": {}, "external_ref": {}})
    personas = [store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": f"persona_{i}", "persona": {"name": f"p{i}"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}}) for i in range(4)]

    lock = threading.Lock()
    in_flight, peak = 0, 0

    def dispatch(req, timeout):
        nonlocal in_flight, peak
        payload = json_module.loads(req.data)
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        return Response(json_module.dumps({
            "runId": payload["runId"], "runStatus": "completed",
            "profileId": payload["profile"]["id"], "simulationProfile": payload["profile"],
            "verdict": {"status": "passed", "criteria": [], "blockers": [], "uxFindings": [],
                       "suggestedImprovements": []},
            "artifacts": {"screenshots": [], "snapshots": []}}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.setenv("MAX_CONCURRENT_MODEL_CALLS", "2")
    monkeypatch.delenv("EYESON_WORKER_URL", raising=False)
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    ids = [persona["artifact_id"] for persona in personas]
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": ids, "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": ids, "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])
    completed = store.get_job(job["job_id"])

    assert completed["status"] == "succeeded"
    assert peak == 2, f"expected at most 2 in flight at once, saw {peak}"
