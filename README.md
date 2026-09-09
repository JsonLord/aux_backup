---
title: UX Analysis Orchestrator
emoji: 📈
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
hf_oauth: true
hf_oauth_scopes:
  - openid
  - profile
hf_oauth_expiration_minutes: 480
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference

The Space uses native HF OAuth for login and workspace discovery. External control
plane and persona deployments must set `AUTH_MODE=hf_token`; see
[`docs/hf-workspaces.md`](docs/hf-workspaces.md) for the identity, role, revocation,
and PostgreSQL RLS flow.

## New control plane

Development has begun on the real, inspectable backend described in [`spec.md`](spec.md).
The legacy root Gradio app is preserved during migration, but new orchestration code
lives under `apps/api` and persists sessions, jobs, events, and artifacts locally
instead of delegating them to Jules.

```bash
docker compose up --build
# API:  http://localhost:8000/docs
# health: http://localhost:8000/healthz
# persona runtime: http://localhost:8090/docs
# journey worker: http://localhost:8080/healthz
```

Compose now starts PostgreSQL, Redis, a Celery worker and beat scheduler, and a local
S3-compatible object store before applying Alembic migrations and starting the API.
After startup, validate the production path with:

```bash
PRODUCTION_API_URL=http://localhost:8000 pytest -q tests/integration/test_production_stack.py
```

The current Stage 0/1 slice runs Gradio analysis and responsive-prototype requests as
real control-plane jobs. SQLite attempt/job state and filesystem report/prototype
artifacts are persistent; live JourneyTest evidence, PostgreSQL, production workers,
DSPy parity, and migrated Eyeson execution are explicitly tracked placeholders.
See [`AGENTS.md`](AGENTS.md) for progress, approach, and unresolved decisions.

The persona image installs Microsoft TinyTroupe v0.7.0 from its resolved commit;
local Python execution can still use seed-reproducible offline generation. Set
`PERSONA_GENERATOR=tinytroupe` to use the pinned adapter. Blablador `alias-huge` is
the direct semantic baseline when credentials are configured, while CI uses the
deterministic mock. DSPy is not activated until parity evaluation passes. The Journey
worker pins core 0.1.2, owns behavior state, and is called by the control plane when
`JOURNEY_WORKER_URL` is configured.

Phase 2 persona profiles are persisted by the persona runtime in local SQLite
(`PERSONA_DATABASE_PATH`) or production PostgreSQL (`PERSONA_DATABASE_URL`) and can be
retrieved through `GET /v1/personas` or `GET /v1/personas/{persona_id}`.
Persona operations are workspace-scoped. Starting a combined test snapshots each
selected profile into an immutable `persona.profile` artifact; the job, Journey worker
result, persisted report, and Live Monitoring all reference or render that exact
snapshot. Validate the pinned TinyTroupe package path separately with
`RUN_TINY_TROUPE_ACCEPTANCE=1 pytest -q tests/integration/test_tinytroupe_runtime.py`.

## Self-contained Docker Space demo

`spaces/aux-demo` is a small local-folder demo that can be deployed independently of
the unfinished live-browser stack. It is explicitly labeled as an offline contract
preview. With a write-scoped Hugging Face token, create/update the Space and print its
build/runtime logs with:

```bash
HF_TOKEN=hf_... python scripts/deploy_hf_space.py YOUR_NAMESPACE/aux-synthetic-ux-demo
```

See [`docs/hf-space-demo.md`](docs/hf-space-demo.md) for limitations and deployment
details.
