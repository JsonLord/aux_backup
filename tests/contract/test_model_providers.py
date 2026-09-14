"""One provider resolution, used everywhere it is needed.

The same resolution existed three times -- generator.py for live generation,
dspy_program.py for compilation, app.py for readiness. A fallback was added to
the first, and cycle 28 failed anyway on the copy that had not been touched:
persona *compilation* went through dspy_program, which still reached for an
endpoint that was not there.
"""

import os

import pytest

from services.persona_service.providers import model_providers, unreachable, why


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_COMPATIBLE_ENDPOINT", "OPENAI_BASE_URL",
                 "BLABLADOR_API_KEY", "BLABLADOR_BASE_URL", "BLABLADOR_MODEL",
                 "BLABLADOR_FALLBACK_MODEL", "JOURNEY_REFLECT_BASE_URL",
                 "JOURNEY_REFLECT_API_KEY", "JOURNEY_REFLECT_MODEL"):
        monkeypatch.delenv(name, raising=False)


def test_generation_falls_back_to_a_large_model_then_a_larger_one(monkeypatch):
    """Writing a person is a big, infrequent job. alias-fast is chosen for
    reflection precisely because it is cheap and frequent, which makes it the wrong
    tool here."""
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT", "https://router.example/v1")
    monkeypatch.setenv("JOURNEY_REFLECT_BASE_URL", "https://blablador.example/v1")
    monkeypatch.setenv("JOURNEY_REFLECT_API_KEY", "k2")
    monkeypatch.setenv("JOURNEY_REFLECT_MODEL", "alias-fast")

    assert model_providers() == [
        ("https://router.example/v1", "k1", "auto"),
        ("https://blablador.example/v1", "k2", "alias-large"),
        ("https://blablador.example/v1", "k2", "alias-huge"),
    ]


def test_two_aliases_on_one_host_are_two_providers(monkeypatch):
    """Deduplicating on the endpoint alone would silently drop the second of them,
    leaving a chain that looks like a fallback and has none.

    A deployment with only Blablador configured also resolves its "primary" to the
    Blablador endpoint -- and must not then be handed the router's model id.
    "auto" is the router's word; Blablador serves named models and answers 404 to
    it on every persona compile. The endpoint decides the model, not the variable
    the endpoint happened to arrive in.
    """
    monkeypatch.setenv("BLABLADOR_API_KEY", "k")
    monkeypatch.setenv("BLABLADOR_BASE_URL", "https://blablador.example/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    chain = model_providers()
    assert [url for url, _, _ in chain] == ["https://blablador.example/v1"] * 2
    assert [model for _, _, model in chain] == ["alias-large", "alias-huge"]
    assert "auto" not in [model for _, _, model in chain]


def test_a_router_deployment_still_leads_with_auto(monkeypatch):
    """The router requires the literal id "auto" and 400s on anything else."""
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT", "https://router.example/v1")

    assert model_providers()[0] == ("https://router.example/v1", "k1", "auto")


def test_an_endpoint_with_no_key_is_not_a_provider(monkeypatch):
    """A model, an endpoint and a key are one setting. Naming an alias without its
    token is a 401 on every call, which is worse than having no fallback: it looks
    like one."""
    monkeypatch.setenv("OPENAI_API_KEY", "k1")
    monkeypatch.setenv("OPENAI_COMPATIBLE_ENDPOINT", "https://router.example/v1")
    monkeypatch.setenv("BLABLADOR_BASE_URL", "https://blablador.example/v1")

    assert [url for url, _, _ in model_providers()] == ["https://router.example/v1"]


def test_nothing_configured_offers_nothing(monkeypatch):
    assert model_providers() == []


def test_only_a_request_that_never_arrived_moves_a_run():
    """A 400 or a refusal is the provider answering. Asking a different one the same
    bad question spends a second budget on the same failure."""
    assert unreachable(Exception("Failed to resolve 'router.example'"))
    assert unreachable(Exception("[Errno 101] Network is unreachable"))
    assert unreachable(Exception("connect ECONNREFUSED 10.0.0.1:443"))
    assert unreachable(Exception("APIConnectionError: Connection error."))

    assert not unreachable(Exception("400 model_not_found"))
    assert not unreachable(Exception("401 Unauthorized"))
    assert not unreachable(Exception("429 rate limit exceeded"))
    assert not unreachable(None)


def test_the_real_cause_is_reported_when_it_is_one_level_down():
    inner = Exception("getaddrinfo EAI_AGAIN blablador.example")
    outer = Exception("compilation failed")
    outer.__cause__ = inner

    assert unreachable(outer), "the wrapper says nothing; the cause says everything"
    assert "EAI_AGAIN" in why(outer)
    # Depth-bounded and cycle-safe: a self-referential chain must not hang.
    looped = Exception("outer")
    looped.__cause__ = looped
    assert why(looped) == "outer"


def test_the_service_resolves_providers_in_exactly_one_place():
    """The guard that would have caught cycles 28 and 29 before they were fired.

    Naming the modules by hand is what let this miss twice: the guard listed
    generator, compiler and dspy_program, and the path that actually runs is
    semantic.py -- PERSONA_COMPILER defaults to "native", so dspy never executes
    at all. So it walks the package instead of a list somebody has to remember to
    extend.
    """
    import importlib
    import inspect
    import pkgutil
    import re

    import services.persona_service as package

    modules = []
    for info in pkgutil.iter_modules(package.__path__):
        if info.name in {"providers", "main"}:
            continue
        modules.append(importlib.import_module(f"services.persona_service.{info.name}"))
    assert any(module.__name__.endswith("semantic") for module in modules), \
        "the module that actually compiles a persona must be covered"

    offenders = []
    for module in modules:
        try:
            source = inspect.getsource(module)
        except OSError:  # pragma: no cover - namespace package
            continue
        for number, line in enumerate(source.splitlines(), start=1):
            if line.strip().startswith("#") or '"""' in line:
                continue
            if re.search(r'getenv\(\s*["\'](OPENAI_COMPATIBLE_ENDPOINT|OPENAI_BASE_URL'
                         r'|BLABLADOR_BASE_URL|BLABLADOR_API_KEY)["\']', line):
                offenders.append(f"{module.__name__}:{number}: {line.strip()[:80]}")
    assert not offenders, (
        "provider resolution belongs in providers.py only; a second copy is how "
        "cycle 28 failed:\n" + "\n".join(offenders))
