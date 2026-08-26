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
    assert len(job["output_artifacts"]) == 1
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
