from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path
from typing import Any

DSPY_VERSION = "3.3.0"
DSPY_WHEEL_SHA256 = "358cbfb15d13246dc4a289bb2350c0ee602260c8a3869f7f63a48a9d2233e48c"
PROGRAM_VERSION = "semantic-parity-v1"


def load_reviewed_corpus(path: str | Path) -> list[dict[str, Any]]:
    examples = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line]
    if len(examples) != 100:
        raise ValueError("semantic parity requires exactly 100 examples")
    pending = [item["id"] for item in examples if item.get("review_status") != "approved"]
    if pending:
        raise ValueError(f"semantic parity corpus has {len(pending)} unapproved examples")
    return examples


def run_metadata(corpus_path: str | Path, uv_lock_path: str | Path) -> dict[str, Any]:
    corpus = Path(corpus_path)
    lock = Path(uv_lock_path)
    return {
        "dspy_package": DSPY_VERSION,
        "dspy_wheel_sha256": DSPY_WHEEL_SHA256,
        "python": platform.python_version(),
        "uv_lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
        "dspy_program_version": PROGRAM_VERSION,
        "evaluation_set": corpus.name,
        "evaluation_set_sha256": hashlib.sha256(corpus.read_bytes()).hexdigest(),
        "direct_baseline": "DirectLLMSemanticEngine/auto",
    }
