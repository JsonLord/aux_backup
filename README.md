---
title: UX Analysis Orchestrator
emoji: 📈
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
hf_oauth: true
---

Check out the configuration reference at https://huggingface.co/docs/hub/spaces-config-reference

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
