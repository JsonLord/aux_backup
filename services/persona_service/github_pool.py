"""Read-only client for the GitHub-backed persona pool (docs/persona-pool-plan.md).

Component A/C of that plan: a dedicated GitHub repository holding pre-generated
SyntheticUserProfile JSON files plus a manifest (index.json), read here through
an "always-connected", read-only service credential (PERSONA_POOL_GITHUB_TOKEN)
distinct from any individual user's own GitHub PAT. Component B (the scheduled
GitHub Actions generation workflow) is out of scope for this client -- it only
reads whatever the pool repo currently holds.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
from typing import Any

import requests

BEHAVIOR_FIELDS = (
    "patience", "persistence", "irritability", "angerReactivity", "angerRecovery",
    "impulsivity", "ambiguityTolerance", "failureTolerance", "repeatFailureTolerance",
    "selfEfficacy", "digitalConfidence", "helpSeeking", "exploration",
    "verificationTendency", "riskTolerance",
)

_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "who",
    "that", "this", "are", "is", "be", "as", "at", "by", "from", "their", "they",
    "who's", "into", "your", "you", "our", "we", "it", "its", "was", "were",
}


class PersonaPoolConfig:
    def __init__(self, repo: str, token: str | None = None):
        self.repo = repo  # "owner/name"
        self.token = token

    @classmethod
    def from_env(cls) -> "PersonaPoolConfig | None":
        repo = os.getenv("PERSONA_POOL_GITHUB_REPO")
        if not repo:
            return None
        return cls(repo, os.getenv("PERSONA_POOL_GITHUB_TOKEN"))


class GitHubPersonaPoolClient:
    def __init__(self, config: PersonaPoolConfig, ttl_seconds: float = 300.0, session: requests.Session | None = None):
        self.config = config
        self.ttl_seconds = ttl_seconds
        self.session = session or requests.Session()
        self._index_cache: tuple[float, list[dict]] | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        return headers

    def _get_content(self, path: str) -> bytes:
        url = f"https://api.github.com/repos/{self.config.repo}/contents/{path}"
        response = self.session.get(url, headers=self._headers(), timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("encoding") != "base64":
            raise ValueError(f"unexpected encoding for {path}: {payload.get('encoding')}")
        return base64.b64decode(payload["content"])

    def fetch_index(self, force: bool = False) -> list[dict]:
        now = time.monotonic()
        if not force and self._index_cache is not None and (now - self._index_cache[0]) < self.ttl_seconds:
            return self._index_cache[1]
        try:
            raw = self._get_content("index.json")
        except requests.exceptions.HTTPError as error:
            if error.response is not None and error.response.status_code == 404:
                entries: list[dict] = []
                self._index_cache = (now, entries)
                return entries
            raise
        entries = json.loads(raw.decode("utf-8"))
        if not isinstance(entries, list):
            raise ValueError("index.json must be a JSON array")
        self._index_cache = (now, entries)
        return entries

    def fetch_persona(self, path: str) -> dict[str, Any]:
        raw = self._get_content(path)
        return json.loads(raw.decode("utf-8"))


def _keywords(text: str | None) -> set[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return {word for word in words if len(word) > 2 and word not in _STOPWORDS}


def _entry_keywords(entry: dict) -> set[str]:
    tags = {str(tag).lower() for tag in (entry.get("themeTags") or [])}
    return tags | _keywords(entry.get("summary")) | _keywords(entry.get("name"))


def _textual_distance(entry: dict, theme: str, customer_profile: str) -> float:
    request_kw = _keywords(theme) | _keywords(customer_profile)
    entry_kw = _entry_keywords(entry)
    if not request_kw or not entry_kw:
        return 1.0
    union = request_kw | entry_kw
    if not union:
        return 1.0
    return 1.0 - (len(request_kw & entry_kw) / len(union))


def _trait_distance(entry: dict, behavior_targets: dict[str, float] | None) -> float:
    if not behavior_targets:
        return 0.0
    behavior = entry.get("behavior") or {}
    diffs = [
        abs(float(behavior[field]) - float(target))
        for field, target in behavior_targets.items()
        if field in behavior and isinstance(behavior[field], (int, float))
    ]
    return sum(diffs) / len(diffs) if diffs else 0.0


def _combined_distance(entry: dict, theme: str, customer_profile: str, behavior_targets: dict[str, float] | None) -> float:
    textual = _textual_distance(entry, theme, customer_profile)
    trait = _trait_distance(entry, behavior_targets)
    trait_weight = 0.5 if behavior_targets else 0.0
    return (1.0 - trait_weight) * textual + trait_weight * trait


def _trait_vector_distance(a: dict, b: dict) -> float:
    a_behavior, b_behavior = a.get("behavior") or {}, b.get("behavior") or {}
    diffs = [
        (float(a_behavior[field]) - float(b_behavior[field])) ** 2
        for field in BEHAVIOR_FIELDS
        if field in a_behavior and field in b_behavior
    ]
    return sum(diffs) ** 0.5 if diffs else 0.0


def select_pool_group(
    entries: list[dict],
    theme: str,
    customer_profile: str,
    count: int,
    behavior_targets: dict[str, float] | None = None,
) -> list[dict]:
    """Pick `count` pool entries as the closest-ranged, diversified group.

    Per docs/persona-pool-plan.md section 4 point 3: not the `count` individually
    nearest entries (which can cluster near one point), but a diversified sample
    drawn from the smallest bounding range of nearest candidates -- score every
    entry, take the top-K nearest as that bounding range, then greedily add the
    entry farthest (in trait space) from what's already selected.
    """
    if not entries or count <= 0:
        return []
    scored = sorted(
        ((entry, _combined_distance(entry, theme, customer_profile, behavior_targets)) for entry in entries),
        key=lambda pair: pair[1],
    )
    top_k = max(count * 3, 8)
    candidates = scored[:top_k]
    if len(candidates) <= count:
        return [entry for entry, _ in candidates]

    selected = [candidates[0][0]]
    remaining = candidates[1:]
    while len(selected) < count and remaining:
        best_index, best_separation = 0, -1.0
        for index, (entry, _distance) in enumerate(remaining):
            separation = min(_trait_vector_distance(entry, chosen) for chosen in selected)
            if separation > best_separation:
                best_index, best_separation = index, separation
        selected.append(remaining.pop(best_index)[0])
    return selected
