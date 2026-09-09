# Hugging Face Docker Space demo

The deployable local-folder demo lives in `spaces/aux-demo`. It is intentionally
self-contained so Space image builds do not clone repositories or require the external
control plane during startup.

The UI identifies itself as `offline_contract_demo`: it previews deterministic
configuration, live-event, `run.json`, report, grounding, and readiness contracts. It
does **not** claim that JourneyTest launched a browser, that Eyeson inspected pixels,
or that synthetic output represents real-user evidence.

## Deploy and inspect logs

Authenticate with a write-scoped user or organization token, then run either:

```bash
export HF_TOKEN=hf_...
python scripts/deploy_hf_space.py YOUR_NAMESPACE/aux-synthetic-ux-demo
```

or store the token in the standard Hugging Face cache before deploying:

```bash
hf auth login
python scripts/deploy_hf_space.py YOUR_NAMESPACE/aux-synthetic-ux-demo
```

The helper creates or updates a Docker Space, uploads only `spaces/aux-demo`, prints
the authenticated account and current build logs, waits for the Space runtime, and
prints runtime logs. `HF_USERNAME` only selects a namespace and is not an API
credential. Use `--private` for a private Space and `--timeout` to change the build
wait.

## Test the deployed API with cURL

The Gradio call protocol uses a POST to obtain an event ID followed by a GET of the
event stream. Run the checked-in smoke test against the accepted deployment:

```bash
bash scripts/test_hf_space_api.sh
```

Pass another Space base URL as the first argument to test a different deployment.
The script intentionally uses command substitution for the event ID rather than a
piped `read`: in non-interactive Bash, a pipeline can run `read` in a subshell and
leave the subsequent GET with an empty event ID. It validates all four returned
values, including the transparent `offline_contract_demo` mode, `not_executed`
verdict, synthetic-user count, and demo readiness.

## Required production variables

The fixture Space needs no secrets. A production deployment of the root application
still requires external service URLs and `AUTH_MODE=hf_token` on those services; see
`docs/hf-workspaces.md`. Never add credentials to the demo folder or commit them.

## Current environment result

Deployment was accepted on 2026-08-26 at
[`Leon4gr45/aux-synthetic-ux-demo`](https://huggingface.co/spaces/Leon4gr45/aux-synthetic-ux-demo).
The remote Docker build completed, `/healthz` returned the documented ready payload,
and the public `/run_contract_demo` Gradio API produced the deterministic fixture and
readiness contracts through the documented two-request cURL protocol. Browser
acceptance also confirmed that clicking **Run contract preview** displays progress,
updates the cross-tab outputs, and displays a completion message above the tabs. The
first runtime attempt exposed an undeclared `requests`
import in Gradio 5.15.0; the Space requirements now include it explicitly. This
acceptance covers only the self-contained offline contract demo, not the external
production services or HF workspace OAuth scenarios.
