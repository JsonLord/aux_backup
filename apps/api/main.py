"""Canonical FastAPI application; replaces Jules as the product control plane."""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Response, status
from fastapi.responses import FileResponse, StreamingResponse

from .models import ArtifactCreate, JobCreate, SessionCreate
from .store import Store


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store()

    @asynccontextmanager
    async def lifespan(app):
        app.state.store = store
        yield

    app = FastAPI(title="Synthetic UX Testing Platform", version="0.1.0", lifespan=lifespan)
    app.state.store = store

    def required(value, noun):
        if value is None:
            raise HTTPException(404, f"{noun} not found")
        return value

    @app.get("/healthz")
    def health(): return {"status": "ok"}

    @app.get("/readyz")
    def ready(): return {"status": "ready", "storage": "sqlite"}

    @app.get("/v1/system/services")
    def services():
        return {"services": [{"name": "control-plane", "version": app.version, "status": "ready"}], "placeholders": ["postgresql", "redis", "journey-worker", "eyeson-worker", "persona-service", "semantic-service"]}

    @app.post("/v1/sessions", status_code=201)
    def create_session(body: SessionCreate): return store.create_session(body.model_dump() if hasattr(body, "model_dump") else body.dict())

    @app.get("/v1/sessions/{session_id}")
    def get_session(session_id: str): return required(store.get_session(session_id), "session")

    @app.get("/v1/sessions/{session_id}/jobs")
    def session_jobs(session_id: str):
        required(store.get_session(session_id), "session")
        return {"items": store.list_jobs(session_id)}

    @app.get("/v1/sessions/{session_id}/artifacts")
    def session_artifacts(session_id: str):
        required(store.get_session(session_id), "session")
        return {"items": store.list_artifacts(session_id)}

    @app.post("/v1/jobs", status_code=202)
    def create_job(body: JobCreate, response: Response):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        required(store.get_session(payload["session_id"]), "session")
        record, created = store.create_job(payload)
        if not created:
            response.status_code = status.HTTP_200_OK
        return record

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str): return required(store.get_job(job_id), "job")

    @app.post("/v1/jobs/{job_id}/cancel", status_code=202)
    def cancel_job(job_id: str):
        job = required(store.get_job(job_id), "job")
        if job["status"] in ("succeeded", "failed", "cancelled"):
            raise HTTPException(409, "terminal jobs cannot be cancelled")
        store.update_job(job_id, "cancel_requested")
        store.event(job_id, "job.cancel_requested", None, {})
        return store.get_job(job_id)

    @app.post("/v1/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str):
        job = required(store.get_job(job_id), "job")
        if job["status"] not in ("failed", "cancelled"):
            raise HTTPException(409, "only failed or cancelled jobs can be retried")
        store.update_job(job_id, "queued", attempt=job["attempt"] + 1, started_at=None, ended_at=None, error=None)
        store.event(job_id, "job.retried", 0, {"attempt": job["attempt"] + 1})
        return store.get_job(job_id)

    @app.get("/v1/jobs/{job_id}/events")
    def events(job_id: str, after: int = 0):
        required(store.get_job(job_id), "job")
        return {"items": store.events(job_id, after)}

    @app.get("/v1/jobs/{job_id}/events/stream")
    async def event_stream(job_id: str, last_event_id: str | None = Header(None, alias="Last-Event-ID")):
        required(store.get_job(job_id), "job")
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
    def create_artifact(body: ArtifactCreate):
        payload = body.model_dump() if hasattr(body, "model_dump") else body.dict()
        required(store.get_session(payload["session_id"]), "session")
        return store.create_artifact(payload)

    @app.get("/v1/artifacts/{artifact_id}")
    @app.get("/v1/artifacts/{artifact_id}/metadata")
    def artifact(artifact_id: str): return required(store.get_artifact(artifact_id), "artifact")

    @app.get("/v1/artifacts/{artifact_id}/content")
    def artifact_content(artifact_id: str):
        artifact = required(store.get_artifact(artifact_id), "artifact")
        return FileResponse(artifact["path"], media_type=artifact["content_type"])

    return app


app = create_app()
