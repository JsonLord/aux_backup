# Development Continuation Guide

## Approach

Treat `spec.md` as the architectural contract and deliver it in the numbered stages in section 29. Keep service implementations isolated: communicate only through versioned HTTP contracts, job IDs, and persisted artifact references. Preserve the legacy Gradio tabs while moving callbacks incrementally to `apps/gradio/api_client.py`; do not add new Jules-backed flows. Mark partial implementations explicitly with `PLACEHOLDER`.

## Progress overview (2026-08-26)

- Stage 0 started: canonical top-level monorepo directories, Python 3.12 control-plane image, Node 24 Journey worker image, and local Compose definition exist.
- The previously imported Eyeson source remains in `services/eyeson-engine`; migration into the target TypeScript worker boundary is not complete.
- Stage 1 advanced: persistent SQLite development sessions, jobs, ordered events, idempotency keys, cancellation/retry state transitions, attempt records, structured failures, deletion/result endpoints, artifact files/metadata, SSE replay, health/readiness, and service-version endpoints exist.
- The root Gradio application remains operational and has not yet been decomposed. Its Analysis Orchestrator and prototype/adaptation callbacks now use `apps/gradio/api_client.py` and persisted control-plane jobs rather than Jules.
- A local in-process executor now produces versioned `ux.report` JSON and responsive `ui.prototype` HTML artifacts. The report explicitly labels its findings as inferred until JourneyTest supplies observed browser evidence.
- A versioned persona runtime now generates distinct, seed-reproducible full synthetic-user profiles, compiles normalized behavior priors at the DSPy boundary, exposes manual profile updates, and preserves neutral functional abilities rather than inferring restrictions from demographics. TinyTroupe and DSPy package execution remain explicitly gated until exact versions and model configuration are approved.
- The Journey worker now owns a native deterministic `BehaviorController`, emits experience/state/coping events, and accepts full simulation profiles through `/v1/runs`. Its journeytest-core browser-library call remains a `PLACEHOLDER` pending the pinned fork decision.
- The preserved Gradio register includes a Persona Studio tab with full profile inspection, behavior/ability tweak controls, and persistence through the persona runtime HTTP API.
- Dependency baselines are resolved: TinyTroupe v0.7.0 is pinned to upstream commit `a6244b358a1fe1c71bf751f7ba0f8dfa368ec5a4`, JourneyTest is pinned to `@baguette-studios/journeytest-core@0.1.2` / commit `9139d581fc6a882257ea4c46bdf16d59547c0ae5`, and the root Docker image no longer clones or patches the obsolete TinyTroupe fork or installs Jules.
- The semantic compiler boundary now selects the direct OpenAI-compatible Blablador `alias-huge` baseline when credentials are present and a deterministic mock in CI/offline environments. DSPy stays gated behind parity evaluation.
- Stage 1 audit result: not complete. Local workspace attribution/isolation, workspace-prefixed artifact paths, and dependency rescheduling now work and have contract coverage. PostgreSQL/Alembic, Redis/Celery durability, verified HF OIDC/workspace membership, and R2/presigned uploads remain required; see `docs/stage-1-audit.md`.
- Read-only legacy GitHub branch discovery/import now ingests bounded historical report/evidence artifacts into tenant-owned sessions without rerunning or writing to GitHub. Local artifacts now receive 30/180-day expiration metadata, support pinning, and can be swept when expired.
- Jules is no longer in the root application's runtime path. Historical MCP helpers, connectivity scripts, API notes, templates, and imported upstream references still need archival or removal.

## Open questions

1. Should the canonical repository be renamed from `aux_backup` to `aux`, and what migration date should clients use?
2. Which exact DSPy release and distribution hash should be pinned before parity evaluation begins?

## Next implementation slice

Close Stage 1 by adding Alembic/PostgreSQL, Redis/Celery, verified HF OIDC/workspace membership, and the R2/presigned-upload adapter with durable retention scheduling. Wire legacy session discovery/import into Report Viewer, then migrate Live Monitoring. In parallel, inspect JourneyTest in a network-enabled build and replace simulated observations with verified browser evidence through the existing worker contract. Build the 100-example reviewed semantic parity corpus before allowing DSPy to become default.
