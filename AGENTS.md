# Development Continuation Guide

## Approach

Treat `spec.md` as the architectural contract and deliver it in the numbered stages in section 29. Keep service implementations isolated: communicate only through versioned HTTP contracts, job IDs, and persisted artifact references. Preserve the legacy Gradio tabs while moving callbacks incrementally to `apps/gradio/api_client.py`; do not add new Jules-backed flows. Mark partial implementations explicitly with `PLACEHOLDER`.

## Progress overview (2026-08-26)

- Stage 0 started: canonical top-level monorepo directories, Python 3.12 control-plane image, Node 24 Journey worker image, and local Compose definition exist.
- The previously imported Eyeson source remains in `services/eyeson-engine`; migration into the target TypeScript worker boundary is not complete.
- Stage 1 advanced: persistent SQLite development sessions, jobs, ordered events, idempotency keys, cancellation/retry state transitions, attempt records, structured failures, deletion/result endpoints, artifact files/metadata, SSE replay, health/readiness, and service-version endpoints exist.
- The root Gradio application remains operational and has not yet been decomposed. Its Analysis Orchestrator and prototype/adaptation callbacks now use `apps/gradio/api_client.py` and persisted control-plane jobs rather than Jules.
- A local in-process executor now produces versioned `ux.report` JSON and responsive `ui.prototype` HTML artifacts. The report explicitly labels its findings as inferred until JourneyTest supplies observed browser evidence.
- A versioned, workspace-scoped persona runtime now generates distinct, seed-reproducible offline synthetic-user profiles, compiles normalized behavior priors at the semantic boundary, exposes manual profile updates, and preserves neutral functional abilities rather than inferring restrictions from demographics. The pinned TinyTroupe runtime path uses public serialization but still needs package-level validation; DSPy remains gated behind parity evaluation.
- The Journey worker now owns a native deterministic `BehaviorController`, emits experience/state/coping events, and accepts full simulation profiles through `/v1/runs`. Its journeytest-core browser-library call remains a `PLACEHOLDER` pending the pinned fork decision.
- The preserved Gradio register includes a Persona Studio tab with full profile inspection, behavior/ability tweak controls, and persistence through the persona runtime HTTP API.
- Migration Phase 2 integration is implemented: workspace-scoped profiles survive SQLite/PostgreSQL restarts, selected profiles become immutable artifacts, the Journey worker receives the exact snapshots, and reports/live monitoring render them. Formal completion awaits the pinned TinyTroupe package test in a network-enabled Python 3.12 environment; see `docs/stage-2-audit.md`.
- Dependency baselines are resolved: TinyTroupe v0.7.0 is pinned to upstream commit `a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4`, JourneyTest is pinned to `@baguette-studios/journeytest-core@0.1.2` / commit `9139d581fc6a882257ea4c46bdf16d59547c0ae5`, and the root Docker image no longer clones or patches the obsolete TinyTroupe fork or installs Jules.
- The semantic compiler boundary now selects the direct OpenAI-compatible Blablador `alias-huge` baseline when credentials are present and a deterministic mock in CI/offline environments. DSPy stays gated behind parity evaluation.
- Stage 1 production-adapter implementation is complete: PostgreSQL/Alembic, Redis/Celery execution and retention, verified HF OIDC roles/service credentials, R2 storage/presigned multipart flows, Compose services, and a production-stack acceptance test exist. Formal acceptance remains pending execution of that test in a Docker-enabled runner; see `docs/stage-1-audit.md`.
- Read-only legacy GitHub branch discovery/import now ingests bounded historical report/evidence artifacts into tenant-owned sessions without rerunning or writing to GitHub. Local artifacts now receive 30/180-day expiration metadata, support pinning, and can be swept when expired.
- Jules is no longer in the root application's runtime path. Historical MCP helpers, connectivity scripts, API notes, templates, and imported upstream references still need archival or removal.

## Open questions

1. Should the canonical repository be renamed from `aux_backup` to `aux`, and what migration date should clients use?
2. Resolved: DSPy uses `dspy==3.3.0` and canonical wheel SHA-256 `358cbfb15d13246dc4a289bb2350c0ee602260c8a3869f7f63a48a9d2233e48c`; do not install `dspy-ai` or upgrade during parity evaluation.

## Next implementation slice

### Stage 1 production-adapter completion

Run the production-stack acceptance test in a Docker-enabled runner, including one
forced Celery worker termination/redelivery. If it passes, record Stage 1 as accepted
and move to the parallel acceptance work below. If it fails, fix the adapter rather
than adding another boundary or fallback.

### Stage 2 persona-generation integration

Stage 2's environment-independent integration work is complete. In a network-enabled
Python 3.12 build with model credentials, run
`RUN_TINY_TROUPE_ACCEPTANCE=1 pytest -q tests/integration/test_tinytroupe_runtime.py`.
Confirm which public TinyPerson serialization method is available, whether the pinned
factory accepts the seed parameter, and that two generated normalized profiles are
distinct. Fix the adapter if the test fails; Stage 2 closes when it passes. Keep the
offline generator explicitly labeled as a fallback.

### Parallel acceptance work after the Stage 1 adapter path is runnable

- Inspect the pinned JourneyTest package in a network-enabled Node 24 build and
  replace fixture observations with browser screenshots, semantic snapshots, video,
  and UI-change evidence through `/v1/runs`.
- Human-review all 100 `semantic_parity_v1.jsonl` candidates, generate and commit the
  Python 3.12 `uv.lock`, then run the frozen direct-versus-DSPy 3.3.0 parity report.
  DSPy must not become the default before that report is approved.
