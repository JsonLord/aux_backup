"""Local job executor implementing useful control-plane behavior without Jules.

The interface intentionally keeps execution behind persisted jobs and artifacts so a
JourneyTest worker can replace this development executor without changing clients.
"""
from __future__ import annotations

from html import escape
import json
import os
from typing import Any
from urllib import request

from .store import Store


class JobExecutor:
    def __init__(self, store: Store):
        self.store = store

    def run(self, job_id: str) -> None:
        job = self.store.claim_job(job_id)
        if not job:
            return
        dependencies = [self.store.get_job(item) for item in job["depends_on"]]
        if any(item is None or item["status"] != "succeeded" for item in dependencies):
            self.store.update_job(job_id, "waiting_on_dependency")
            self.store.event(job_id, "job.waiting_on_dependency", 0, {"depends_on": job["depends_on"]})
            return
        self.store.start_attempt(job_id, job["attempt"])
        self.store.event(job_id, "job.started", .05, {"attempt": job["attempt"]})
        try:
            if job["type"] == "combined_test":
                result = self._combined_test(job)
                kind, content_type = "ux.report", "application/json"
            elif job["type"] == "ui_adaptation":
                result = self._ui_adaptation(job)
                kind, content_type = "ui.prototype", "text/html"
            else:
                raise ValueError(f"unsupported job type: {job['type']}")
            artifact = self.store.create_artifact({"session_id": job["session_id"], "kind": kind, "content_type": content_type, "content": result, "metadata": {"job_id": job_id, "schema_version": "1.0"}})
            self.store.update_job(job_id, "running", output_artifacts=[artifact["artifact_id"]])
            self.store.event(job_id, "artifact.created", .95, {"artifact_id": artifact["artifact_id"], "kind": kind})
            self.store.finish_attempt(job_id, job["attempt"], "succeeded")
            self.store.event(job_id, "job.succeeded", 1, {"output_artifacts": [artifact["artifact_id"]]})
            self._resume_dependents(job_id)
        except Exception as exc:
            error = {"code": "execution_failed", "message": str(exc), "retryable": False}
            self.store.finish_attempt(job_id, job["attempt"], "failed", error)
            self.store.event(job_id, "job.failed", 1, {"error": error})

    def _resume_dependents(self, completed_job_id: str) -> None:
        for waiting in self.store.waiting_jobs(completed_job_id):
            dependencies = [self.store.get_job(item) for item in waiting["depends_on"]]
            if dependencies and all(item and item["status"] == "succeeded" for item in dependencies):
                self.store.update_job(waiting["job_id"], "queued")
                self.store.event(waiting["job_id"], "job.dependencies_satisfied", 0, {"depends_on": waiting["depends_on"]})
                self.run(waiting["job_id"])

    def _combined_test(self, job: dict[str, Any]) -> dict[str, Any]:
        data = job["metadata"]
        persona_artifacts, tasks = data.get("persona_artifacts", []), data.get("tasks", [])
        personas = []
        for artifact_id in persona_artifacts:
            artifact = self.store.get_artifact(artifact_id)
            if not artifact or artifact["session_id"] != job["session_id"] or artifact["kind"] != "persona.profile":
                raise ValueError(f"invalid persona profile artifact: {artifact_id}")
            personas.append(json.loads(self.store.read_artifact(artifact_id)))
        if not personas or not tasks:
            raise ValueError("combined_test requires persona profile artifacts and non-empty metadata.tasks")
        journeys = []
        worker_url = os.getenv("JOURNEY_WORKER_URL")
        if worker_url:
            for persona in personas:
                payload = json.dumps({"runId": f"{job['job_id']}_{persona.get('id', len(journeys))}", "url": data.get("url"), "tasks": tasks, "profile": persona}).encode()
                call = request.Request(f"{worker_url.rstrip('/')}/v1/runs", data=payload, headers={"content-type": "application/json"}, method="POST")
                with request.urlopen(call, timeout=120) as response:
                    journeys.append(json.loads(response.read()))
        findings = [{"severity": "medium", "title": f"Validate task clarity: {task}", "evidence": "Inferred from the configured task; browser evidence is pending JourneyTest integration."} for task in tasks]
        return {"schema_version": "1.0", "mode": "user_journey", "url": data.get("url"), "executive_summary": f"Prepared {len(tasks)} task scenarios for {len(personas)} synthetic users.", "synthetic_users": personas, "persona_artifacts": persona_artifacts, "journey_outcome": {"status": "simulated" if journeys else "configured", "tasks": tasks, "runs": journeys}, "critical_pain_points": findings, "evidence_language": "inferred", "limitations": ["PLACEHOLDER: live JourneyTest browser evidence is not yet connected."]}

    def _ui_adaptation(self, job: dict[str, Any]) -> str:
        data = job["metadata"]
        title = escape(data.get("title", "Responsive UX prototype"))
        request = escape(data.get("request", "Improve clarity and responsiveness"))
        return f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><style>body{{font:16px system-ui;margin:auto;max-width:72rem;padding:clamp(1rem,4vw,4rem);color:#18202a}}main{{display:grid;gap:1rem}}section{{padding:1.5rem;border:1px solid #ccd5df;border-radius:1rem}}@media(min-width:48rem){{main{{grid-template-columns:2fr 1fr}}}}</style></head><body><h1>{title}</h1><main><section><h2>Adaptation request</h2><p>{request}</p></section><section><h2>Accessible by default</h2><p>Responsive layout, semantic landmarks, and readable contrast.</p></section></main></body></html>"""
