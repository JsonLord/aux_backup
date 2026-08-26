"""Canonical FastAPI application; replaces Jules as the product control plane."""
import asyncio
import base64
import json
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse
import requests

from .executor import JobExecutor
from .legacy import LegacyGitHubSessionProvider
from .models import ArtifactCreate, ArtifactPin, JobCreate, LegacyGitHubImport, SessionCreate
from .store import Store


def create_app(store: Store | None = None, legacy_provider: LegacyGitHubSessionProvider | None = None) -> FastAPI:
    store = store or Store()
    legacy_provider = legacy_provider or LegacyGitHubSessionProvider()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store
        yield

    app = FastAPI(title="Synthetic UX Testing Platform", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    executor = JobExecutor(store)

    def required(value, noun):
        if value is None:
            raise HTTPException(404, f"{noun} not found")
        return value

    def identity(x_workspace_id: str = Header("local", alias="X-Workspace-ID"), x_user_id: str = Header("local", alias="X-User-ID")):
        return {"workspace_id": x_workspace_id, "owner_user_id": x_user_id}

    def authorized(record, auth, noun):
        record = required(record, noun)
        if record.get("workspace_id", "local") != auth["workspace_id"]:
            raise HTTPException(404, f"{noun} not found")
        return record

    @app.get("/healthz")
    def health(): return {"status": "ok"}

    @app.get("/readyz")
    def ready(): return {"status": "ready", "storage": "sqlite"}

    @app.get("/v1/system/services")
    def services():
        return {"services": [{"name": "control-plane", "version": app.version, "status": "ready"}], "placeholders": ["postgresql", "redis", "journey-worker", "eyeson-worker", "persona-service", "semantic-service"]}

    @app.get("/v1/legacy/github/branches")
    def legacy_branches(repository: str, auth=Depends(identity)):
        del auth
        try:
            return {"items": legacy_provider.list_branches(repository)}
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(502, f"legacy GitHub lookup failed: {exc}") from exc

    @app.post("/v1/legacy/github/import", status_code=201)
    def import_legacy(body: LegacyGitHubImport, auth=Depends(identity)):
        try:
            imported = legacy_provider.read_artifacts(body.repository, body.branch)
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(502, f"legacy GitHub import failed: {exc}") from exc
        session = store.create_session({"metadata": {"source": "legacy_github", "read_only": True}, "external_ref": {"provider": "github", "repository": body.repository, "branch": body.branch}}, **auth)
        artifact_ids = []
        for item in imported:
            suffix = item["path"].rsplit(".", 1)[-1].lower()
            content_type = {"json": "application/json", "html": "text/html", "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webm": "video/webm"}.get(suffix, "text/markdown")
            artifact = store.create_artifact({"session_id": session["session_id"], "kind": "legacy.report" if suffix in {"md", "json", "html"} else "legacy.evidence", "content_type": content_type, "content": item["content"].decode("utf-8", errors="replace") if content_type.startswith("text/") or content_type == "application/json" else base64.b64encode(item["content"]).decode(), "metadata": {"legacy_path": item["path"], "github_sha": item["sha"], "encoding": "base64" if not (content_type.startswith("text/") or content_type == "application/json") else "utf-8"}, "retention_class": "structured" if suffix in {"md", "json", "html"} else "raw"})
            artifact_ids.append(artifact["artifact_id"])
        return {"session": session, "artifact_ids": artifact_ids, "imported": len(artifact_ids), "read_only": True}

    @app.post("/v1/sessions", status_code=201)
    def create_session(body: SessionCreate, auth=Depends(identity)): return store.create_session(body.model_dump() if hasattr(body, "model_dump") else body.dict(), **auth)

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, auth=Depends(identity)): return authorized(store.get_session(session_id), auth, "session")

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str, auth=Depends(identity)):
        authorized(store.get_session(session_id), auth, "session")
        store.delete_session(session_id)

    @app.get("/v1/sessions/{session_id}/jobs")
    def session_jobs(session_id: str, auth=Depends(identity)):
        authorized(store.get_session(session_id), auth, "session")
        return {"items": store.list_jobs(session_id)}

    @app.get("/v1/sessions/{session_id}/artifacts")
    def session_artifacts(session_id: str, auth=Depends(identity)):
        authorized(store.get_session(session_id), auth, "session")
        return {"items": store.list_artifacts(session_id)}

    @app.post("/v1/jobs", status_code=202)
    def create_job(body: JobCreate, response: Response, background_tasks: BackgroundTasks, auth=Depends(identity)):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        authorized(store.get_session(payload["session_id"]), auth, "session")
        record, created = store.create_job(payload)
        if not created:
            response.status_code = status.HTTP_200_OK
        else:
            background_tasks.add_task(executor.run, record["job_id"])
        return record

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, auth=Depends(identity)): return authorized(store.get_job(job_id), auth, "job")

    @app.get("/v1/jobs/{job_id}/attempts")
    def attempts(job_id: str, auth=Depends(identity)):
        authorized(store.get_job(job_id), auth, "job")
        return {"items": store.attempts(job_id)}

    @app.get("/v1/jobs/{job_id}/result")
    def result(job_id: str, auth=Depends(identity)):
        job = authorized(store.get_job(job_id), auth, "job")
        if job["status"] != "succeeded":
            raise HTTPException(409, "job has no successful result")
        return {"job_id": job_id, "artifacts": [store.get_artifact(item) for item in job["output_artifacts"]]}

    @app.post("/v1/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str, auth=Depends(identity)):
        job = authorized(store.get_job(job_id), auth, "job")
        if job["status"] in ("succeeded", "failed", "cancelled"):
            raise HTTPException(409, "terminal jobs cannot be cancelled")
        store.update_job(job_id, "cancel_requested")
        store.event(job_id, "job.cancel_requested", None, {})
        return store.get_job(job_id)

    @app.post("/v1/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str, background_tasks: BackgroundTasks, auth=Depends(identity)):
        job = authorized(store.get_job(job_id), auth, "job")
        if job["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "only failed or cancelled jobs can be retried")
        store.update_job(job_id, "queued", attempt=job["attempt"] + 1, started_at=None, ended_at=None, error=None)
        store.event(job_id, "job.retried", 0, {"attempt": job["attempt"] + 1})
        background_tasks.add_task(executor.run, job_id)
        return store.get_job(job_id)

    @app.get("/v1/jobs/{job_id}/events")
    def events(job_id: str, after: int = 0, auth=Depends(identity)):
        authorized(store.get_job(job_id), auth, "job")
        return {"items": store.events(job_id, after)}

    @app.get("/v1/jobs/{job_id}/events/stream")
    async def event_stream(job_id: str, last_event_id: str | None = Header(None, alias="Last-Event-ID"), auth=Depends(identity)):
        authorized(store.get_job(job_id), auth, "job")
        async def generate():
            cursor = int(last_event_id or 0)
            for _ in range(60):
                for event in store.events(job_id, cursor):
                    cursor = event["sequence"]
                    yield f'id: {cursor}\nevent: {event["type"]}\ndata: {json.dumps(event)}\n\n'
                if store.get_job(job_id)["status"] in ("succeeded", "failed", "cancelled"):
                    return
                await asyncio.sleep(1)
        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/v1/artifacts", status_code=201)
    def create_artifact(body: ArtifactCreate, auth=Depends(identity)):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        authorized(store.get_session(payload["session_id"]), auth, "session")
        return store.create_artifact(payload)

    @app.get("/v1/artifacts/{artifact_id}")
    @app.get("/v1/artifacts/{artifact_id}/metadata")
    def artifact(artifact_id: str, auth=Depends(identity)): return authorized(store.get_artifact(artifact_id), auth, "artifact")

    @app.get("/v1/artifacts/{artifact_id}/content")
    def artifact_content(artifact_id: str, auth=Depends(identity)):
        artifact = authorized(store.get_artifact(artifact_id), auth, "artifact")
        return FileResponse(artifact["path"], media_type=artifact["content_type"])

    @app.patch("/v1/artifacts/{artifact_id}/pin")
    def pin_artifact(artifact_id: str, body: ArtifactPin, auth=Depends(identity)):
        authorized(store.get_artifact(artifact_id), auth, "artifact")
        return store.pin_artifact(artifact_id, body.pinned)

    return app


app = create_app()
