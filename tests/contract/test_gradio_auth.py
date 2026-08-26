from types import SimpleNamespace

import pytest

from apps.gradio.auth import request_identity, workspaces_from_profile


PROFILE = {"sub": "user-1", "name": "Ada", "preferred_username": "ada", "orgs": [{"sub": "org-1", "name": "Research", "roleInOrg": "write"}, {"sub": "blocked", "name": "Blocked", "securityRestrictions": ["mfa"]}]}


def test_space_profile_builds_namespaced_authorized_workspaces():
    assert [item["id"] for item in workspaces_from_profile(PROFILE)] == ["hf:user:user-1", "hf:org:org-1"]
    identity = request_identity(PROFILE, SimpleNamespace(token="oauth-token"), "hf:org:org-1")
    assert identity.authorization == "Bearer oauth-token"
    assert identity.user_id == "user-1"


def test_space_profile_rejects_forged_workspace_selection():
    with pytest.raises(PermissionError):
        request_identity(PROFILE, SimpleNamespace(token="oauth-token"), "hf:org:other")
