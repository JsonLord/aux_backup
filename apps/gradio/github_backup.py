"""Per-user GitHub backup of workspace session reports/artifacts/persona sheets.

Bring-your-own-PAT flow: the token is supplied live by the signed-in user for
each sync and is kept only in the browser session's Gradio state -- it is
never written to the control-plane's persistent store (see
docs/aux-space-status-overview.md). This is distinct from the persona pool's
read-only, "always-connected" service credential (services/persona_service/
github_pool.py), which is a separate, shared, pull-only integration.
"""
from __future__ import annotations

import base64

import requests

GITHUB_API = "https://api.github.com"
_TIMEOUT = 15

_ARTIFACT_KIND_FILENAMES = {
    "ux.report": "report.json",
    "ux.presentation": "presentation.html",
    "ux.slides": "slides.html",
    "journey.log": "journey-log.json",
}


class GitHubAuthError(Exception):
    """The supplied token was rejected or lacks the access this feature needs."""


def _headers(pat: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def validate_and_list_repos(pat: str) -> tuple[str, list[str]]:
    """Validate a user-supplied GitHub PAT and return (username, [repo full_names])
    the token can push to."""
    if not pat:
        raise GitHubAuthError("A GitHub personal access token is required.")
    user_response = requests.get(f"{GITHUB_API}/user", headers=_headers(pat), timeout=_TIMEOUT)
    if user_response.status_code == 401:
        raise GitHubAuthError("GitHub rejected this token (invalid or expired).")
    user_response.raise_for_status()
    username = user_response.json()["login"]

    repos, page = [], 1
    while page <= 10:  # 1000 repos is far more than any workspace backup needs; avoids unbounded pagination
        response = requests.get(f"{GITHUB_API}/user/repos", headers=_headers(pat),
                                params={"per_page": 100, "page": page, "affiliation": "owner,collaborator"}, timeout=_TIMEOUT)
        response.raise_for_status()
        batch = response.json()
        repos.extend(repo["full_name"] for repo in batch if repo.get("permissions", {}).get("push"))
        if len(batch) < 100:
            break
        page += 1
    return username, repos


def confirm_backup_repo(pat: str, repo_full_name: str) -> dict:
    """Verify that this exact repo can actually receive a backup, and describe it.

    Listing repos with push access (validate_and_list_repos) is a snapshot taken at
    connect time; it does not prove the chosen one is still writable now, and it
    says nothing about a repo being archived -- GitHub accepts the token, lists the
    repo with push permission, and then rejects every write to it. Checking the one
    repo the user is committing to is what makes "fixed for backup" a statement
    about reality rather than about a dropdown.
    """
    if not pat:
        raise GitHubAuthError("Connect GitHub first.")
    if not repo_full_name:
        raise GitHubAuthError("Choose a repository first.")
    response = requests.get(f"{GITHUB_API}/repos/{repo_full_name}", headers=_headers(pat), timeout=_TIMEOUT)
    if response.status_code == 401:
        raise GitHubAuthError("GitHub rejected this token (invalid or expired).")
    if response.status_code in (403, 404):
        raise GitHubAuthError(f"`{repo_full_name}` is not reachable with this token. "
                              "Check the token still grants it **Contents: Read and write**.")
    response.raise_for_status()
    repo = response.json()
    if not repo.get("permissions", {}).get("push"):
        raise GitHubAuthError(f"This token can read `{repo_full_name}` but cannot write to it. "
                              "It needs **Contents: Read and write**.")
    if repo.get("archived"):
        raise GitHubAuthError(f"`{repo_full_name}` is archived, so GitHub will reject every write to it.")
    return {"full_name": repo["full_name"], "default_branch": repo.get("default_branch") or "main",
            "private": bool(repo.get("private")), "html_url": repo.get("html_url") or f"https://github.com/{repo_full_name}"}


def _existing_file_sha(pat: str, repo_full_name: str, path: str) -> str | None:
    response = requests.get(f"{GITHUB_API}/repos/{repo_full_name}/contents/{path}", headers=_headers(pat), timeout=_TIMEOUT)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json().get("sha")


def push_file(pat: str, repo_full_name: str, path: str, content_bytes: bytes, message: str) -> dict:
    sha = _existing_file_sha(pat, repo_full_name, path)
    body = {"message": message, "content": base64.b64encode(content_bytes).decode("ascii")}
    if sha:
        body["sha"] = sha
    response = requests.put(f"{GITHUB_API}/repos/{repo_full_name}/contents/{path}", headers=_headers(pat), json=body, timeout=30)
    response.raise_for_status()
    return response.json()


def push_session_to_github(pat: str, repo_full_name: str, session_id: str, session_client) -> dict:
    """Push a workspace session's report/presentation/slides/journey-log/persona
    artifacts to `repo_full_name` under sessions/<session_id>/..., using the
    signed-in user's own PAT. Returns {"pushed": [paths], "errors": [messages]}."""
    artifacts = session_client.list_artifacts(session_id)
    pushed, errors = [], []
    for artifact in artifacts:
        kind = artifact["kind"]
        if kind in _ARTIFACT_KIND_FILENAMES:
            path = f"sessions/{session_id}/{_ARTIFACT_KIND_FILENAMES[kind]}"
        elif kind == "persona.profile":
            persona_id = artifact.get("metadata", {}).get("persona_id") or artifact["artifact_id"]
            path = f"sessions/{session_id}/personas/{persona_id}.json"
        else:
            continue
        try:
            content = session_client.get_artifact_content(artifact["artifact_id"])
            content_bytes = content.encode("utf-8") if isinstance(content, str) else content
            push_file(pat, repo_full_name, path, content_bytes, message=f"aux: sync {kind} for session {session_id}")
            pushed.append(path)
        except requests.exceptions.RequestException as error:
            errors.append(f"{path}: {error}")
    return {"pushed": pushed, "errors": errors}
