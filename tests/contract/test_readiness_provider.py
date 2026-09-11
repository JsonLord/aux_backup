"""Readiness has to be able to say the model is not answering.

`liveExecutionReady` was computed from `bool(os.getenv("OPENAI_API_KEY"))` -- the
presence of a string in the environment. Every other dependency in that endpoint
gets a real round trip to /healthz; the one thing no run can proceed without got
a truthiness test.

So the Space reported `status: ready`, `personaRuntime: ok`,
`liveExecutionReady: true` through four consecutive cycles in which it could not
compile a single persona, and the first anyone knew was a 500 from a workflow
call. A check that cannot fail is not a check.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
import requests


def load_app_module():
    path = Path("app.py")
    spec = importlib.util.spec_from_file_location("aux_app_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def readiness_probe(monkeypatch):
    """The provider probe alone, with the environment it actually reads."""
    module = pytest.importorskip("app") if "app" in sys.modules else load_app_module()
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key")
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT", "https://router.example/v1")
    return module


def test_a_key_in_the_environment_is_not_a_provider_that_answers(readiness_probe, monkeypatch):
    calls = []

    def refuse(url, **kwargs):
        calls.append((url, kwargs))
        raise requests.ConnectionError("HTTPSConnectionPool(host='router.example'): fetch failed")

    monkeypatch.setattr(requests, "get", refuse)
    probe = readiness_probe.build_model_provider_probe()

    result = probe()
    assert result["status"] == "unreachable"
    assert result["endpoint"] == "https://router.example", "the host, never the key"
    assert "fetch failed" in result["error"]
    # It asked the discovery route, which costs no tokens.
    assert calls[0][0] == "https://router.example/v1/models"
    # And it sent the key where the key already goes, and nowhere else.
    assert calls[0][1]["headers"] == {"authorization": "Bearer not-a-real-key"}


def test_the_reported_endpoint_never_carries_the_key(readiness_probe, monkeypatch):
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT",
                       "https://router.example/v1?api_key=secret-in-a-query-string")

    def refuse(url, **kwargs):
        raise requests.ConnectionError("nope")

    monkeypatch.setattr(requests, "get", refuse)
    result = readiness_probe.build_model_provider_probe()()

    assert "secret-in-a-query-string" not in str(result)
    assert result["endpoint"] == "https://router.example"


def test_a_provider_that_answers_is_reported_ok_and_asked_once(readiness_probe, monkeypatch):
    calls = []

    class Answered:
        def raise_for_status(self):
            return None

    def answer(url, **kwargs):
        calls.append(url)
        return Answered()

    monkeypatch.setattr(requests, "get", answer)
    probe = readiness_probe.build_model_provider_probe()

    assert probe()["status"] == "ok"
    # Readiness is polled. A round trip to the model on every poll would be both
    # slow and rude, so the answer is held briefly.
    assert probe()["status"] == "ok"
    assert len(calls) == 1, "the second poll reuses the first answer"


def test_no_key_configured_says_so_rather_than_reporting_a_dead_endpoint(readiness_probe, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("BLABLADOR_API_KEY", raising=False)

    def never_called(url, **kwargs):  # pragma: no cover
        raise AssertionError("there is nothing to ask with")

    monkeypatch.setattr(requests, "get", never_called)
    result = readiness_probe.build_model_provider_probe()()

    assert result["status"] == "unconfigured"
    assert "OPENAI_API_KEY" in result["error"]
