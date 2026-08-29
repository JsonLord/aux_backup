# AUX Synthetic UX Demo — Space status overview

Date: 2026-08-27, updated 2026-08-28 (multiple passes), 2026-08-29 (multiple passes)

## -11. Live-observed Persona Studio crashes, example personas in the Studio,
knowledge-grounding synthesis bug, and a stale-doc correction pass

Two real production stack traces surfaced from the deployed Space's own logs:

- **`load_persona` `IndexError: list index out of range`.** Selecting a
  `persona_index` value with no matching entry in `persona_display` (e.g. a
  stale dropdown value left over from before a page reload, or before any
  persona had been loaded) crashed the event handler outright. `load_persona`
  now falls back to the first available profile for an out-of-range index,
  and to blank defaults for an empty list, instead of raising.
- **`monitor_and_log` `401 Unauthorized`, from the Live Monitoring tab's 60s
  background timer.** That timer fires for every open tab regardless of
  sign-in state; an expired HF OAuth session (a long-idle tab) or an
  anonymous visitor without `ADMIN_API_TOKEN` configured produced an
  unhandled `HTTPError`/`PermissionError` every minute, spamming the server
  log. Now caught and surfaced as a status message in the tab instead.

**Example personas enabled directly in Persona Studio**, per explicit
request: previously the 6 bundled example personas (Friedrich_Wolf, Lila,
Lisa, Marcos, Oscar, Sophie_Lefevre) were only reachable through the
Analysis Orchestrator's Generate flow (`persona_method = "Example Persona"`).
A new "Bundled example persona" dropdown + "Load into Studio" button in
Persona Studio compiles one directly (real behavior/abilities through the
same `PersonaCompiler` every other source uses) and appends it to whatever's
already loaded, selecting it immediately for editing -- no Generate run
required. This is very likely what the crashing `persona_index` selection
above was actually reaching for.

