"""Canonical FastAPI application; replaces Jules as the product control plane."""
import asyncio
import base64
import json
import os
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
import requests

from .auth import IdentityProvider
from .executor import JobExecutor
from .legacy import LegacyGitHubSessionProvider
from .models import ArtifactCreate, ArtifactPin, JobCreate, LegacyGitHubImport, MultipartComplete, PresignedArtifactCreate, SessionCreate
from .queue import job_queue
from .store import Store, create_store


def create_app(store: Store | None = None, legacy_provider: LegacyGitHubSessionProvider | None = None, identity_provider=None) -> FastAPI:
    store = store or create_store()
    legacy_provider = legacy_provider or LegacyGitHubSessionProvider()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store
        yield

    app = FastAPI(title="Synthetic UX Testing Platform", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    executor = JobExecutor(store)
    identity = identity_provider or IdentityProvider(membership_store=store if store.backend == "postgresql" else None)

    def required(value, noun):
        if value is None:
            raise HTTPException(404, f"{noun} not found")
        return value

    def authorized(record, auth, noun):
        record = required(record, noun)
        if record.get("workspace_id", "local") != auth["workspace_id"]:
            raise HTTPException(404, f"{noun} not found")
        return record

    def require_write(auth):
        if auth.get("role", "owner") not in {"owner", "admin", "write", "contributor", "service"}:
            raise HTTPException(403, "workspace role is read-only")

    @app.get("/healthz")
    def health(): return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        try:
            store.ping()
            artifact_storage = getattr(store, "artifact_storage", None)
            if artifact_storage: artifact_storage.ping()
            if store.backend == "postgresql" and os.getenv("JOB_QUEUE") == "celery":
                from redis import Redis
                Redis.from_url(os.environ["REDIS_URL"]).ping()
        except Exception as error:
            raise HTTPException(503, "production dependency is unavailable") from error
        return {"status": "ready", "storage": store.backend, "artifacts": getattr(getattr(store, "artifact_storage", None), "backend", "filesystem")}

    @app.get("/v1/system/services")
    def services():
        return {"services": [{"name": "control-plane", "version": app.version, "status": "ready", "storage": store.backend}], "placeholders": ["journey-worker", "eyeson-worker", "semantic-service"]}

    @app.get("/v1/me")
    def me(auth=Depends(identity)):
        return {"user": auth.get("user", {"id": auth["owner_user_id"]}), "workspaces": auth.get("workspaces", [{"id": auth["workspace_id"], "name": auth["workspace_id"], "type": "local", "role": "owner"}]), "selected_workspace_id": auth["workspace_id"]}

    @app.get("/v1/legacy/github/branches")
    def legacy_branches(repository: str, auth=Depends(identity)):
        del auth
        try:
            return {"items": legacy_provider.list_branches(repository)}
        except (requests.RequestException, ValueError) as exc:
            raise HTTPException(502, f"legacy GitHub lookup failed: {exc}") from exc

    @app.post("/v1/legacy/github/import", status_code=201)
    def import_legacy(body: LegacyGitHubImport, auth=Depends(identity)):
        require_write(auth)
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
    def create_session(body: SessionCreate, auth=Depends(identity)):
        require_write(auth)
        return store.create_session(body.model_dump() if hasattr(body, "model_dump") else body.dict(), workspace_id=auth["workspace_id"], owner_user_id=auth["owner_user_id"])

    @app.get("/v1/sessions")
    def list_sessions(auth=Depends(identity)): return {"items": store.list_sessions(auth["workspace_id"])}

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str, auth=Depends(identity)): return authorized(store.get_session(session_id), auth, "session")

    @app.delete("/v1/sessions/{session_id}", status_code=204)
    def delete_session(session_id: str, auth=Depends(identity)):
        require_write(auth)
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
        require_write(auth)
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        authorized(store.get_session(payload["session_id"]), auth, "session")
        record, created = store.create_job(payload)
        if not created:
            response.status_code = status.HTTP_200_OK
        else:
            job_queue(executor, background_tasks).enqueue(record["job_id"])
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
        require_write(auth)
        job = authorized(store.get_job(job_id), auth, "job")
        if job["status"] in ("succeeded", "failed", "cancelled"):
            raise HTTPException(409, "terminal jobs cannot be cancelled")
        store.update_job(job_id, "cancel_requested")
        store.event(job_id, "job.cancel_requested", None, {})
        return store.get_job(job_id)

    @app.post("/v1/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str, background_tasks: BackgroundTasks, auth=Depends(identity)):
        require_write(auth)
        job = authorized(store.get_job(job_id), auth, "job")
        if job["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "only failed or cancelled jobs can be retried")
        store.update_job(job_id, "queued", attempt=job["attempt"] + 1, started_at=None, ended_at=None, error=None)
        store.event(job_id, "job.retried", 0, {"attempt": job["attempt"] + 1})
        job_queue(executor, background_tasks).enqueue(job_id)
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
        require_write(auth)
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        authorized(store.get_session(payload["session_id"]), auth, "session")
        return store.create_artifact(payload)

    @app.get("/v1/artifacts/{artifact_id}")
    @app.get("/v1/artifacts/{artifact_id}/metadata")
    def artifact(artifact_id: str, auth=Depends(identity)): return authorized(store.get_artifact(artifact_id), auth, "artifact")

    @app.get("/v1/artifacts/{artifact_id}/content")
    def artifact_content(artifact_id: str, auth=Depends(identity)):
        artifact = authorized(store.get_artifact(artifact_id), auth, "artifact")
        storage = getattr(store, "artifact_storage", None)
        if storage and storage.backend == "r2":
            return RedirectResponse(storage.presign_download(artifact["path"]), status_code=307)
        return FileResponse(artifact["path"], media_type=artifact["content_type"])

    @app.post("/v1/artifacts/uploads", status_code=201)
    def create_upload(body: PresignedArtifactCreate, auth=Depends(identity)):
        require_write(auth)
        payload = body.model_dump()
        authorized(store.get_session(payload["session_id"]), auth, "session")
        storage = getattr(store, "artifact_storage", None)
        if not storage or storage.backend != "r2" or not hasattr(store, "reserve_artifact"):
            raise HTTPException(409, "presigned uploads require the R2 production adapter")
        artifact = store.reserve_artifact(payload)
        if body.multipart:
            upload_id = storage.create_multipart(artifact["path"], body.content_type)
            return {"artifact": artifact, "multipart": True, "upload_id": upload_id}
        upload = storage.presign_upload(auth["workspace_id"], body.session_id, artifact["artifact_id"], body.size, body.content_type)
        return {"artifact": artifact, "multipart": False, "upload": storage.response(upload)}

    @app.post("/v1/artifacts/{artifact_id}/uploads/parts/{part_number}")
    def presign_part(artifact_id: str, part_number: int, upload_id: str, auth=Depends(identity)):
        require_write(auth)
        artifact = authorized(store.get_artifact(artifact_id), auth, "artifact")
        storage = getattr(store, "artifact_storage", None)
        if not storage or storage.backend != "r2": raise HTTPException(409, "multipart uploads require R2")
        return {"part_number": part_number, "url": storage.presign_part(artifact["path"], upload_id, part_number)}

    @app.post("/v1/artifacts/{artifact_id}/uploads/complete")
    def complete_upload(artifact_id: str, body: MultipartComplete, auth=Depends(identity)):
        require_write(auth)
        artifact = authorized(store.get_artifact(artifact_id), auth, "artifact")
        storage = getattr(store, "artifact_storage", None)
        if not storage or storage.backend != "r2": raise HTTPException(409, "multipart uploads require R2")
        if body.upload_id:
            if not body.parts: raise HTTPException(422, "multipart completion requires parts")
            storage.complete_multipart(artifact["path"], body.upload_id, [item.model_dump() for item in body.parts])
        expected = artifact["metadata"].get("expected_size")
        if expected is not None and storage.size(artifact["path"]) != expected:
            raise HTTPException(409, "uploaded object size does not match reservation")
        return store.complete_artifact_upload(artifact_id)

    @app.patch("/v1/artifacts/{artifact_id}/pin")
    def pin_artifact(artifact_id: str, body: ArtifactPin, auth=Depends(identity)):
        require_write(auth)
        authorized(store.get_artifact(artifact_id), auth, "artifact")
        return store.pin_artifact(artifact_id, body.pinned)

    return app


app = create_app()
