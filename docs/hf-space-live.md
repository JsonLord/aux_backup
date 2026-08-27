# Hugging Face live application

`spaces/aux-live` is the deployment overlay for the repository-backed application.
Unlike the offline contract demo, its image installs the pinned TinyTroupe runtime,
Node 24 Journey worker, JourneyTest core, `agent-browser`, and its browser runtime.
The container starts the control plane, persona runtime, and Journey worker on
loopback ports; Gradio communicates with them only through their versioned HTTP APIs.

Deploy it with:

```bash
python scripts/deploy_hf_space.py Leon4gr45/aux-synthetic-ux-demo \
  --folder spaces/aux-live --full-repo --timeout 1800
```

## Required Space configuration

The Space must enable OAuth and external services must use `AUTH_MODE=hf_token`.
Configure `BLABLADOR_API_KEY` for semantic compilation and the OpenAI-compatible
director credentials expected by JourneyTest (`OPENAI_API_KEY`, `OPENAI_BASE_URL`,
and `JOURNEY_MODEL`). Without model credentials, the services remain healthy but
TinyTroupe or agent-directed browser runs must fail explicitly rather than falling
back to claimed live evidence.

The image installs the pinned TinyTroupe source with `--no-deps` after installing
the reviewed runtime subset in `requirements-live.txt`. TinyTroupe 0.7.0 publishes
notebook, test, scraping, embedding, and GPU-adjacent packages as mandatory
dependencies even though the persona factory boundary does not use them. The live
image therefore stays CPU-oriented and verifies the factory import during its build.

The single-container layout is a Hugging Face preview topology. Persistent production
acceptance still requires PostgreSQL/RLS, Redis/Celery, R2, and separately deployed
service containers as described in `docs/hf-workspaces.md` and `docs/stage-1-audit.md`.

## Current deployment result

The repository-backed image is running at
[`Leon4gr45/aux-synthetic-ux-demo`](https://huggingface.co/spaces/Leon4gr45/aux-synthetic-ux-demo).
`GET /api/readiness` confirms the control plane, pinned TinyTroupe import, native
behavior controller, Eyeson worker, and JourneyTest 0.1.2 worker are ready. With the
Space's `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_COMPATIBLE_ENDPOINT` settings,
the endpoint now reports `modelCredentialsConfigured: true` and
`liveExecutionReady: true`. Readiness is not represented as a successful
model-directed browser run. The full Gradio register and Persona Studio behavior and
ability controls are visible after Hugging Face sign-in.

## Workspace-local results

The live UI no longer uses GitHub branches as its result store. Analysis sessions,
immutable persona snapshots, reports, presentations, journey logs, prototypes, and
browser evidence are listed from the authenticated control-plane workspace. Finished
reports and presentations have download buttons backed by the artifact content API.
The former repository/branch loaders and GitHub token diagnostics are not registered
as Gradio API endpoints.

Authenticated API clients can run the OpenDesign acceptance workflow with:

```bash
HF_OAUTH_TOKEN=... WORKSPACE_ID=hf:user:... \
  bash scripts/test_hf_live_workflow.sh
```

This accepts a Space OAuth access token or a Hugging Face personal access token. A
personal token is restricted to its verified personal workspace; organization
workspace selection requires OAuth claims. It also requires the Blablador/OpenAI
model secret reported by `/api/readiness`.

On 2026-08-27, the deployed readiness, UI/API-surface, and single-profile
`persona_choices` regression checks passed, and `https://open-design.ai/` returned
HTTP 200. The personal-token API path generated five workspace-scoped profiles and
persisted report, presentation, and journey-log artifacts. Those report findings are
still inferred: the recorded JourneyTest runs failed before screenshot capture, so no
observed Eyeson findings are claimed for that target. Re-run the asynchronous command
above and retain non-empty browser-evidence artifact IDs before accepting the report.
