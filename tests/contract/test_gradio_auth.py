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


def test_expired_sign_in_reads_as_a_prompt_not_a_traceback():
    """A Hugging Face OAuth token expires while the tab stays open, so the saved-report
    tabs' list_sessions()/list_artifacts() calls start returning 401 long after sign-in
    appeared to succeed. In production that surfaced as a raw
    `requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url:
    http://127.0.0.1:8000/v1/sessions/.../artifacts` traceback in the UI."""
    import requests

    import app as gradio_app

    def http_error(status):
        response = requests.Response()
        response.status_code = status
        return requests.exceptions.HTTPError(f"{status} Client Error", response=response)

    assert "sign in" in gradio_app.workspace_access_message(http_error(401)).lower()
    assert "sign in" in gradio_app.workspace_access_message(http_error(403)).lower()
    assert "500" in gradio_app.workspace_access_message(http_error(500))
    assert "unreachable" in gradio_app.workspace_access_message(
        requests.exceptions.ConnectionError("connection refused"))
    assert "Sign in with Hugging Face to continue" in gradio_app.workspace_access_message(
        PermissionError("Sign in with Hugging Face to continue"))


def test_github_connection_sits_in_the_header_beside_the_hugging_face_sign_in():
    """Connecting GitHub is the same act as signing in -- attaching an account to
    the workspace -- and the token must be re-entered after every page reload
    because it is never stored server-side. Buried in the GitHub Backup tab it was
    a control a returning user had to go looking for."""
    import gradio as gr

    import app as gradio_app

    def ancestry(component):
        names, node = [], component
        while getattr(node, "parent", None) is not None:
            node = node.parent
            names.append(type(node).__name__)
        return names

    components = list(gradio_app.demo.blocks.values())
    token = next(c for c in components
                 if isinstance(c, gr.Textbox) and (c.label or "").startswith("GitHub token"))
    repo = next(c for c in components
                if isinstance(c, gr.Dropdown) and c.label == "Backup repository")
    workspace = next(c for c in components
                     if isinstance(c, gr.Dropdown) and c.label == "Workspace")

    # In the header, not inside any tab -- the same place the Workspace selector is.
    for component in (token, repo):
        assert "Tab" not in ancestry(component), ancestry(component)
        assert ancestry(component)[-1] == ancestry(workspace)[-1] == "Blocks"
    # The token is a secret, not free text.
    assert token.type == "password"
    # Exactly one place to enter it; the backup tab no longer defines its own.
    assert sum(1 for c in components
               if isinstance(c, gr.Textbox) and "GitHub" in (c.label or "")) == 1
