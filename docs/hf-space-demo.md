# Hugging Face Docker Space demo

The deployable local-folder demo lives in `spaces/aux-demo`. It is intentionally
self-contained so Space image builds do not clone repositories or require the external
control plane during startup.

The UI identifies itself as `offline_contract_demo`: it previews deterministic
configuration, live-event, `run.json`, report, grounding, and readiness contracts. It
does **not** claim that JourneyTest launched a browser, that Eyeson inspected pixels,
or that synthetic output represents real-user evidence.

## Deploy and inspect logs

Authenticate with a write-scoped user or organization token, then run:

```bash
export HF_TOKEN=hf_...
python scripts/deploy_hf_space.py YOUR_NAMESPACE/aux-synthetic-ux-demo
```

The helper creates or updates a Docker Space, uploads only `spaces/aux-demo`, prints
the current build logs, waits for the Space runtime, and prints runtime logs. Use
`--private` for a private Space and `--timeout` to change the build wait.

## Required production variables

The fixture Space needs no secrets. A production deployment of the root application
still requires external service URLs and `AUTH_MODE=hf_token` on those services; see
`docs/hf-workspaces.md`. Never add credentials to the demo folder or commit them.

## Current environment result

Deployment was attempted on 2026-08-26 but could not create a remote Space because no
HF token/username was configured and the environment's HTTPS CONNECT proxy returned
HTTP 403 for Hugging Face. Docker is also unavailable, so the Docker image could not
be built locally here. The local app contract and Python sources remain testable.
