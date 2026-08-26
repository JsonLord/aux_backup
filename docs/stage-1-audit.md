# Stage 1 completion audit

Date: 2026-08-26

## Result

**Stage 1 implementation is complete; production-stack validation is pending.** The
runtime adapters, Compose topology, and acceptance test now exist. This environment
does not provide Docker, so the production-stack test has not run here and Stage 1
must not be marked accepted until it passes in a Docker-enabled runner.

## Complete

- Persistent local sessions, jobs, attempts, ordered events and artifact metadata.
- Idempotent creation, structured failures, cancellation/retry transitions, result
  and deletion endpoints, and SSE replay.
- Workspace and owner attribution on sessions, jobs and artifacts.
- Workspace authorization at every session/job/artifact HTTP endpoint.
- Workspace/session-prefixed filesystem artifact keys.
- Dependency waiting and automatic rescheduling after all prerequisites succeed.
- Read-only legacy GitHub discovery/import with bounded artifact ingestion.
- Local raw/structured expiration dates, artifact pinning and retention sweeping.
- Contract coverage for tenant isolation, dependency scheduling and persistence.
- Alembic-managed PostgreSQL repository with atomic claims, workspace-scoped
  idempotency, ordered events, attempts, retention locking, roles and service tokens.
- Redis/Celery late-ack job execution, recovery settings, retries, and periodic
  retention scheduling.
- HF OIDC signature/audience/issuer verification, persisted workspace roles, and
  hashed scoped service credentials. Production mode does not trust identity headers.
- R2 direct storage, presigned uploads/downloads, multipart completion, size
  verification, and metadata-linked deletion.
- Compose PostgreSQL, Redis, Celery worker/beat and S3-compatible local object store.
- Report Viewer legacy discovery/import and Live Monitoring now consume control-plane
  HTTP contracts rather than reading GitHub directly.

## Required before Stage 1 acceptance

- Run `docker compose up --build` in a Docker-enabled environment and execute
  `PRODUCTION_API_URL=http://localhost:8000 pytest -q tests/integration/test_production_stack.py`.
- Exercise worker termination/redelivery once during that run and confirm the job has
  one terminal attempt and a replayable ordered event stream.
- Verified JourneyTest package execution and browser evidence are Phase 1 product
  acceptance work and remain blocked in this container by registry HTTP 403.

## Exit check

Stage 1 closes when the production-stack command above passes without changing the
versioned HTTP contracts used by Gradio. The test covers concurrent PostgreSQL
idempotency, Celery execution/event persistence, and an R2 upload/download round trip.
