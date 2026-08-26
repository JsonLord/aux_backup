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
    assert metadata["direct_baseline"] == "DirectLLMSemanticEngine/alias-huge"
