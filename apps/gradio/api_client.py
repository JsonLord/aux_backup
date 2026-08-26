"""HTTP client boundary for migrating callbacks away from Jules.

PLACEHOLDER: callbacks in the legacy root app are migrated tab-by-tab. New callbacks
must use this client rather than import control-plane or worker implementations.
"""
import os
import time

import requests


class ControlPlaneClient:
    def __init__(self, base_url: str | None = None, workspace_id: str | None = None, user_id: str | None = None):
        self.base_url = (base_url or os.getenv("CONTROL_PLANE_URL", "http://localhost:8000")).rstrip("/")
        self.headers = {"X-Workspace-ID": workspace_id or os.getenv("WORKSPACE_ID", "local"), "X-User-ID": user_id or os.getenv("OWNER_USER_ID", "local")}

    def create_session(self, metadata=None):
        response = requests.post(f"{self.base_url}/v1/sessions", headers=self.headers, json={"metadata": metadata or {}}, timeout=30)
        response.raise_for_status()
        return response.json()

    def create_job(self, payload):
        response = requests.post(f"{self.base_url}/v1/jobs", headers=self.headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()

    def get_job(self, job_id):
        response = requests.get(f"{self.base_url}/v1/jobs/{job_id}", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def wait_for_job(self, job_id, timeout=300, poll_interval=1):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.get_job(job_id)
            if job["status"] in {"succeeded", "failed", "cancelled"}:
                return job
            time.sleep(poll_interval)
        raise TimeoutError(f"job {job_id} did not finish within {timeout}s")

    def get_artifact_content(self, artifact_id):
        response = requests.get(f"{self.base_url}/v1/artifacts/{artifact_id}/content", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.text

    def run_job(self, job_type, metadata, session_id=None, idempotency_key=None):
        session_id = session_id or self.create_session(metadata={"source": "gradio"})["session_id"]
        job = self.create_job({"session_id": session_id, "type": job_type, "metadata": metadata, "idempotency_key": idempotency_key})
        return self.wait_for_job(job["job_id"])


class PersonaRuntimeClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.getenv("PERSONA_RUNTIME_URL", "http://localhost:8090")).rstrip("/")

    def generate(self, theme, customer_profile, count, scenario="", seed=1):
        response = requests.post(f"{self.base_url}/v1/personas/generate", json={"theme": theme, "customer_profile": customer_profile, "count": int(count), "scenario": scenario, "seed": int(seed)}, timeout=120)
        response.raise_for_status()
        return response.json()

    def update(self, profile):
        response = requests.patch(f"{self.base_url}/v1/personas/{profile['id']}", json={"persona": profile}, timeout=30)
        response.raise_for_status()
        return response.json()
