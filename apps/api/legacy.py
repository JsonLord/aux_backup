"""Read-only GitHub compatibility adapter for the one-release migration window."""
from __future__ import annotations

import base64
import os
import re
from typing import Any
from urllib.parse import quote

import requests


REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ALLOWED_SUFFIXES = (".md", ".json", ".html", ".png", ".jpg", ".jpeg", ".webm")


class LegacyGitHubSessionProvider:
    """Reads legacy artifacts without preserving legacy branch writes."""

    def __init__(self, token: str | None = None, api_url: str = "https://api.github.com"):
        self.token = token or os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_API_TOKEN")
        self.api_url = api_url.rstrip("/")

    @property
    def headers(self):
        headers = {"accept": "application/vnd.github+json", "x-github-api-version": "2022-11-28"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        return headers

    def _repo(self, repository: str) -> str:
        if not REPOSITORY.fullmatch(repository):
            raise ValueError("repository must be formatted as owner/name")
        return repository

    def list_branches(self, repository: str) -> list[dict[str, Any]]:
        repository = self._repo(repository)
        response = requests.get(f"{self.api_url}/repos/{repository}/branches", headers=self.headers, params={"per_page": 100}, timeout=30)
        response.raise_for_status()
        return [{"name": item["name"], "commit_sha": item["commit"]["sha"], "read_only": True} for item in response.json()]

    def read_artifacts(self, repository: str, branch: str) -> list[dict[str, Any]]:
        repository = self._repo(repository)
        tree = requests.get(f"{self.api_url}/repos/{repository}/git/trees/{quote(branch, safe='')}", headers=self.headers, params={"recursive": "1"}, timeout=30)
        tree.raise_for_status()
        candidates = [item for item in tree.json().get("tree", []) if item.get("type") == "blob" and item["path"].startswith("user_experience_reports/") and item["path"].lower().endswith(ALLOWED_SUFFIXES)]
        if len(candidates) > 100:
            raise ValueError("legacy branch exceeds the 100-artifact import limit")
        artifacts = []
        total_bytes = 0
        for item in candidates:
            blob = requests.get(item["url"], headers=self.headers, timeout=30)
            blob.raise_for_status()
            data = blob.json()
            content = base64.b64decode(data["content"]) if data.get("encoding") == "base64" else data.get("content", "").encode()
            total_bytes += len(content)
            if total_bytes > 25 * 1024 * 1024:
                raise ValueError("legacy import exceeds the 25 MB ingestion limit")
            artifacts.append({"path": item["path"], "content": content, "sha": item.get("sha")})
        return artifacts
