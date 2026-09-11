import json

import pytest

from services.persona_service.parity import load_reviewed_corpus, run_metadata


def test_corpus_has_100_candidates_and_review_gate():
    path = "tests/fixtures/semantic_parity_v1.jsonl"
    rows = [json.loads(line) for line in open(path, encoding="utf-8")]
    assert len(rows) == 100
    assert len({row["id"] for row in rows}) == 100
    with pytest.raises(ValueError, match="100 unapproved"):
        load_reviewed_corpus(path)


def test_parity_metadata_records_freeze_point(tmp_path):
    lock = tmp_path / "uv.lock"
    lock.write_text("fixture lock")
    metadata = run_metadata("tests/fixtures/semantic_parity_v1.jsonl", lock)
    assert metadata["dspy_package"] == "3.3.0"
    assert len(metadata["uv_lock_sha256"]) == 64
    assert metadata["direct_baseline"] == "DirectLLMSemanticEngine/auto"


def test_the_endpoint_and_the_model_are_one_setting(monkeypatch):
    """The regression this exists for, found on the deployed Space.

    BLABLADOR_BASE_URL used to default to the primary router's URL, so the
    endpoint and the model id always agreed by accident. Once Blablador became a
    real second endpoint, this engine kept taking the endpoint from
    BLABLADOR_BASE_URL and the model from OPENAI_MODEL -- sending "auto", which
    only the primary router has, to Blablador, which answered 404 on every
    persona compile. The start script pairs them; nothing made the code pair
    them, and a start-script assertion cannot catch a third consumer.
    """
    from services.persona_service.semantic import DirectLLMSemanticEngine

    for name in ("SEMANTIC_BASE_URL", "SEMANTIC_MODEL", "SEMANTIC_API_KEY",
                 "OPENAI_BASE_URL", "OPENAI_COMPATIBLE_ENDPOINT", "OPENAI_MODEL",
                 "OPENAI_API_KEY", "BLABLADOR_BASE_URL", "BLABLADOR_MODEL",
                 "BLABLADOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    # Both endpoints configured, which is how the Space runs. The primary wins,
    # and "auto" goes to the router that has it.
    monkeypatch.setenv("OPENAI_BASE_URL", "https://router.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "auto")
    monkeypatch.setenv("OPENAI_API_KEY", "primary")
    monkeypatch.setenv("BLABLADOR_BASE_URL", "https://blablador.test/v1")
    monkeypatch.setenv("BLABLADOR_API_KEY", "secondary")
    engine = DirectLLMSemanticEngine()
    assert engine.base_url == "https://router.test/v1"
    assert engine.model == "auto"
    assert engine.api_key == "primary", "and the key travels with its own endpoint"


def test_a_blablador_only_deployment_does_not_ask_it_for_auto(monkeypatch):
    """The legacy shape. Blablador serves specific small models by name and has
    no "auto", so defaulting the model to "auto" there is a guaranteed 404."""
    from services.persona_service.semantic import DirectLLMSemanticEngine

    for name in ("SEMANTIC_BASE_URL", "SEMANTIC_MODEL", "SEMANTIC_API_KEY",
                 "OPENAI_BASE_URL", "OPENAI_COMPATIBLE_ENDPOINT", "OPENAI_MODEL",
                 "OPENAI_API_KEY", "BLABLADOR_BASE_URL", "BLABLADOR_MODEL",
                 "BLABLADOR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BLABLADOR_BASE_URL", "https://blablador.test/v1")
    monkeypatch.setenv("BLABLADOR_API_KEY", "secondary")

    engine = DirectLLMSemanticEngine()
    assert engine.base_url == "https://blablador.test/v1"
    assert engine.model != "auto"
    assert engine.model == "alias-fast"

    # And a named model there is honoured.
    monkeypatch.setenv("BLABLADOR_MODEL", "alias-large")
    assert DirectLLMSemanticEngine().model == "alias-large"