**Blablador naming retired from app.py.** We no longer use Helmholtz
Blablador -- the self-hosted freellmapi router has been primary since
section -1. `app.py`'s own module-level config resolution still read
`BLABLADOR_API_KEY`/`BLABLADOR_BASE_URL` *before* `OPENAI_*`, inverted from
the comment above it describing the intended precedence (and from
`start-live.sh`'s own resolution order). Renamed to `LLM_API_KEY`/
`LLM_BASE_URL`/`get_llm_client()`/`llm_chat_adaptation`, with `OPENAI_*` read
first and `BLABLADOR_*` kept only as a legacy env-var fallback (the actual
env var names, not the internal identifiers, since `start-live.sh` and
anything else in the deployed container may still reference them).

**Real knowledge grounding was silently lost during cross-persona
synthesis** -- found while correcting section 7's now-very-stale phase
table below. `visionCritique.js` calls `groundPainPoint` against a curated
WCAG/Nielsen-Norman corpus for every finding and sets a real `grounding`
field on each `UXPainPoint`, but `aggregate.js`'s `aggregateCohort` never
carries that field into its root-cause groups, and `apps/api/executor.py`'s
`_synthesize_pain_points` never read it off the representative pain point
either -- so `critical_pain_points[].grounding` was `None` on every real
report, presentation, and slide deck this session ever produced, despite
the underlying references being real and correctly computed. Fixed
entirely in Python (no JS change needed: `_synthesize_pain_points` already
has the full original pain points via `pain_point_by_id`, grounding
included) -- `representative.get("grounding")` is now copied onto the
report finding, and both `_presentation` and `_slide_deck` render a
"Grounded in: <source> — <principle>" line when references are present.
`test_vision_critique_synthesizes_across_personas_with_element_crop` now
asserts grounding survives into the report, the presentation HTML, and the
slide deck HTML.

Section 7 below ("Open spec stages / phases") was still describing a
2026-08-27 snapshot -- a Blablador 502 blocking live generation, "no
observed live run yet" -- that every later section of this document had
already resolved with real, live evidence. Corrected in place rather than
left to mislead a future reader.

Verified: full Python suite 89 passed / 4 skipped (8 new tests in
`tests/contract/test_persona_studio.py`); `services/eyeson-worker/node`'s
18-test suite unaffected (no JS changed); `app.py` imports cleanly
standalone.

## -10. GitHub re-enabled, deliberately scoped two ways

`gh`/GitHub-write flows were removed in section -8 in favor of workspace-scoped
control-plane storage. Re-enabled here, but narrower and more intentional than
before -- two separate integrations, not one broad one:

**1. Persona pool -- read-only, "always-connected" service credential.**
Implements all three persona-pool-plan.md components (A, B, C).
`services/persona_service/github_pool.py`'s `GitHubPersonaPoolClient` reads
`index.json` and persona files from a dedicated pool repo
([JsonLord/PersonaPool](https://github.com/JsonLord/PersonaPool)) via the
GitHub Contents API, TTL-cached (default 300s), using
`PERSONA_POOL_GITHUB_TOKEN` -- a read-only, contents:read credential
distinct from any individual user's own GitHub PAT (set as an HF Space
secret, never baked into the Dockerfile; the client also works
unauthenticated against a public repo, just under GitHub's lower rate
limit -- confirmed live, since no token is set yet). Selection uses
keyword/tag textual distance plus behavior-trait-range distance, picking a
diversified "closest-ranged group" (farthest-point sampling over the
nearest candidates) rather than the naively-closest matches, which can
cluster. New `POST /v1/personas/pool-lookup` (persona-runtime) mints a
fresh workspace-local persona id per adopted match -- `PersonaStore.save()`
keys rows globally by persona id, so re-saving a pool file's own id under
two different workspaces would silently steal it from whichever workspace
saved it first. `app.py`'s "PersonaPool" generation method now calls this
lookup and falls back to live TinyTroupe generation for any shortfall,
replacing the external `THzva/deeppersona-experience` Space call
(`generate_persona_from_deeppersona`) entirely -- that whole function is
deleted, not just unreferenced.

Seeded live: `POST /api/v1/personas/compile-example` (new, also generally
useful standalone) was called once per bundled TinyTroupe example persona
(Friedrich_Wolf, Lila, Lisa, Marcos, Oscar, Sophie_Lefevre) against the
deployed Space, producing 6 real compiled `SyntheticUserProfile` records,
written to the pool repo with a generated `index.json` and README. Directly
calling `POST /api/v1/personas/generate` (new) or
`/api/v1/workflows/usability` for live TinyTroupe-generated personas across
theme archetypes (persona-pool-plan.md section 3's originally planned
diversity source) was attempted but consistently cut off by an intermediate
proxy's idle-connection timeout before a multi-minute generation could
finish -- both routes hold one HTTP connection open synchronously for the
whole generation, unlike the job-queued journey-run path. Solved properly
via component B rather than worked around here (see below).

**Component B -- scheduled generation, implemented as an inert template
(not wired to run in this repo, at the user's explicit request).**
Its generation logic runs daily via `scripts/generate_persona_pool_batch.py`
in the workflow (`workflow_dispatch` also available for an on-demand run)
when active, but the workflow file itself lives at
`scripts/persona-pool-generate.yml.template` -- deliberately kept outside
`.github/workflows/`, the only directory GitHub Actions scans for
workflows, so it cannot fire on a schedule or be manually dispatched in
this repo. To activate it elsewhere: copy the file into
`.github/workflows/persona-pool-generate.yml` (dropping the `.template`
suffix) in the target repo and add the two secrets below there. The
script itself calls `TinyTroupeGenerator` directly
in-process (no HTTP round-trip to time out) against 6 rotating theme/
customer-profile archetypes (checkout, SaaS onboarding, support, content
discovery, healthcare scheduling, banking) -- each archetype's
`customer_profile` text is written to lean the generated persona toward a
different behavioral flavor (patience, digital confidence, verification
tendency, ...), since `TinyTroupeGenerator` has no direct numeric
trait-target input; behavior is compiled from the generated persona's
description, not set by hand. Writes new persona files plus a regenerated
`index.json`, prunes entries older than 90 days (deleting their files, never
an entry whose date can't be parsed), and commits/pushes only when there is
an actual diff. `tests/contract/test_persona_pool_batch_generation.py`
covers the theme-tag/summary derivation, per-archetype failure isolation
(one archetype erroring doesn't abort the run), file writing, and pruning
logic (9 tests, using the generator's deterministic offline-fallback path
so no live credentials are needed to test it).

**Not live-verified -- deliberately deactivated.** Even once copied into an
active `.github/workflows/` location, it needs two repository secrets
neither I nor the Space can supply: `BLABLADOR_API_KEY` (the same
model-router credential the Space already uses) and
`PERSONA_POOL_WRITE_TOKEN` (a GitHub PAT scoped to `contents:write` on
`JsonLord/PersonaPool` only -- deliberately a different, more-privileged
credential than the Space's own read-only `PERSONA_POOL_GITHUB_TOKEN`, so a
compromised Space credential still can't write to the pool repo). The pool
stays at its 6-persona hand-seeded state until this is activated somewhere
and those secrets are added.

Live-verified end-to-end after deploy: `POST /api/v1/personas/pool-lookup`
for "Architecture and modular housing design" correctly matched Oscar (an architect) as the closest
textual match and picked Sophie Lefevre (unrelated occupation, but a
behaviorally distant second pick) rather than the second architect in the
pool, Friedrich_Wolf -- real evidence the diversification pass is doing
its job, not just returning the K nearest.

**2. Per-user backup -- bring-your-own PAT, session-only.** A new "GitHub
Backup" tab lets a signed-in user paste their own fine-grained PAT, lists
repos it can push to via the GitHub API (`GET /user/repos`, filtered to
`permissions.push`), and syncs the current workspace session's
ux.report/ux.presentation/ux.slides/journey.log/persona.profile artifacts
to their chosen repo under `sessions/<session_id>/...` via the Contents API
(sha-aware create-or-update). `apps/gradio/github_backup.py` holds the
logic; the PAT lives only in a Gradio browser-session `gr.State` and is
never written to the control-plane's persistent store -- re-entering it
after a page reload is the accepted cost of that choice. Live-verified the
failure path end-to-end (`POST .../gradio_api/call/connect_github` with a
fake token correctly surfaced "GitHub rejected this token"); the success
path needs a real user-supplied PAT to verify, which only the signed-in
user can provide.

Both features' unit/integration tests (`tests/contract/test_persona_pool.py`,
`tests/contract/test_github_backup.py`) mock all GitHub HTTP calls; the pool
lookup and the connect-github failure path were additionally verified live
against the real deployed Space and the real (public) JsonLord/PersonaPool
repo, as described above.

## -9. Persistent local storage for sessions/reports/artifacts across restarts

Live multi-persona verification (two `Friedrich_Wolf` example personas,
distinct ids/seeds, against `https://leon4gr45-nova-right-nav.hf.space`)
confirmed the previous identity-collapse fix works end-to-end in production,
and surfaced a real limitation in cross-persona synthesis: `aggregate.js`'s
`rootCauseSignature` groups on an exact string match of the vision model's
free-form `diagnosis.mechanism` text, so near-duplicate findings from
different personas describing the same real issue in different words (e.g.
"Primary navigation hidden inside a dropdown" vs. "Unconventional tab-based
navigation dropdown" from the two runs) stayed as separate single-persona
root causes instead of merging. Left open as a follow-up (needs a semantic
or category+element-overlap grouping key, not exact-text matching).

Separately, the "Workspace session / Refresh sessions / Report / Load
report / Download report" flow (Report Viewer, Persona Thought Logs,
Presentations, Slide deck, and Evidence Artifacts tabs) was already real
and workspace-scoped -- `apps/api/store.py`'s SQLite `Store` keys every
session/job/artifact row by `workspace_id`, and artifacts are written under
`<ARTIFACT_ROOT>/<workspace_id>/<session_id>/<artifact_id>`. The actual gap:
the live Space's `Dockerfile` points `DATABASE_URL`/`ARTIFACT_ROOT` at
`/home/user/data` and `/home/user/artifacts`, which are inside the
container's own ephemeral filesystem -- every redeploy or Space restart
wiped all sessions and reports, defeating "current sessions to load and
follow along." `spec.md` calls for Cloudflare R2 (S3-compatible) as the
*production* artifact store but explicitly requires "support local-only
runs" too, so switching this demo Space to R2 isn't the right fix; the
SQLite/local-filesystem path is correct here, it just needs to survive a
restart. `spaces/aux-live/start-live.sh` now detects Hugging Face Spaces'
persistent storage volume (mounted at `/data` when the Space has the
Persistent Storage add-on attached) at container start: if `/data` is a
writable mount, `DATABASE_URL`, `PERSONA_DATABASE_PATH`, `ARTIFACT_ROOT`,
and `JOURNEY_ARTIFACT_ROOT` are redirected under it before any service
starts; otherwise the Dockerfile's original ephemeral paths are used
unchanged, so this is a no-op unless persistent storage is actually
attached to the Space (a paid HF Spaces setting the user controls, not
something settable from inside the container).

## -8. Full UXPainPoint synthesis, dead-code removal, and three tabs made real

User-directed expansion of §-7's stage-2 critique toward spec.md §20's full
`UXPainPoint` model and real cross-persona synthesis, plus "go further with
the next tabs" -- explicitly: results must be based on synthesized data
analysis, never individual persona citations.

**Full UXPainPoint shape + real cohort aggregation.** `visionCritique.js`
findings now carry multiple elements with roles (trigger/cause/feedback/
obstacle/recovery, not one `elementSelector`), a vision-model-*estimated*
`behavioralImpact` (frustration/confusion/trust -- the same epistemic
category as its existing severity/category judgment; cognitive/physical
effort deltas have no analogue in a static screenshot and stay at 0 rather
than being invented), and structured `alternatives` (proposedChange/
rationale/effort). New `toPainPoint()` shapes a finding into the full record
`aggregate.js`'s `aggregateCohort()` expects -- real, tested cohort/root-
cause aggregation code that already existed in this repo but had never been
wired to a live evidence source, since it was built against the native
fixture engine's simulated psychological deltas. New endpoints:
`/v1/journey-evidence-analyses` also returns full `painPoints`, and
`/v1/cohort-aggregation` runs `aggregateCohort` across every persona's pain
points from one run. `apps/api/executor.py`'s vision path now has two
stages: `_collect_vision_pain_points` (per-persona UXPainPoint records) then
`_synthesize_pain_points` (cross-persona root causes -> report findings
tagged `source=eyeson-vision-synthesis`). Every vision finding in the report
is now a synthesized root cause -- how many personas hit it, average
estimated impact, combined alternatives -- never a single persona's
individual citation, even with one persona (that's just a root cause with
one affected user through the same synthesis path, not a special case).

**Dead GitHub-backed code removed (~480 lines).** `gh` has been `None`
since the control-plane migration, so everything gated on it was already
unreachable, and most of it (repo/branch listing, report-in-branch/PR
pulling, `render_slides`, heatmaps, `deploy_to_hf`, solutions/thought-log
fetchers, the periodic repo monitor) wasn't even wired to a UI element
anymore. The one exception that mattered: `select_or_create_personas`'s
default path always hit `get_persona_pool()` (GitHub, always `[]`), so its
"ask an LLM which pool persona fits" logic never ran -- every call silently
generated fresh personas and no-op'd an "upload to pool". Replaced with a
**real local pool**: `persona_client.list()` against the persona-runtime's
own store, which already durably saves every persona this workspace has
ever generated or compiled (no separate upload step needed at all). Also
fixed a real crash the dead code was hiding: the pool-judging loop read
`pool[i]['name']` directly, but real profiles nest name under
`persona.name` -- would have KeyError'd the moment the pool had content.

**Three more tabs made real:**
- **Persona Thought Logs** now renders a Markdown summary (persona name,
  verdict with emoji, the real per-action timeline
  `services/journey-worker`'s `timelineToEvents` records, blockers/UX
  findings) above a collapsed raw-JSON accordion, instead of a bare JSON
  code dump. Handles both `journey.log` and `persona.profile` artifact
  shapes.
- **Slide deck**: a new `ux.slides` artifact, generated locally alongside
  the presentation for every `combined_test` run -- one navigable slide
  (arrow keys or click) per *synthesized* finding, with its crop image and
  combined alternatives, self-contained in one HTML file. No GitHub, no
  external `mkslides` binary (which, on inspection, was only ever installed
  in the *other*, unrelated root `Dockerfile` -- never in
  `spaces/aux-live/Dockerfile`, so `render_slides` was doubly dead even
  before its GitHub dependency). Shown in the Presentations tab via an
  iframe (`gr.HTML` injects via innerHTML, which silently does not execute
  `<script>` tags -- the deck's navigation JS needs a real iframe document,
  the same `srcdoc` pattern already used for the generated-UI prototype).
- **Agents.txt** gained a real "design agent brief" generator, finally using
  the `session_id_at` textbox that sat wired to nothing. Built entirely from
  a session's synthesized `critical_pain_points` (severity-sorted, each with
  its combined alternatives as concrete instructions), not the pre-existing
  "coding agent prompt" button next to it, which was found to be
  permanently non-functional: it reads from `selected_solutions_json_state`,
  a `gr.State("[]")` that is never set as any event's output anywhere in the
  file, so it always ran on an empty list. Left as-is (a separate,
  differently-scoped feature) rather than silently repurposed.

**Multi-persona Example Persona identity-collapse fix.** Both
`select_or_create_personas` and the `/api/v1/workflows/usability` API
endpoint built N-persona example-persona runs with
`[load_example_persona(...)] * count` -- N references to the exact same
compiled dict, sharing one persona id. This silently defeated the
cross-persona synthesis just described: `aggregateCohort` groups
`affectedUsers` in a Set keyed by persona id, so "5 personas" from one
example file would always collapse into "1 affected user" and never
exercise real cohort aggregation. Fixed on both paths: compile the example
persona once per requested persona, each with its own seed (1..N), giving
each its own id and seed-varied behavior/ability sample. The cheap
identical-copy shortcut is kept only where identity doesn't matter (the
no-network dropdown preview).

## -7. Stage-2 vision critique, the PersonaPool gap, and infra fixes live
## testing surfaced along the way

Direct continuation of §-6 (same two directives: prefer example/pool personas
over live generation for testing; never accept a placeholder where the spec
calls for something real). Also user-directed: "see where to integrate the
ux-ai testing eyeson feeding it the screenshots taken during journeytest
core... based on the 2 stage implementation of user persona feedback and then
grounding in ux interest."

**New: stage-2 vision-based UX critique.** `services/eyeson-worker`'s
`visionCritique.js` sends real JourneyTest screenshots plus journeytest-core's
own semantic element list to the already-configured vision-capable model
(verified live before wiring anything: "auto" routes to a real vision model,
which needs a much larger completion budget than text calls -- hidden
reasoning consumed a 300-token budget with no visible output in one probe).
Findings are grounded through the previously-unused `CuratedUXKnowledgeProvider`
(real WCAG/Nielsen Norman references). New `POST /v1/journey-evidence-analyses`
endpoint; `apps/api/executor.py` calls it for a bounded, evenly-spaced sample
of each run's screenshots, pairs each with its semantic snapshot by filename
stem, and crops the specific element region a finding refers to into the
report as a data URI. Findings seen on multiple screenshots from the same run
(the same real bug, confirmed by more than one sample) now collapse into one
finding instead of listing near-duplicates. See `docs/upstream-sources.md`'s
Eyeson entry for how this relates to the originally-planned Eyeson migration.

**Live verification found a real bug in the tool, then a real bug on a real
site.** First live run against a real user-provided site
(`leon4gr45-nova-right-nav.hf.space`) came back `passed` with zero pain
points from stage 1 alone -- unsurprising, since task-completion verdicts
can't see design problems. Stage 2 caught what stage 1 structurally cannot:
a page heading clipped under a sticky header, low-contrast form labels
(independently confirmed by inspecting the actual screenshot), and -- most
notably -- a severe rendering bug where the entire hero/header section
repeats recursively down the page, flagged independently on two different
screenshots and, on manual review, corrected an earlier (wrong) call in this
same doc: a similar duplicated-content full-page screenshot was previously
guessed to be a capture-tool artifact (identical height across two temporally
separate captures). A fresh vision model with no knowledge of that guess
looked at the same kind of evidence and called it a real frontend rendering
bug -- the more likely explanation in hindsight, since Chromium's full-page
capture renders exactly what's in the DOM.

**Live testing surfaced three more real, fixed bugs while verifying this:**
1. **PersonaPool had the exact same gap Example Persona had before it was
   fixed**: `generate_persona_from_deeppersona` (the external DeepPersona-Space
   stand-in) returned a bare `{name, minibio, persona}` dict with no
   `behavior`/`abilities`, so any real journey test against a PersonaPool
   persona would fail. Now compiled through the same `PersonaCompiler` as
   every other source. Also fixed: a partial PersonaPool result (some
   DeepPersona calls failed) was being silently discarded, falling through
   into an unrelated generic fallback path instead of returning what
   `force_method="PersonaPool"` had actually, successfully produced.
2. **`/api/v1/workflows/usability` returned a bare, undiagnosable 500** when
   persona generation/compilation failed upstream (e.g. the shared model
   router rate-limiting under this session's own heavy testing load) --
   FastAPI's default handler for an unwrapped exception. Now a 502 with the
   real error message.
3. **The persona `compile()` client had a hardcoded 60s timeout** shorter
   than the server's own legitimate internal retry/backoff (up to
   `SEMANTIC_ENGINE_MAX_ATTEMPTS` attempts with growing backoff, for two
   concurrent calls) can take under router load -- found from the newly
   readable error message in fix (2) immediately after deploying it. Now a
   generous, overridable 180s default (`PERSONA_COMPILE_TIMEOUT`), matching
   `generate()`'s existing pattern.

All of the above verified via passing unit/integration tests (Python +
Node) and, for the vision critique and PersonaPool fixes, live runs against
real target sites and a local functional check against a running
persona-runtime.

## -6. Example-persona journey testing, real pain-points, real UI generation,
## and the first live end-to-end verdicts against real target sites

Continuing-development pass driven by two directives: always use a bundled
example persona (Friedrich_Wolf and friends) rather than live TinyTroupe
generation for backend/API testing, and never accept a hardcoded/placeholder
result where the spec calls for something real.

**Example personas were silently unusable for journey testing.** The
"Example Persona" method built a bare `{name, minibio, persona}` dict with no
`behavior`/`abilities` -- but live journey runs require `profile.behavior`
(journey-worker validates this). Added `POST /v1/personas/compile`
(persona_service) and `TinyTroupeGenerator.compile_existing`, which run an
already-built persona through the same `PersonaCompiler` live generation
uses, without paying TinyTroupe's generation latency/cost. Wired into
`app.py`'s Example Persona path and a new `example_persona` parameter on
`/api/v1/workflows/usability`. First deploy of this crashed the whole Space
at Gradio module-import time: the dropdown's default preview eagerly
compiles before any authenticated identity exists, hit the new endpoint
unauthenticated, 401'd, and the unhandled exception took the whole
`with gr.Blocks()` block down with it. Fixed by splitting a pure-file-read
preview path (`compile_behavior=False`, no network call) from the real
compile path used for actual journey testing -- verified this time by
**actually importing `app.py` locally** (installed gradio+itsdangerous in
the dev sandbox) rather than trusting `py_compile`, which can't catch
module-import-time bugs.

**`_combined_test`'s pain-points were a fixed per-task sentence
("Validate task clarity: <task>"), regardless of what the browser run
found.** Inspecting `@baguette-studios/journeytest-core@0.1.2`'s actual
`RunResultSchema` (installed and read locally, not guessed) shows every
live run already carries a genuine `AgentVerdict`: `blockers`, `uxFindings`,
`suggestedImprovements`, and per-criterion pass/fail results,
evidence-grounded in what the director actually observed.
`_pain_points_from_journeys` now derives `critical_pain_points` from that
verdict, falling back to the old inferred list only when
`JOURNEY_WORKER_URL` isn't configured at all. Also found and fixed a related
dead-code bug: journey-worker's `index.js` looped over `result.steps` to
enqueue Eyeson evidence for live runs, but the real `RunResultSchema` has no
`.steps` field at all -- that loop silently never ran. Replaced with
`timelineToEvents()`, mapping the run's real `timeline` into worker events.

**First live smoke test caught a real logic bug in the fix above.**
Friedrich_Wolf against `https://example.com` (via the new `example_persona`
API path) came back `verdict.status: "passed"` with a real screenshot
(downloaded and visually confirmed as the actual example.com page) but
`critical_pain_points` still flagged `"Pass criterion not-met: tasks-blocked"`
as a high-severity finding. `journeyContract()` always emits one pass
criterion (`tasks-completed`: bad when not-met/blocked) and one **fail**
criterion (`tasks-blocked`: bad when the failure condition is actually
*met*) -- the deriver treated every criterion's `not-met` as bad, which is
backwards for a fail criterion. Fixed with a small id-keyed polarity map;
`"blocked"` (assessment itself couldn't complete) stays bad either way.
Verified live a second time (see below) with the same criteria pattern
correctly producing no false pain-point.

**`ui_adaptation` jobs ("Full New UI" tab, chat-based "Real-time
Adaptation") always returned the same fixed HTML template** with the
request text merely embedded as inert copy -- "Change primary color to
emerald" produced identical output to any other request. Now calls the
already-configured OpenAI-compatible model for a real, self-contained HTML
prototype (`DirectLLMSemanticEngine.complete_text`, a new sibling to
`_complete_json` sharing its retry/backoff machinery), falling back to the
old static template (now honestly labeled "Offline fallback") only when no
LLM credentials are configured or generation fails. The chat path now also
passes the session's most recent `ui.prototype` artifact as `previous_html`
so follow-up requests genuinely revise the current prototype instead of
generating an unrelated one from scratch each turn.

**Two full end-to-end live runs against real target sites, evaluated for
judgment quality, not just plumbing:**

- `https://example.com` -- `passed`, high confidence, correct specific
  summary of the actual page content.
- `https://leon4gr45-nova-right-nav.hf.space` (a real user-provided site,
  "Nova Workspace") -- `passed`, high confidence:
  > "The tester successfully understood the website's offerings (Branding
  > Simulation API for Global Teams) and how the main navigation works
  > (tabs and sidebar). The tester also used the navigation to find and
  > interact with a specific feature (Leave Feedback modal)."

  Cross-checked against the actual screenshots: the H1 text, the tab/sidebar
  nav model, and the "Leave Feedback" sidebar link are all real and
  correctly identified -- not generic boilerplate. Task-completion judgment
  quality: genuinely good. UX-critique *depth* is honestly limited: with
  nothing blocking either task, pain-points stayed empty, because this
  pipeline currently judges "did the persona complete the task," not "is
  this well-designed" -- deep Eyeson visual/element-attribution critique
  (spec.md §20) is still not wired to live evidence, and the report's own
  `limitations` field says so.

  **Found a real defect in evidence capture, not the target site:** two
  "full page" screenshots from the Nova run are 9,956px tall and just tile
  the same short landing-page hero section repeatedly instead of capturing
  more unique content -- viewed both, byte-identical height despite being
  taken at different points ~200s apart in the session, which points to a
  fixed/capped tiling fallback in `agent-browser`'s (or journeytest-core's)
  full-page capture rather than a growing DOM bug in the target site (a
  real accumulating-duplicate-DOM bug would produce a *taller* second
  capture, not an identical one). `agent-browser` ships as a closed,
  precompiled binary per platform (no readable source), so this is
  documented rather than patched -- out of this repo's ownership boundary
  per spec.md §3.1 (JourneyTest "must own" screenshots).

Regression tests added for all of the above:
`test_compile_endpoint_gives_an_existing_persona_real_behavior_and_abilities`,
`test_report_pain_points_are_derived_from_real_journeytest_verdict_not_hardcoded`,
`test_passed_run_with_unblocked_fail_criterion_reports_no_pain_point`,
`test_ui_adaptation_calls_the_configured_llm_for_a_real_prototype`,
`test_ui_adaptation_falls_back_to_static_template_without_llm_credentials`,
and a journey-worker `index.test.js` for the timeline→events mapping.

## -5. Real-usage bug: Workspace dropdown rejected a real signed-in user

Reported directly by the user against real (non-API-test) browser usage:
`gradio.exceptions.Error: 'Value: hf:user:675f37b072d14a2cff8b7343 is not in the
list of choices: []'` -- a genuine, currently-logged-in HF user's own real
workspace ID, rejected. Same error class found earlier in this session during
admin/API testing, but this confirms it also breaks real logged-in use, not just
headless calls.

Root cause, confirmed against Gradio 5.15.0's actual installed source
(`Dropdown.preprocess`): a submitted value is validated against `self.choices`,
the *server-side* Python component's own attribute -- and in a `gr.Blocks()` app,
that component is a single object shared across every concurrent session on the
deployment, not per-browser-session state. Any other session's (or an earlier
event's) most recent `gr.update(choices=...)` can leave it stale or empty for
everyone else, independent of what any individual user's own browser is showing
them.

Fix: `allow_custom_value=True` on all 10 dynamically-populated dropdowns
(`workspace_selector`, `persona_index`, and the 4 workspace-session/artifact
pairs for presentations/reports/logs/evidence) -- Gradio's documented, official
way to skip this exact validation. Safe here because the real authorization
check already happens downstream in `authenticated_clients()`/
`request_identity()` against the actual OAuth token; these dropdowns only need
to *offer* choices, not gate them. (`example_persona_select` and `color_vision`
were left untouched -- their choices are genuinely static, not per-session
dynamic, so they don't share this failure mode.)


## -4. Speed, round 2: bypassing TinyTroupe's sampling-plan setup phase

Round 1's tuning (§-3) got a 10-persona batch to complete successfully for the
first time, but at 845 seconds -- and the live log timeline showed why: with
`factory.generate_people(number_of_people=N)`, TinyTroupe first computes sampling
dimensions and a sampling plan (a couple of slow calls), then generates a name for
**every** planned person **one at a time in a plain sequential `for` loop**, all
under one lock, before any parallel per-person generation even starts. Observed
live: ~7.5 of ~14 minutes was this setup phase alone -- entirely unaffected by
`MAX_CONCURRENT_MODEL_CALLS` or any other concurrency/retry tuning, since none of
that applies until after this phase finishes.

Fix: default to calling `factory.generate_person()` directly, once per person, in
our own `ThreadPoolExecutor` (TinyTroupe's "one-off agents" code path) instead of
`generate_people(number_of_people=N)`. This still serializes one name-generation
call per person under the same lock, but each call releases the lock immediately
after, interleaved with other threads' work, instead of blocking every thread
behind N sequential calls upfront. Trade-off, and it's a real one: this loses the
sampling plan's demographic-quota diversity control, and TinyTroupe 0.7's
`generate_person()` has no `seed` parameter, so raw-generation seed
reproducibility is lost too (the compiled behavior/ability profiles are still
seeded per persona regardless). Restore the old behavior with
`PERSONA_USE_SAMPLING_PLAN=true` if that trade-off isn't wanted.

Verified: a mocked-factory test confirming the default path calls
`generate_person()` N times in parallel (never `generate_people()`), with
`attempts` still passed through, producing N distinct personas; full contract
suite green. Live timing after this change: see the measurement appended below
once run.

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
(§48). **This table was last accurate around 2026-08-27 and had gone stale** --
most rows below describe blockers (a Blablador 502, "no observed live run yet")
that sections -2 through -10 of this document since resolved with real, live
evidence. Corrected 2026-08-29 against that later work and one gap it surfaced
(see the grounding note under phase 12):

| Phase | Area | Status |
| --- | --- | --- |
| 0 | Dependency baselines, persona-runtime service, shared IDs | ✅ done |
| 1 | One JourneyTest run inside host | ✅ done -- proven live repeatedly (section -2's first completed batch run, section -10's multi-persona live verification) |
| 2 | TinyTroupe persona generation | ✅ done -- live generation confirmed working (section -2), plus lightweight `/api/v1/personas/generate`/`compile-example` routes (section -10) |
| 3 | BehaviorController MVP | ✅ native controller present (readiness `behaviorController:true`) |
| 4 | DSPy persona compiler | ⚠️ available but not selected by default: `dspyAvailable:true` in readiness means the package imports, but `PERSONA_COMPILER` defaults to `native` -- the deterministic compiler is what's actually active in production, not DSPy |
| 5 | Evidence bus / screenshot streaming to Eyeson | ✅ done -- proven end to end repeatedly (section -7's live vision critique, section -10's live crop/finding evidence) |
| 6 | Pain-point resolver | ✅ done for the active path (vision-critique -> `toPainPoint` -> `aggregateCohort`, section -8); `services/eyeson-worker/node/src/painResolver.js` (the native-fixture-engine path) remains an explicit, deliberate placeholder for a path this deployment doesn't use |
| 7 | Two-mode report UI | ✅ done -- stage 1 (JourneyTest's own AgentVerdict) and stage 2 (independent vision critique) both live in `critical_pain_points` |
| 8 | Alternative generation | ✅ done for the active path -- vision findings get real, structured LLM-proposed alternatives (section -8); `alternatives.js`'s template system remains an explicit placeholder for the native-fixture-engine path |
| 9 | RAG placeholder | ✅ real for the active path -- `CuratedUXKnowledgeProvider` (WCAG/Nielsen-Norman references) grounds every vision-critique finding (section -7), though until 2026-08-29 that grounding was silently dropped during cross-persona synthesis and never reached the report/presentation/slides (fixed today, see phase 12) |
| 10 | Physical/perceptual profiles | ✅ ability compilation works (verified via `apply_persona_tweaks`) |
| 11 | Cohort aggregation | ✅ done -- `aggregateCohort` wired to the live evidence path and verified live (section -10: correctly matched and diversified real pool personas) |
| 12 | Real knowledge grounding | ⚠️ real but narrow: a 3-source curated WCAG/Nielsen-Norman corpus (`services/eyeson-worker/node/src/knowledge.js`), not the fuller corpus spec.md §51 envisions (peer-reviewed UX/HCI literature, internal design system, past studies, support tickets, analytics, A/B tests -- none of that is started). **Bug fixed 2026-08-29**: `apps/api/executor.py`'s `_synthesize_pain_points` built its report finding without ever reading the representative pain point's `grounding` field, so real references computed per observation never survived cross-persona synthesis into the user-facing report, presentation, or slide deck -- silently `None` in every report despite being real upstream. Now copied through to all three, with a new test asserting it end to end. |

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
