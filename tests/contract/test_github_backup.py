import pytest
import requests

from apps.gradio.github_backup import (
    GitHubAuthError,
    push_file,
    push_session_to_github,
    validate_and_list_repos,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.exceptions.HTTPError(f"{self.status_code}")

    def json(self):
        return self._payload


def test_validate_and_list_repos_rejects_bad_token(monkeypatch):
    monkeypatch.setattr("apps.gradio.github_backup.requests.get", lambda *a, **k: FakeResponse(status_code=401))

    with pytest.raises(GitHubAuthError, match="rejected"):
        validate_and_list_repos("bad-token")


def test_validate_and_list_repos_requires_a_token():
    with pytest.raises(GitHubAuthError, match="required"):
        validate_and_list_repos("")


def test_validate_and_list_repos_only_returns_push_access_repos(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/user"):
            return FakeResponse({"login": "octocat"})
        if params["page"] == 1:
            return FakeResponse([
                {"full_name": "octocat/pushable", "permissions": {"push": True}},
                {"full_name": "octocat/read-only", "permissions": {"push": False}},
            ] * 50)  # 100 entries -> triggers a second page fetch
        return FakeResponse([])

    monkeypatch.setattr("apps.gradio.github_backup.requests.get", fake_get)

    username, repos = validate_and_list_repos("fixture-token")

    assert username == "octocat"
    assert repos == ["octocat/pushable"] * 50
    assert "octocat/read-only" not in repos


def test_push_file_creates_new_file_without_sha(monkeypatch):
    monkeypatch.setattr("apps.gradio.github_backup.requests.get", lambda *a, **k: FakeResponse(status_code=404))
    captured = {}

    def fake_put(url, headers=None, json=None, timeout=None):
        captured["url"], captured["json"] = url, json
        return FakeResponse({"content": {"sha": "new-sha"}})

    monkeypatch.setattr("apps.gradio.github_backup.requests.put", fake_put)

    push_file("token", "octocat/repo", "sessions/s1/report.json", b'{"a":1}', "aux: sync")

    assert "sha" not in captured["json"]
    assert captured["url"].endswith("/repos/octocat/repo/contents/sessions/s1/report.json")


def test_push_file_updates_existing_file_with_sha(monkeypatch):
    monkeypatch.setattr("apps.gradio.github_backup.requests.get", lambda *a, **k: FakeResponse({"sha": "old-sha"}))
    captured = {}

    def fake_put(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return FakeResponse({})

    monkeypatch.setattr("apps.gradio.github_backup.requests.put", fake_put)

    push_file("token", "octocat/repo", "sessions/s1/report.json", b"content", "aux: sync")

    assert captured["json"]["sha"] == "old-sha"


class FakeSessionClient:
    def __init__(self, artifacts, contents):
        self._artifacts = artifacts
        self._contents = contents

    def list_artifacts(self, session_id):
        return self._artifacts

    def get_artifact_content(self, artifact_id):
        return self._contents[artifact_id]


def test_push_session_to_github_pushes_known_kinds_and_skips_others(monkeypatch):
    artifacts = [
        {"artifact_id": "art_report", "kind": "ux.report", "metadata": {}},
        {"artifact_id": "art_persona", "kind": "persona.profile", "metadata": {"persona_id": "persona_1"}},
        {"artifact_id": "art_screenshot", "kind": "browser.screenshot", "metadata": {}},
    ]
    contents = {"art_report": '{"ok":true}', "art_persona": '{"id":"persona_1"}'}
    client = FakeSessionClient(artifacts, contents)
    pushed_paths = []

    monkeypatch.setattr("apps.gradio.github_backup.push_file",
                        lambda pat, repo, path, content_bytes, message: pushed_paths.append(path))

    result = push_session_to_github("token", "octocat/repo", "ses_1", client)

    assert result["pushed"] == ["sessions/ses_1/report.json", "sessions/ses_1/personas/persona_1.json"]
    assert result["errors"] == []
    assert pushed_paths == result["pushed"]


def test_push_session_to_github_collects_errors_without_aborting(monkeypatch):
    artifacts = [
        {"artifact_id": "art_report", "kind": "ux.report", "metadata": {}},
        {"artifact_id": "art_slides", "kind": "ux.slides", "metadata": {}},
    ]
    contents = {"art_report": "{}", "art_slides": "<html></html>"}
    client = FakeSessionClient(artifacts, contents)

    def failing_push_file(pat, repo, path, content_bytes, message):
        if "report" in path:
            raise requests.exceptions.RequestException("rate limited")
        return {"content": {"sha": "ok"}}

    monkeypatch.setattr("apps.gradio.github_backup.push_file", failing_push_file)

    result = push_session_to_github("token", "octocat/repo", "ses_1", client)

    assert result["pushed"] == ["sessions/ses_1/slides.html"]
    assert len(result["errors"]) == 1
    assert "report.json" in result["errors"][0]
