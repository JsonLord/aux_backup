import base64
import importlib.util
import json
from functools import lru_cache
from pathlib import Path

import pytest
import requests
from fastapi.testclient import TestClient

from services.persona_service import main as persona_main
from services.persona_service.github_pool import (
    GitHubPersonaPoolClient,
    PersonaPoolConfig,
    _textual_distance,
    _trait_distance,
    select_pool_group,
)


@lru_cache(maxsize=1)
def load_root_app():
    path = Path(__file__).parents[2] / "app.py"
    spec = importlib.util.spec_from_file_location("aux_root_app", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.exceptions.HTTPError(f"{self.status_code}")
            error.response = self
            raise error

    def json(self):
        return self._payload


def _content_response(data: dict):
    return FakeResponse({"encoding": "base64", "content": base64.b64encode(json.dumps(data).encode()).decode()})


# --- scoring/selection (docs/persona-pool-plan.md section 4) ---

def test_textual_distance_prefers_overlapping_theme_keywords():
    checkout_entry = {"themeTags": ["checkout", "ecommerce"], "summary": "Busy shopper checking out"}
    onboarding_entry = {"themeTags": ["onboarding", "saas"], "summary": "New user setting up an account"}

    checkout_distance = _textual_distance(checkout_entry, "checkout flow", "busy online shoppers")
    onboarding_distance = _textual_distance(onboarding_entry, "checkout flow", "busy online shoppers")

    assert checkout_distance < onboarding_distance


def test_trait_distance_is_zero_without_targets_and_measures_gap_with_targets():
    entry = {"behavior": {"patience": 0.2, "riskTolerance": 0.9}}

    assert _trait_distance(entry, None) == 0.0
    assert _trait_distance(entry, {"patience": 0.2}) == 0.0
    assert _trait_distance(entry, {"patience": 0.9}) == pytest.approx(0.7)


def test_select_pool_group_returns_closest_ranged_diversified_set():
    entries = [
        {"path": f"p{i}.json", "themeTags": ["checkout"], "summary": "checkout",
         "behavior": {"patience": value, "riskTolerance": value}}
        for i, value in enumerate([0.1, 0.15, 0.2, 0.8, 0.85, 0.9])
    ]

    selected = select_pool_group(entries, "checkout", "shoppers", count=2)

    assert len(selected) == 2
    # A diversified pick should not be two near-duplicate low-patience entries.
    patiences = sorted(entry["behavior"]["patience"] for entry in selected)
    assert patiences[1] - patiences[0] > 0.05


def test_select_pool_group_returns_everything_when_pool_smaller_than_request():
    entries = [{"path": "p1.json", "behavior": {}}]
    assert select_pool_group(entries, "checkout", "shoppers", count=5) == entries


def test_select_pool_group_handles_empty_pool():
    assert select_pool_group([], "checkout", "shoppers", count=3) == []


# --- GitHubPersonaPoolClient ---

def test_pool_client_fetches_index_and_persona_via_contents_api(monkeypatch):
    calls = []

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            calls.append(url)
            if url.endswith("/contents/index.json"):
                return _content_response([{"path": "personas/p1.json"}])
            return _content_response({"id": "persona_seed1", "source": "preset"})

    client = GitHubPersonaPoolClient(PersonaPoolConfig("jsonlord/PersonaPool", "fixture-token"), session=FakeSession())

    index = client.fetch_index()
    persona = client.fetch_persona("personas/p1.json")

    assert index == [{"path": "personas/p1.json"}]
    assert persona["id"] == "persona_seed1"
    assert any("index.json" in url for url in calls)
    assert any("personas/p1.json" in url for url in calls)


def test_pool_client_caches_index_within_ttl(monkeypatch):
    calls = {"count": 0}

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            calls["count"] += 1
            return _content_response([])

    client = GitHubPersonaPoolClient(PersonaPoolConfig("jsonlord/PersonaPool"), ttl_seconds=300, session=FakeSession())
    client.fetch_index()
    client.fetch_index()

    assert calls["count"] == 1


def test_pool_client_treats_missing_index_as_empty_pool():
    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            return FakeResponse({}, status_code=404)

    client = GitHubPersonaPoolClient(PersonaPoolConfig("jsonlord/PersonaPool"), session=FakeSession())
    assert client.fetch_index() == []


# --- /v1/personas/pool-lookup endpoint ---

def test_pool_lookup_endpoint_reports_unconfigured_when_no_pool_client(monkeypatch):
    monkeypatch.setattr(persona_main, "pool_client", None)
    api = TestClient(persona_main.app)

    response = api.post("/v1/personas/pool-lookup", json={"theme": "checkout", "customer_profile": "shoppers", "count": 2})

    assert response.status_code == 200
    assert response.json() == {"poolConfigured": False, "personas": [], "requested": 2, "matched": 0}


def test_pool_lookup_endpoint_mints_fresh_workspace_local_id(monkeypatch):
    persona_main.profiles.clear()

    class FakePoolClient:
        config = PersonaPoolConfig("jsonlord/PersonaPool")

        def fetch_index(self):
            return [{"path": "personas/p1.json", "themeTags": ["checkout"], "summary": "checkout", "behavior": {}}]

        def fetch_persona(self, path):
            behavior = {"seed": 1, "patience": .5, "persistence": .5, "irritability": .5,
                        "angerReactivity": .5, "angerRecovery": .5, "impulsivity": .5,
                        "ambiguityTolerance": .5, "failureTolerance": .5, "repeatFailureTolerance": .5,
                        "selfEfficacy": .5, "digitalConfidence": .5, "helpSeeking": .5,
                        "exploration": .5, "verificationTendency": .5, "riskTolerance": .5}
            return {"id": "persona_original_pool_id", "source": "preset",
                    "persona": {"name": "Pool Persona"}, "abilities": {}, "behavior": behavior, "generation": {}}

    monkeypatch.setattr(persona_main, "pool_client", FakePoolClient())
    api = TestClient(persona_main.app)

    response = api.post("/v1/personas/pool-lookup", json={"theme": "checkout", "customer_profile": "shoppers", "count": 1})

    assert response.status_code == 200
    body = response.json()
    assert body["poolConfigured"] is True
    assert body["matched"] == 1
    minted = body["personas"][0]
    assert minted["id"] != "persona_original_pool_id"
    assert minted["generation"]["poolSource"] == {"repo": "jsonlord/PersonaPool", "path": "personas/p1.json"}
    assert persona_main.profiles.get_for_workspace(minted["id"], "local")["id"] == minted["id"]


# --- app.py's PersonaPool branch (real pool lookup, fallback to generation) ---

class FakePersonaClient:
    def __init__(self, pool_personas, configured=True, lookup_error=None):
        self.pool_personas = pool_personas
        self.configured = configured
        self.lookup_error = lookup_error
        self.generate_calls = []

    def pool_lookup(self, theme, customer_profile, count, behavior_targets=None):
        if self.lookup_error:
            raise self.lookup_error
        matched = self.pool_personas[:count]
        return {"poolConfigured": self.configured, "personas": list(matched), "requested": count, "matched": len(matched)}

    def generate(self, theme, customer_profile, count, scenario=""):
        self.generate_calls.append(count)
        return [{"id": f"gen_{index}", "source": "tinytroupe"} for index in range(count)]


def test_persona_pool_branch_uses_pool_then_fills_shortfall_with_generation():
    app_module = load_root_app()
    fake = FakePersonaClient([{"id": "pool_1", "source": "preset"}])

    result = app_module.select_or_create_personas("checkout", "busy shoppers", 3, force_method="PersonaPool", persona_client=fake)

    assert [persona["id"] for persona in result] == ["pool_1", "gen_0", "gen_1"]
    assert fake.generate_calls == [2]


def test_persona_pool_branch_falls_back_entirely_when_unconfigured():
    app_module = load_root_app()
    fake = FakePersonaClient([], configured=False)

    result = app_module.select_or_create_personas("checkout", "busy shoppers", 2, force_method="PersonaPool", persona_client=fake)

    assert [persona["id"] for persona in result] == ["gen_0", "gen_1"]
    assert fake.generate_calls == [2]


def test_persona_pool_branch_falls_back_when_lookup_raises():
    app_module = load_root_app()
    fake = FakePersonaClient([], lookup_error=requests.exceptions.RequestException("pool unreachable"))

    result = app_module.select_or_create_personas("checkout", "busy shoppers", 2, force_method="PersonaPool", persona_client=fake)

    assert [persona["id"] for persona in result] == ["gen_0", "gen_1"]
    assert fake.generate_calls == [2]


def test_persona_pool_branch_uses_pool_alone_when_fully_covered():
    app_module = load_root_app()
    fake = FakePersonaClient([{"id": "pool_1"}, {"id": "pool_2"}])

    result = app_module.select_or_create_personas("checkout", "busy shoppers", 2, force_method="PersonaPool", persona_client=fake)

    assert [persona["id"] for persona in result] == ["pool_1", "pool_2"]
    assert fake.generate_calls == []
