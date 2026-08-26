# Semantic parity freeze point

The parity candidate is the actual `dspy` package at version `3.3.0`; `dspy-ai` is
forbidden. The normative distribution is `dspy-3.3.0-py3-none-any.whl`, SHA-256
`358cbfb15d13246dc4a289bb2350c0ee602260c8a3869f7f63a48a9d2233e48c`.
Dependencies must be frozen by a repository `uv.lock` and must not change during the
first direct-versus-DSPy evaluation. **PLACEHOLDER:** generate and commit that lock in
a network-enabled Python 3.12 build; the current environment could not reach PyPI.
The normative wheel itself can be checked independently with
`pip download --no-deps --require-hashes -r services/persona_service/dspy-artifact.lock`.

`semantic_parity_v1.jsonl` contains 100 structurally complete candidates. They are
deliberately marked `pending`: a human reviewer must approve every example before
`load_reviewed_corpus` permits an evaluation. This prevents generated fixtures from
being misrepresented as a reviewed benchmark. Every result must include the metadata
returned by `services.persona_service.parity.run_metadata`.
