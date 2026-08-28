# AUX Synthetic UX Demo — Space status overview

Date: 2026-08-27, updated 2026-08-28
Space: [`Leon4gr45/aux-synthetic-ux-demo`](https://huggingface.co/spaces/Leon4gr45/aux-synthetic-ux-demo)
Deployment overlay: `spaces/aux-live` (single-container preview topology)

This document records what currently works on the live Space, what does not, the
fixes applied in this change, and which spec stages remain open. The first pass was
written from live read-only probes plus a code review. It was then updated after
redeploying the Space four times and driving real, admin-authenticated batch persona
generation against it end to end — see §0 for what that testing found.

## -3. Speed: concurrency + retry tuning

Follow-up to §-2's 363s/3-persona measurement. Implemented every lever identified
there:

- `MAX_CONCURRENT_MODEL_CALLS` (the `threading.BoundedSemaphore` gating every
  outgoing chat-completion call process-wide): `4` -> `8` in `config.ini`. A
  batch of N personas needs up to N concurrent calls per generation "wave"
  (TinyTroupe's own raw-generation phase, then behavior+ability compilation);
  4 throttled a 10-person batch into multiple sequential waves per phase for no
  reason once the backend can sustain more. **First tried 12**: against a
  10-persona batch (up to 20 desired concurrent calls in the compilation wave)
  this overwhelmed the self-hosted router (Tailscale Funnel + Caddy on the
  user's own machine, not a large cloud provider) -- several calls failed live
  with `SSL: UNEXPECTED_EOF_WHILE_READING` (the server dropping connections
  under load, not a code bug). Dialed back to 8 as a more conservative middle
  ground; still independently tunable via `OPENAI_MAX_CONCURRENT_MODEL_CALLS`
  in either direction depending on what a given host can sustain.
- Retry/backoff tuned down to match a fast/reliable provider instead of
  Blablador's: `timeout` 480->180s, `max_attempts` 5->3,
  `exponential_backoff_factor` 5->2 (worst-case pure backoff across retries for
  one call drops from ~13 minutes to ~7s). Each of these five knobs, plus the
  concurrency ceiling, is independently overridable via `OPENAI_*` env vars
  without touching `config.ini` (`services/persona_service/generator.py`,
  `_configure_openai_compatible`).
- `factory.generate_people(..., attempts=3)` now passed explicitly (TinyTroupe
  0.7 defaults this to `10` retries for a single problematic persona's own
  generation call before giving up on it). Override via
  `PERSONA_GENERATION_ATTEMPTS`.
- `generator.py`'s outer per-persona compilation loop (behavior+ability, one
  call each, already parallelized against each other per persona) now also
  runs **across all N personas concurrently** via `ThreadPoolExecutor`, instead
  of looping through them one at a time after TinyTroupe's own raw-generation
  phase finishes. This was the largest hidden serialization: for a 10-person
  batch it turned "10 sequential rounds of paired calls" into one wave (up to
  the concurrency ceiling above).
- `app.py`'s `generate_tasks` retry wait: hardcoded `35s` (tuned for
  Blablador's proxy errors) -> `3s` default, overridable via
  `OPENAI_TASK_RETRY_WAIT_SECONDS`.
- **Found live while testing this at 10 personas, fixed separately**: TinyTroupe's
  one-time sampling-plan step (before any per-person generation) can have the
  model return quantities summing to `0` instead of the requested count
  (`"Expected 10 samples, but got 0 samples"`), and nothing retried that step --
  every person then failed instantly with `"No more characteristics samples left"`,
  and the API reported `"Generation complete!"` with zero personas and no error at
  all. `_generate_people_with_retry` now retries the *whole* batch call (fresh
  `TinyPersonFactory` each attempt -- reusing one after a failed sampling plan
  means its sample pool is already empty) up to `PERSONA_BATCH_RETRY_ATTEMPTS`
  (default 2) times, and a batch that still yields 0 people now raises a clear
  error instead of silently returning `[]`.

Verified: unit tests for every new env-override helper and the
`_configure_openai_compatible` wiring; a mocked-TinyTroupe test confirming the
parallelized outer loop still preserves persona order and per-persona seed
assignment correctly (order is not guaranteed by thread completion order, only
by `ThreadPoolExecutor.map`'s input-order guarantee); full contract suite green.
Live timing after this change: see the measurement appended below once run.

## -2. Milestone: first fully completed live batch persona generation (2026-08-28)

A real batch of 3 TinyTroupe personas was generated end to end through the live
Space (`handle_generate`, admin-authenticated, no HF login) and reached
`event: complete` with full, valid persona/behavior/ability data for all 3 --
the first time in this project's testing that has happened. Total time: 363
seconds for 3 personas (~121s/persona average), which is well above the
previously discussed "<2 minutes for 10 personas" target discussed but not yet
implemented -- the concurrency/retry-tuning levers identified earlier
(`max_concurrent_model_calls`, parallelizing the compiler stage across
personas, tightening `max_attempts`/`exponential_backoff_factor`/`timeout`)
remain open follow-up work.

Getting here required three more real, previously-hidden bugs, found only by
running generation for real (not by static review) after the provider switch
and the persona-varied-abilities feature made execution reach further into
the pipeline than any earlier attempt:

1. `TinyPerson.__init__` unconditionally imports an unused notebook-display
   module (`tinytroupe.experimentation.in_place_experiment_runner`) that needs
   `IPython` and `scipy` at import time. Never exercised before this session
   because generation always failed earlier (Blablador 502s, then the
   system-message-ordering 400s). Fixed by adding both to
   `spaces/aux-live/requirements-live.txt`.
2. `DirectLLMSemanticEngine._complete_json` (behavior + the new ability
   compiler) had no retry logic at all, unlike TinyTroupe's own client --
   raised by the user after observing "the auto model sometimes fails."
   Fixed: retries the identical request up to 3 times on connection error,
   non-2xx status, or an empty completion.
3. The bug that retry then exposed: some models behind the `auto` router
   (observed live: `gemini-2.5-flash-lite`) wrap their JSON completion in a
   markdown code fence despite `response_format: json_object`, so every retry
   was hitting the same deterministic parse failure, not a transient one.
   Fixed with fence-stripping plus a regex fallback before `json.loads`.

## -1. Provider switch: Blablador → self-hosted freellmapi router

After §0's testing pinned every remaining failure on Blablador's own gateway
reliability (persistent `502 Proxy Error`), the Space was switched to a different
OpenAI-compatible provider:

- **Endpoint:** `https://debian-devil.tail3f341b.ts.net/v1` (Tailscale Funnel → a
  self-hosted `desk_agent_2.0` Caddy/router), set as the public `OPENAI_COMPATIBLE_ENDPOINT`
  Space variable.
- **Model:** must be the literal id `"auto"` (the router's own model-selection
  logic) — any other id 400s with `model_not_found`. Set as the `OPENAI_MODEL` Space
  secret; also the new code-level default everywhere `alias-large`/`alias-huge` used
  to be (`app.py`, `config.ini`, the persona generator/semantic engine defaults,
  `start-live.sh`).
- **API key:** set as the `OPENAI_API_KEY` Space secret.

Verified directly before rollout: `GET /v1/models` returns 200 with `auto` listed as
`available: true` (1,048,576 token context window), and a live
`POST /v1/chat/completions` with `model: "auto"` returned a clean, fast `200 OK`
(routed to `gemini-2.5-flash` in that instance). This endpoint is self-hosted by the
user and was substantially more responsive in this initial check than Blablador was
throughout §0's testing.

The system-message-consolidation fix from §0.2 is provider-agnostic (it only
normalizes outgoing message ordering) and was left in place — harmless if this
router doesn't share Blablador's strict ordering requirement, still protective if it
does. `BLABLADOR_*` env var names remain supported everywhere as legacy aliases for
the same `OPENAI_*` settings; nothing reads them as Blablador-specific anymore.

**Not yet re-verified after this switch:** an actual end-to-end batch persona
generation run against the new provider (redeploy was still in progress / pending at
the time this section was written — check the live conversation or `/api/readiness`
plus `/api/v1/sessions` for the current state).

## 0. Update: live redeploy + batch persona generation testing

The Space was redeployed with this branch, its `OPENAI_MODEL` secret was corrected,
and a real (non-offline, non-mocked) TinyTroupe batch persona-generation run was
driven against the live Space using the new admin credential. This surfaced and fixed
three additional real defects beyond the original token-cap fix, in order:

1. **`alias-huge` is not a valid Blablador model.** The Space's `OPENAI_MODEL` secret
   and this repo's own default (set in the prior revision of this change) were both
   `alias-huge`, which the gateway rejects with a live `404 Model 'alias-huge' not
   found`. A web search of Blablador's documentation confirms the real aliases are
   `alias-fast`, `alias-large`, `alias-code`, `alias-embeddings`, `alias-reasoning`.
   Reverted the default to `alias-large` everywhere (`app.py`, the persona generator
   and semantic engine, `config.ini`, `start-live.sh`) and corrected the Space secret
   directly via the Hugging Face API.
2. **TinyTroupe 0.7.0 sends a trailing system message, which Blablador rejects.**
   Reading the pinned TinyTroupe source directly: `tinytroupe/utils/llm.py`'s
   `LLMChat.call()` appends a JSON/typing-format instruction with `role: "system"` to
   the *end* of the conversation immediately before nearly every structured/typed
   call — the path every `@llm()`-decorated persona-attribute generator uses. The
   Blablador gateway's backend rejects any request whose system message is not first
   with `400 System message must be at the beginning`, and TinyTroupe's own retry
   logic treats that as non-retryable, silently returning `None` for the field
   instead of failing loudly. This affected essentially every generated persona
   attribute. Fixed with a runtime patch (`services/persona_service/generator.py`,
   `_patch_system_message_ordering`) that wraps `OpenAIClient.send_message` to
   consolidate every system-role message into one leading message before the call is
   sent — no TinyTroupe site-packages file is edited, consistent with the existing
   "map settings through TinyTroupe's public config-manager APIs only" boundary.
3. **Gradio's own OAuth gate blocked the admin bypass.** The admin-token feature
   (§ below) worked at the `authenticated_clients()` level, but every relevant Gradio
   callback declared `oauth_profile: gr.OAuthProfile` (not `| None`), and Gradio's own
   `special_args` framework code rejects such calls before the function body ever
   runs, independent of any in-function fallback. Verified against Gradio's own
   source. Widened all 16 affected callback signatures to `gr.OAuthProfile | None,
   gr.OAuthToken | None` so an anonymous/admin-token caller actually reaches the
   function body.

**Result after all three fixes:** the pipeline now demonstrably reaches Blablador
correctly — genuine `200 OK` responses were observed (`Sampling dimensions computed
successfully`, `Sampling plan computed successfully`), and the `400` cascade is gone
(no further "System message must be at the beginning" errors appeared in any
subsequent run). The **remaining blocker is Blablador's own gateway reliability**, not
this codebase: across roughly 50 minutes of live testing (four redeploys, multiple
generation attempts), effectively every model call after the fixes still failed with
`502 Proxy Error / Error reading from remote server` from Blablador's own reverse
proxy, exhausting TinyTroupe's retry budget (backoff up to 625s per attempt) without
completing. No application-level error accompanied any of these — they are upstream
502s. **No batch persona generation run reached completion during this session**; the
connection and full instrumentation chain are proven correct, but observed evidence of
a completed batch is still outstanding, pending Blablador's own availability. A
Workspace-dropdown UX gap was also found (the browser dropdown starts empty and
`load_hf_workspaces` doesn't add an admin-workspace choice when using the token
bypass) — noted as a follow-up, not blocking.

**Test reproduction**, once Blablador is stable, using the admin credential (works
from any HTTP client, no HF login needed):

```bash
curl -X POST -H "Authorization: Admin $ADMIN_API_TOKEN" -H "Content-Type: application/json" \
  -d '{"data": ["<theme>", "<customer profile>", 3, "TinyTroupe", null, "<target url>", null]}' \
  https://leon4gr45-aux-synthetic-ux-demo.hf.space/gradio_api/call/handle_generate
# then GET .../gradio_api/call/handle_generate/<event_id> (SSE) until "event: complete"
```

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
| Model default | Default model unified to `alias-large` (see §0 — `alias-huge` is invalid) | `config.ini`, `app.py`, `services/persona_service/generator.py`, `services/persona_service/semantic.py`, `services/persona_service/parity.py`, `spaces/aux-live/start-live.sh` |
| Env normalize | `start-live.sh` exports `OPENAI_MODEL` default + `OPENAI_MAX_COMPLETION_TOKENS` | `spaces/aux-live/start-live.sh` |
| 401 noise | `validate_workspace` no longer raises a traceback before login; returns a friendly message | `app.py` |
| Example personas | `get_example_personas` / example loader now also find agents in the installed TinyTroupe wheel, and degrade gracefully instead of erroring | `app.py` |
| **Admin access** | Operator break-glass: `Authorization: Admin <ADMIN_API_TOKEN>` authenticates as admin without HF OAuth (backend + Gradio + public API) | `apps/api/auth.py`, `app.py` |
| **Admin access (Gradio gate)** | 16 Gradio callbacks widened to `gr.OAuthProfile \| None` so Gradio's own framework-level login gate doesn't block the admin fallback before it can run (see §0.3) | `app.py` |
| **400 fix** | Runtime patch consolidates TinyTroupe's trailing system messages into one leading message so Blablador's gateway accepts the request (see §0.2) | `services/persona_service/generator.py` |

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

Steps 1–3 are **done** as of this update (Space redeployed four times; `OPENAI_MODEL`
secret corrected to `alias-large`; §0's three fixes applied and verified reachable).
What is left:

1. ~~Redeploy the Space with this change~~ — done, running commit `1295a32`.
2. ~~Confirm/correct the Space `OPENAI_MODEL` secret~~ — done, set to `alias-large`.
3. ~~Fix the 400/404 application-level errors~~ — done, verified no recurrence.
4. **Retry once Blablador's gateway is stable.** Every remaining failure in ~50
   minutes of live testing was `502 Proxy Error / Error reading from remote server`
   from Blablador itself, not this application. Re-run the reproduction command in
   §0 — if the pipeline still can't get a clean run through, consider: lowering
   `OPENAI_MAX_COMPLETION_TOKENS` further (e.g. 4096) to shrink each request's
   footprint, generating fewer personas per batch, or trying `alias-fast` for a
   lighter-weight smoke test before returning to `alias-large`.
5. Fix the Workspace-dropdown UX gap noted in §0: have `load_hf_workspaces` add an
   `admin` choice when `ADMIN_API_TOKEN` is set and no HF profile is present, so an
   admin using the actual browser UI (not just headless API calls) gets a usable
   dropdown instead of an empty one.
6. Poll a usability job to completion and require non-empty screenshot + snapshot
   artifacts before treating findings as observed.
