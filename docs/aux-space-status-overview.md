# AUX Synthetic UX Demo — Space status overview

Date: 2026-08-27
Space: [`Leon4gr45/aux-synthetic-ux-demo`](https://huggingface.co/spaces/Leon4gr45/aux-synthetic-ux-demo)
Deployment overlay: `spaces/aux-live` (single-container preview topology)

This document records what currently works on the live Space, what does not, the
fixes applied in this change, and which spec stages remain open. It is written from
live probes of the running Space plus a code review; items that could not be verified
live (they require the Space's private `BLABLADOR_API_KEY`) are labelled **unverified**.

## 1. Deployment topology (as running)

`spaces/aux-live/start-live.sh` starts four processes inside one container and then
the Gradio app:

| Service | Port | Purpose |
| --- | --- | --- |
| Control plane (`apps/api`) | 8000 | sessions, jobs, artifacts, tenancy |
| Persona runtime (`services/persona_service`) | 8090 | TinyTroupe persona generation + compiler |
| Journey worker (Node) | 8080 | JourneyTest browser runs |
| Eyeson worker (Node) | 8081 | screenshot / evidence analysis |
| Gradio + FastAPI (`app.py`) | 7860 | UI and public API, proxies to the above |

`GET /api/readiness` on the live Space returns:

```json
{"status":"ready",
 "services":{"controlPlane":{"status":"ok"},
   "personaRuntime":{"status":"ok","tinytroupeAvailable":true,"dspyAvailable":false},
   "journeyWorker":{"status":"ready","engine":"journeytest","journeyTestVersion":"0.1.2"},
   "eyesonWorker":{"status":"ready","version":"0.1.0"}},
 "modelCredentialsConfigured":true,"liveExecutionReady":true}
```

## 2. Environment → TinyTroupe wiring (verified)

**The Space env vars are being read and registered for TinyTroupe.** The chain is:

1. `start-live.sh` normalizes the Space settings into the internal contracts:
   `OPENAI_COMPATIBLE_ENDPOINT → OPENAI_BASE_URL`, `OPENAI_MODEL → JOURNEY_MODEL`,
   `OPENAI_API_KEY`/`BLABLADOR_API_KEY` reconciled both ways.
2. `services/persona_service/generator.py` prepares the standard OpenAI SDK env
   (`_openai_compatible_settings`) **before importing** TinyTroupe, then maps the
   values onto TinyTroupe's registered OpenAI client through the public config
   manager (`_configure_openai_compatible`: `config_manager.update_multiple(...)` +
   `clients.force_api_type("openai")`).

Evidence it is wired: readiness reports `modelCredentialsConfigured: true`,
`tinytroupeAvailable: true`, `liveExecutionReady: true`, and the Space startup log
shows `Updated config: base_url = https://api.helmholtz-blablador.fz-juelich.de/v1`
and `model = alias-large` at runtime. The Dockerfile itself does not need to read the
secrets — `start-live.sh` and the persona runtime do.

## 3. Root cause of the persona/task failures (`502 Proxy Error`)

The blocker is **not** the wiring. Every failed call in the log is an upstream
`502 Proxy Error / Error reading from remote server` from the Helmholtz Blablador
gateway on `POST /v1/chat/completions`. That is a gateway **read-timeout**: the model
server accepted the request but did not return within the proxy's lifetime.

Primary contributing cause found in config: `MAX_COMPLETION_TOKENS` was **not set** in
`config.ini`, so TinyTroupe 0.7 used its default of **128000**. Asking a large alias
(`alias-large` / `alias-huge`) to stream up to 128k completion tokens does not finish
inside the Blablador proxy window, which produces the 502. The token-counting error
(`_count_tokens() is not implemented for model alias-large`) is emitted by TinyTroupe's
tiktoken lookup for the custom alias; it is **benign noise** (logged, then execution
continues) but it also means TinyTroupe cannot pre-truncate, so an uncapped completion
budget is the practical lever.

Secondary amplifier: `generate_tasks` retried 5× with a fixed `time.sleep(35)` on top
of TinyTroupe's own exponential backoff (up to 625s), so a single 502 storm exceeded
the persona-generate client timeout and surfaced as the `ReadTimeout` on port 8090.

## 4. Fixes applied in this change

| Area | Change | File |
| --- | --- | --- |
| 502 root cause | Cap completion budget: `MAX_COMPLETION_TOKENS=8192` (was default 128000) | `config.ini` |
| 502 root cause | Env override `OPENAI_MAX_COMPLETION_TOKENS` pushed into TinyTroupe config manager | `services/persona_service/generator.py` |
| 502 root cause | Cap all direct OpenAI-compatible chat calls (`max_tokens`) in the Gradio helpers | `app.py` |
| Model default | Default model unified to `alias-huge` across app, generator, start script | `config.ini`, `app.py`, `services/persona_service/generator.py`, `spaces/aux-live/start-live.sh` |
| Env normalize | `start-live.sh` exports `OPENAI_MODEL` default + `OPENAI_MAX_COMPLETION_TOKENS` | `spaces/aux-live/start-live.sh` |
| 401 noise | `validate_workspace` no longer raises a traceback before login; returns a friendly message | `app.py` |
| Example personas | `get_example_personas` / example loader now also find agents in the installed TinyTroupe wheel, and degrade gracefully instead of erroring | `app.py` |
| **Admin access** | Operator break-glass: `Authorization: Admin <ADMIN_API_TOKEN>` authenticates as admin without HF OAuth (backend + Gradio + public API) | `apps/api/auth.py`, `app.py` |

### Admin API-token access (new)

Set `ADMIN_API_TOKEN` (and optionally `ADMIN_WORKSPACE_ID`, default `admin`) as a
Space secret. Then:

- The backend `IdentityProvider` accepts `Authorization: Admin <token>` in any auth
  mode (constant-time compared) and returns an `admin` role identity.
- The Gradio app falls back to this credential **only when no HF OAuth session is
  present**; a signed-in user always authenticates as themselves.
- The public API (`/api/v1/...`) accepts either a `Bearer` HF token or the `Admin`
  credential.

Example:

```bash
curl -H "Authorization: Admin $ADMIN_API_TOKEN" -H "X-Workspace-ID: admin" \
  https://leon4gr45-aux-synthetic-ux-demo.hf.space/api/v1/sessions
```

## 5. API endpoint functional results (live probes)

Probed against the running Space (event POST + result GET). "Functional" means the
endpoint returned correct data, not merely a 200.

| Endpoint | Result | Notes |
| --- | --- | --- |
| `GET /health`, `/api/info`, `/api/readiness` | ✅ works | all services ready |
| `/apply_persona_tweaks` | ✅ **functional** | compiles behavior + ability JSON correctly (no LLM needed) |
| `/persona_choices`, `/persona_choices_1` | ✅ functional | dropdown choices built from persona JSON |
| `/save_tasks` | ✅ functional | returns "Tasks saved." |
| `/load_hf_workspaces`, `/_check_login_status` | ✅ functional | correct pre-login state |
| `/update_method_visibility` | ✅ functional | |
| `/update_persona_preview` | ⚠️ fixed here | previously errored; example agents were not bundled on the live image |
| `/generate_agents_prompt` | ⚠️ state-bound | errors when invoked raw via API with no selected-solutions state; works from the UI |
| `/workspace_storage_diagnostics`, `/list_presentation_sessions`, `/monitor_and_log`, and all session/report/log/evidence listing calls | 🔒 require auth | error without an authenticated workspace; now reachable with HF login **or** the admin token |
| `/handle_generate` (TinyTroupe), `/api/v1/workflows/usability` | ⛔ model-blocked | depend on Blablador; blocked by the 502 addressed above — **unverified** until re-run with the key |

## 6. What works vs. what does not

**Works today**
- Full service topology healthy; env→TinyTroupe wiring confirmed.
- Deterministic persona **compiler** (behavior + physical/perceptual abilities) end to
  end, no model required (`apply_persona_tweaks`).
- Workspace tenancy, session/artifact persistence, downloadable report / presentation /
  journey-log artifacts (validated previously in `docs/opendesign-hf-testing-report.md`).
- HF OAuth login; and now admin-token access for maintainers.

**Does not work / not yet proven**
- **Live model-directed generation** (TinyTroupe personas, task generation, browser
  journeys) has not produced observed evidence: prior runs recorded `runStatus: error`
  before any screenshot, driven by the Blablador 502. The token cap targets this; it
  must be re-run with the key to confirm.
- **Example Persona** method depended on `external/TinyTroupe/examples/` which the live
  wheel image does not ship (now resolved to the installed package / graceful skip).
- **Observed browser screenshots + Eyeson findings**: none captured yet on the Space.

## 7. Open spec stages / phases

The migration plan in `spec.md` §41 (Phases 0–12) and the Definition-of-complete-v1
(§48). Status synthesized from the code, the stage-1…20 audits, and live behavior:

| Phase | Area | Status |
| --- | --- | --- |
| 0 | Dependency baselines, persona-runtime service, shared IDs | ✅ done |
| 1 | One JourneyTest run inside host | ⚠️ wired; **no observed live run yet** (model 502) |
| 2 | TinyTroupe persona generation | ⚠️ wired + offline fallback; **live batch unverified** (this change targets it) |
| 3 | BehaviorController MVP | ✅ native controller present (readiness `behaviorController:true`) |
| 4 | DSPy persona compiler | ⚠️ compiler works; **DSPy disabled** on the live image (`dspyAvailable:false`) — deterministic compiler in use |
| 5 | Evidence bus / screenshot streaming to Eyeson | ⚠️ workers ready; **not proven end to end** (no live screenshots) |
| 6 | Pain-point resolver | 🚧 present in code slices; unproven without observed runs |
| 7 | Two-mode report UI | 🚧 partial |
| 8 | Alternative generation | 🚧 partial (model-gated) |
| 9 | RAG placeholder | ✅ placeholder ships (`not_configured`) |
| 10 | Physical/perceptual profiles | ✅ ability compilation works (verified via `apply_persona_tweaks`) |
| 11 | Cohort aggregation | 🚧 open |
| 12 | Real knowledge grounding | ⛔ future roadmap, not started |

Cross-cutting open items:
- **Production topology**: the Space is a single-container preview. Production
  acceptance still needs PostgreSQL/RLS, Redis/Celery, R2, and separate service
  containers (`docs/hf-workspaces.md`, `docs/stage-1-audit.md`).
- **Observed-evidence acceptance**: an async usability job must be polled via
  `GET /api/v1/jobs/{job_id}` until it finishes with **non-empty** screenshot and
  snapshot artifacts before any report is treated as observed rather than inferred.

## 8. Remaining actions to reach a live batch persona run

1. **Redeploy** the Space with this change so the token cap and admin access take
   effect.
2. Confirm the Space `OPENAI_MODEL` secret is `alias-huge` (or unset it to use the new
   default). The secret overrides the code default.
3. Re-run persona generation and confirm the 502 is gone. If large aliases still time
   out, lower `OPENAI_MAX_COMPLETION_TOKENS` further (e.g. 4096) or switch
   `OPENAI_MODEL` to a faster alias for task generation.
4. Poll a usability job to completion and require non-empty screenshot + snapshot
   artifacts before treating findings as observed.
