"""HTTP client boundary for migrating callbacks away from Jules.

PLACEHOLDER: callbacks in the legacy root app are migrated tab-by-tab. New callbacks
must use this client rather than import control-plane or worker implementations.
"""
import os
import requests

class ControlPlaneClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.getenv("CONTROL_PLANE_URL", "http://localhost:8000")).rstrip("/")

    def create_session(self, metadata=None):
        response = requests.post(f"{self.base_url}/v1/sessions", json={"metadata": metadata or {}}, timeout=30)
        response.raise_for_status()
        return response.json()

    def create_job(self, payload):
        response = requests.post(f"{self.base_url}/v1/jobs", json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
