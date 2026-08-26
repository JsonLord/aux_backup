# Development Continuation Guide

## Approach

Treat `spec.md` as the architectural contract and deliver it in the numbered stages in section 29. Keep service implementations isolated: communicate only through versioned HTTP contracts, job IDs, and persisted artifact references. Preserve the legacy Gradio tabs while moving callbacks incrementally to `apps/gradio/api_client.py`; do not add new Jules-backed flows. Mark partial implementations explicitly with `PLACEHOLDER`.

## Progress overview (2026-08-26)

- Stage 0 started: canonical top-level monorepo directories, Python 3.12 control-plane image, Node 24 Journey worker image, and local Compose definition exist.
- The previously imported Eyeson source remains in `services/eyeson-engine`; migration into the target TypeScript worker boundary is not complete.
- Stage 1 started: persistent SQLite development sessions, jobs, ordered events, idempotency keys, cancellation/retry state transitions, artifact files/metadata, SSE replay, health/readiness, and service-version endpoints exist.
- The root Gradio application remains operational and has not yet been decomposed. A control-plane API client boundary is ready for callback migration.
- Jules code is legacy-only now: the new canonical backend does not call Jules, but remaining root `app.py` callbacks still need migration before Jules can be deleted.

## Open questions

1. Should the canonical repository be renamed from `aux_backup` to `aux`, and what migration date should clients use?
2. Which exact TinyTroupe commit and JourneyTest package version/fork should be pinned?
3. Is PostgreSQL + Redis/Celery the confirmed production choice, and what deployment provides them on Hugging Face Spaces?
4. Which existing Gradio flows must be migrated first, and must old GitHub-branch sessions remain readable?
5. May the imported Eyeson directory be moved outright, or must its Git history/provenance remain as a subtree?
6. What auth/tenant model protects session and artifact APIs?
7. What artifact retention, maximum upload size, and S3-compatible provider are required?
8. Which semantic model/provider is the supported direct-LLM baseline, and what labeled data will evaluate DSPy parity?

## Next implementation slice

Finish Stage 1 with PostgreSQL migrations, a durable Redis queue/worker, attempt records, dependency scheduling, structured failure results, deletion/result endpoints, and concurrency tests. Then migrate the Analysis Orchestrator callback to create `combined_test` jobs through the API without changing the visible tab register.
