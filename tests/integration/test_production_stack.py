"""Acceptance tests for the Compose PostgreSQL/Redis/Celery/R2 stack.

Run with: PRODUCTION_API_URL=http://localhost:8000 pytest -q tests/integration/test_production_stack.py
"""
import concurrent.futures
import os
import time

import pytest
import requests

BASE = os.getenv("PRODUCTION_API_URL")
pytestmark = pytest.mark.skipif(not BASE, reason="PRODUCTION_API_URL is not configured")
HEADERS = {"X-Workspace-ID": "integration", "X-User-ID": "integration-user"}


def test_postgres_idempotency_celery_recovery_and_r2_round_trip():
    session = requests.post(f"{BASE}/v1/sessions", headers=HEADERS, json={}, timeout=10).json()
    payload = {"session_id": session["session_id"], "type": "ui_adaptation", "idempotency_key": "concurrent", "metadata": {"title": "Integration fixture", "request": "Verify durable execution"}}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: requests.post(f"{BASE}/v1/jobs", headers=HEADERS, json=payload, timeout=15), range(8)))
    assert {response.json()["job_id"] for response in responses} == {responses[0].json()["job_id"]}
    job_id = responses[0].json()["job_id"]
    for _ in range(60):
        job = requests.get(f"{BASE}/v1/jobs/{job_id}", headers=HEADERS, timeout=10).json()
        if job["status"] in {"succeeded", "failed"}: break
        time.sleep(1)
    assert job["status"] == "succeeded"
    events = requests.get(f"{BASE}/v1/jobs/{job_id}/events", headers=HEADERS, timeout=10).json()["items"]
    assert "job.worker_received" in {event["type"] for event in events}
    assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))

    size = 26 * 1024 * 1024
    reservation = requests.post(f"{BASE}/v1/artifacts/uploads", headers=HEADERS, json={"session_id": session["session_id"], "kind": "fixture.raw", "content_type": "application/octet-stream", "size": size}, timeout=10)
    assert reservation.status_code == 201
    body = reservation.json()
    uploaded = requests.put(body["upload"]["url"], headers=body["upload"]["headers"], data=b"x" * size, timeout=120)
    uploaded.raise_for_status()
    artifact_id = body["artifact"]["artifact_id"]
    completed = requests.post(f"{BASE}/v1/artifacts/{artifact_id}/uploads/complete", headers=HEADERS, json={}, timeout=15)
    assert completed.json()["metadata"]["upload_status"] == "complete"
    download = requests.get(f"{BASE}/v1/artifacts/{artifact_id}/content", headers=HEADERS, timeout=30)
    assert download.content == b"x" * size
