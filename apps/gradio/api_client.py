"""HTTP client boundary for migrating callbacks away from Jules.

PLACEHOLDER: callbacks in the legacy root app are migrated tab-by-tab. New callbacks
must use this client rather than import control-plane or worker implementations.
"""
import json
import os
from pathlib import Path
import tempfile
import time

import requests


def normalize_personas(personas):
    """Normalize Gradio JSON values without treating mapping keys as profiles."""
    if personas in (None, ""):
        return []
    if isinstance(personas, str):
        try:
            personas = json.loads(personas)
        except json.JSONDecodeError as error:
            raise ValueError("Personas must be a JSON array or profile object.") from error
    if isinstance(personas, dict):
        nested = personas.get("personas", personas.get("items"))
        personas = nested if isinstance(nested, list) else [personas]
    if not isinstance(personas, list):
        raise ValueError("Personas must be a JSON array or profile object.")
    normalized = []
    for index, item in enumerate(personas):
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError as error:
                raise ValueError(f"Persona {index + 1} is not a JSON object.") from error
        if not isinstance(item, dict):
            raise ValueError(f"Persona {index + 1} must be a JSON object.")
        normalized.append(item)
    return normalized


class ControlPlaneClient:
    def __init__(self, base_url: str | None = None, workspace_id: str | None = None, user_id: str | None = None, authorization: str | None = None):
        self.base_url = (base_url or os.getenv("CONTROL_PLANE_URL", "http://localhost:8000")).rstrip("/")
        self.headers = {"X-Workspace-ID": workspace_id or os.getenv("WORKSPACE_ID", "local"), "X-User-ID": user_id or os.getenv("OWNER_USER_ID", "local")}
        authorization = authorization or os.getenv("CONTROL_PLANE_AUTHORIZATION")
        if authorization: self.headers["Authorization"] = authorization

    def me(self):
        response = requests.get(f"{self.base_url}/v1/me", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def create_session(self, metadata=None):
        response = requests.post(f"{self.base_url}/v1/sessions", headers=self.headers, json={"metadata": metadata or {}}, timeout=30)
        response.raise_for_status()
        return response.json()

    def list_sessions(self):
        response = requests.get(f"{self.base_url}/v1/sessions", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()["items"]

    def list_artifacts(self, session_id):
        response = requests.get(f"{self.base_url}/v1/sessions/{session_id}/artifacts", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()["items"]

    def list_jobs(self, session_id):
        response = requests.get(f"{self.base_url}/v1/sessions/{session_id}/jobs", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()["items"]

    def discover_legacy(self, repository):
        response = requests.get(f"{self.base_url}/v1/legacy/github/branches", headers=self.headers, params={"repository": repository}, timeout=30)
        response.raise_for_status()
        return response.json()["items"]

    def import_legacy(self, repository, branch):
        response = requests.post(f"{self.base_url}/v1/legacy/github/import", headers=self.headers, json={"repository": repository, "branch": branch}, timeout=120)
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

    def download_artifact(self, artifact):
        response = requests.get(f"{self.base_url}/v1/artifacts/{artifact['artifact_id']}/content",
                                headers=self.headers, timeout=120)
        response.raise_for_status()
        name = artifact.get("metadata", {}).get("download_name") or f"{artifact['artifact_id']}.bin"
        directory = Path(tempfile.mkdtemp(prefix="aux-download-"))
        path = directory / Path(name).name
        path.write_bytes(response.content)
        return str(path)

    def create_artifact(self, session_id, kind, content, content_type="application/json", metadata=None, retention_class="structured"):
        response = requests.post(f"{self.base_url}/v1/artifacts", headers=self.headers, json={"session_id": session_id, "kind": kind, "content_type": content_type, "content": content, "metadata": metadata or {}, "retention_class": retention_class}, timeout=30)
        response.raise_for_status()
        return response.json()

    def run_job(self, job_type, metadata, session_id=None, idempotency_key=None):
        session_id = session_id or self.create_session(metadata={"source": "gradio"})["session_id"]
        job = self.create_job({"session_id": session_id, "type": job_type, "metadata": metadata, "idempotency_key": idempotency_key})
        return self.wait_for_job(job["job_id"])


class PersonaRuntimeClient:
    def __init__(self, base_url: str | None = None, workspace_id: str | None = None, user_id: str | None = None, authorization: str | None = None):
        self.base_url = (base_url or os.getenv("PERSONA_RUNTIME_URL", "http://localhost:8090")).rstrip("/")
        self.headers = {"X-Workspace-ID": workspace_id or os.getenv("WORKSPACE_ID", "local"), "X-User-ID": user_id or os.getenv("OWNER_USER_ID", "local")}
        authorization = authorization or os.getenv("PERSONA_AUTHORIZATION") or (f"Bearer {os.environ['HF_OIDC_TOKEN']}" if os.getenv("HF_OIDC_TOKEN") else None)
        if authorization: self.headers["Authorization"] = authorization

    def generate(self, theme, customer_profile, count, scenario="", seed=1, allow_offline_fallback=False):
        response = requests.post(f"{self.base_url}/v1/personas/generate", headers=self.headers, json={"theme": theme, "customer_profile": customer_profile, "count": int(count), "scenario": scenario, "seed": int(seed), "allow_offline_fallback": bool(allow_offline_fallback)}, timeout=float(os.getenv("PERSONA_GENERATION_TIMEOUT", "900")))
        response.raise_for_status()
        return response.json()

    def list(self, limit=50):
        response = requests.get(f"{self.base_url}/v1/personas", headers=self.headers, params={"limit": int(limit)}, timeout=30)
        response.raise_for_status()
        return response.json()

    def get(self, persona_id):
        response = requests.get(f"{self.base_url}/v1/personas/{persona_id}", headers=self.headers, timeout=30)
        response.raise_for_status()
        return response.json()

    def update(self, profile):
        response = requests.patch(f"{self.base_url}/v1/personas/{profile['id']}", headers=self.headers, json={"persona": profile}, timeout=30)
        response.raise_for_status()
        return response.json()
