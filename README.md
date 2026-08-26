---
title: UX Analysis Orchestrator
emoji: 📈
colorFrom: blue
colorTo: red
sdk: docker
app_port: 7860
pinned: false
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
```

The current implementation is an initial Stage 0/1 slice. SQLite and filesystem
artifacts are real local persistence; PostgreSQL, Redis workers, JourneyTest,
TinyTroupe, DSPy, and migrated Eyeson execution are explicitly tracked placeholders.
See [`AGENTS.md`](AGENTS.md) for progress, approach, and unresolved decisions.
