# Stage 1 completion audit

Date: 2026-08-26

## Result

**Stage 1 is not yet complete.** The local control-plane slice is functional and its
contract tests pass, but production durability and authentication acceptance criteria
are not satisfied. Calling the slice complete would misrepresent the architecture.

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

## Required before Stage 1 can close

- `PLACEHOLDER`: Alembic migrations and a PostgreSQL-backed store implementing the
  same interface, including concurrent claim/idempotency tests against PostgreSQL.
- `PLACEHOLDER`: durable Redis/Celery queue and worker acknowledgements/recovery.
- `PLACEHOLDER`: HF OIDC token verification, workspace membership/role tables, and
  service-credential verification. Development headers are not production auth.
- `PLACEHOLDER`: generic object-storage interface, Cloudflare R2 implementation and
  presigned upload flow. Local retention semantics exist but need durable scheduling.
- Verified JourneyTest package execution and browser evidence are Phase 1 product
  acceptance work and remain blocked in this container by registry HTTP 403.

## Exit check

Stage 1 closes only when the production adapters above pass integration tests without
changing the versioned HTTP contracts used by Gradio.
