"""HF OAuth workspace acceptance against deployed APIs.

Requires CONTROL_PLANE_URL, HF_USER_A_TOKEN, and HF_USER_B_TOKEN.
"""
import os

import pytest
import requests

BASE = os.getenv("CONTROL_PLANE_URL")
TOKEN_A = os.getenv("HF_USER_A_TOKEN")
TOKEN_B = os.getenv("HF_USER_B_TOKEN")
pytestmark = pytest.mark.skipif(not all((BASE, TOKEN_A, TOKEN_B)), reason="deployed HF OAuth credentials are not configured")


def headers(token, workspace=None):
    result = {"Authorization": f"Bearer {token}"}
    if workspace: result["X-Workspace-ID"] = workspace
    return result


def test_native_users_and_workspace_selection_are_isolated():
    me_a = requests.get(f"{BASE}/v1/me", headers=headers(TOKEN_A), timeout=20).json()
    me_b = requests.get(f"{BASE}/v1/me", headers=headers(TOKEN_B), timeout=20).json()
    personal_a, personal_b = me_a["selected_workspace_id"], me_b["selected_workspace_id"]
    assert personal_a.startswith("hf:user:") and personal_a != personal_b
    session = requests.post(f"{BASE}/v1/sessions", headers=headers(TOKEN_A, personal_a), json={}, timeout=20).json()
    assert requests.get(f"{BASE}/v1/sessions/{session['session_id']}", headers=headers(TOKEN_B, personal_b), timeout=20).status_code == 404
    assert requests.get(f"{BASE}/v1/sessions/{session['session_id']}", headers=headers(TOKEN_A, "hf:org:forged"), timeout=20).status_code == 403


def test_postgres_rls_blocks_cross_workspace_sql():
    database_url = os.getenv("PRODUCTION_DATABASE_URL")
    if not database_url: pytest.skip("PRODUCTION_DATABASE_URL is not configured")
    import psycopg
    with psycopg.connect(database_url.replace("postgresql+psycopg://", "postgresql://", 1)) as db:
        db.execute("SELECT set_config('app.workspace_id', %s, false)", ("hf:user:not-owner",))
        assert db.execute("SELECT session_id FROM sessions").fetchall() == []
