# Tracks B and C, in detail

Build spec for the backend and hats tracks scheduled in `docs/next-cycle-plan.md`.
Written 2026-09-18 against `124818e`; every line reference was checked against that
tree. Each item states **what exists**, **the change**, **the seam it attaches to**,
**the tests that prove it**, and **done when**.

The tests matter more than usual here. The worksheet's ground rules record three
separate cases of a guard that passed by producing less, so every rail below gets a
test that proves the rail rather than the happy path.

---

# Track B — the backend

## B1. Route runs through the workspace's providers

### What exists

Three pieces that already fit, and one missing wire.

`ModelSettingsStore.chain(workspace_id, role)` (`model_settings.py:211`) returns
`list[tuple[base_url, api_key, model]]`, ordered by `position`, skipping rows whose
Space secret has since left the environment.

`model_providers()` (`providers.py:42`) returns **the same tuple shape** from the
environment — the deployment default. Its docstring says the shapes match on
purpose, "so a configured workspace and a default one are walked by the same code
and a fallback behaves identically either way".

`DirectLLMSemanticEngine._chain()` (`semantic.py:233`) is where a Python model call
decides what to try, and `_complete()` (`semantic.py:176`) walks it. The retry
discipline is already correct and already paid for: `unreachable()`
(`providers.py:108`) distinguishes *no model saw the question* (DNS, reset, 502/503/504
— try the next provider) from *a model answered unhappily* (400, 401 — a verdict the
next provider will reach identically, so stop). Cycle 48 is recorded as four 503s
from one provider with a configured fallback never tried, because a 503 read as an
answer.

**The missing wire:** `_chain()` builds only from `model_providers()`. `chain()` has
one non-test caller in the whole tree — `app.py:2805` — and it is an admission gate
(`if chain(...): return`), not a routing decision. So a workspace configures its own
provider, is admitted on the strength of having done so, and the run then spends the
deployment's built-in credentials. That is the outcome `model_settings.py` exists to
prevent, stated in its own opening docstring.

### The change

One seam, plus threading. `DirectLLMSemanticEngine` learns who it is working for:

```python
class DirectLLMSemanticEngine:
    def __init__(self, api_key=None, base_url=None, model=None,
                 *, workspace_id: str | None = None, role: str = ROLE_GENERATION): ...

    def _chain(self) -> list[dict]:
        """Explicit constructor argument first, then this workspace's own
        providers for this role, then the deployment default."""
        chain = [...]                                   # explicit, as today
        if self.workspace_id:
            for url, key, model in _settings_store().chain(self.workspace_id, self.role):
                chain.append({"base_url": url, "api_key": key, "model": model})
        for url, key, model in model_providers():       # deployment default, last
            chain.append({"base_url": url, "api_key": key, "model": model})
        return _deduplicated(chain)
```

Ordering is the whole design: a workspace's own providers are tried **before** the
built-in ones, and the built-in ones are appended only when
`may_use_built_in_providers(auth)` says this caller may spend them. For everyone
else the deployment default is not a fallback — it is not in the list at all.
Otherwise the admission gate is decorative: refused at the door, served at the back.

`_settings_store()` is a module-level lazy singleton so `semantic.py` does not take
an import-time dependency on the control plane; the store is SQLite over the same
file the credential store uses.

### Role mapping

`ROLES` is `generation`, `acting`, `reflection`, `vision`
(`model_settings.py:48-52`). Each Python call site declares one:

| Call site | Role |
| --- | --- |
| Persona generation and compilation (`persona_service`) | `generation` |
| `_generate_redesign_fragment` (`executor.py:3360`) | `vision` |
| `_generate_ui_html` (`executor.py:3411`) | `vision` |
| Vision critique | `vision` |
| Root cause, recommendation (Track A's new calls) | `reflection` |

The two executor sites currently open with `if not (os.getenv("OPENAI_API_KEY") or
os.getenv("BLABLADOR_API_KEY")): return None`. That guard becomes "is there anything
in this workspace's chain for this role", which is the same question asked correctly
— and it stops a configured workspace being told no model is available because the
*deployment's* keys are absent.

### The Node worker is a second process

`journeytest.js:279-340` reads `OPENAI_API_KEY` / `BLABLADOR_API_KEY`,
`OPENAI_BASE_URL` / `OPENAI_COMPATIBLE_ENDPOINT`, and the `JOURNEY_REFLECT_*` trio
straight from its own environment, and `llmActor()` (`personaActor.js:515`) already
takes acting, reflection and fallback endpoints as **arguments** — it is only the
wiring above it that reads the environment.

The worker cannot open the control-plane SQLite file (separate service, and it must
not grow a dependency on it), so **the executor resolves the chains and puts them in
the `/v1/runs` body**, the way it already passes `sessionStatePath` and `identity`:

```jsonc
{ "runId": "...", "url": "...", "profile": {...},
  "models": {
    "acting":     [{"baseUrl": "...", "model": "...", "apiKey": "..."}],
    "reflection": [{"baseUrl": "...", "model": "...", "apiKey": "..."}]
  } }
```

Three consequences to design for rather than discover:

1. **Keys travel in a request body.** Over loopback, to a service in the same
   deployment — the same trust boundary `CredentialStore._worker()` already posts a
   decrypted session across. It is acceptable there and acceptable here, but it
   means the body must never be logged, recorded into the run timeline, or echoed in
   an error. `redactSensitive()` already matches `api[-_]?key` and `authorization`;
   the run recorder must be made to pass the payload through it.
2. **The env path stays as the fallback**, so a worker run directly (tests, local
   development) still works with no control plane.
3. **`llmActor` already accepts a fallback triple** — `fallbackModel`,
   `fallbackApiKey`, `fallbackBaseUrl` — so a two-entry chain maps onto it with no
   change to the actor itself. A chain longer than two needs `llmActor` to take a
   list; do that only when a workspace actually configures three.

### Tests

- `chain()` entries are tried before `model_providers()` entries.
- A caller who may not use built-in providers gets a chain that **does not contain
  them**, even when the environment has keys. (This is the rail; the happy path
  passes either way.)
- A 503 from the first entry advances to the second; a 401 does not.
- A workspace with a configured provider and an empty environment completes a call.
- The `/v1/runs` payload containing `models` is redacted in whatever the recorder
  writes.

### Done when

A run in a workspace with its own provider and no `OPENAI_API_KEY` in the
environment completes, and the report names the provider that served it.

---

## B2. Extract the report assembler

### What exists

`apps/api/executor.py` is **3843 lines** and is two programs. The run half ends
around `_combined_test()` (`executor.py:511`) assembling `result`; the report half is
everything that turns `result` into findings and slides, emitted at
`executor.py:469` as `("ux.slides", "text/html", self._slide_deck(result))`.

`services/report-service/` exists and contains only `__init__.py`.

Track A rewrites the report half and B1 rewrites the run half. Without this they
collide on every commit.

### The change

**One mechanical commit. No behaviour change. Every test green before and after.**

Moves:

- Finding builders — `_pain_points_from_expectations` (1486), `_why_they_expected_that`
  (1694), `_broken_promise_finding` (1778), `_pain_points_from_perception` (1836),
  `_pain_points_from_journeys` (2148), and the merge/cluster/contradiction helpers.
- Rendering — `_slide_deck` (3507), `_finding_slide` (3750), the presentation
  renderer, the diagnostics printers.
- Their pure helpers — `_stem`, `_plural`, `verb`, `_patience_in_words`,
  `contrast_fix`, `cited_captures`, `unresolvable_citations`.

Stays: job orchestration, worker dispatch, `_prepare_run_session`, artifact writing,
`_read_snapshot_elements` (2419, it reads run artifacts), the vision-critique
dispatch.

The moved code is `@classmethod`-heavy on `JobExecutor` with no instance state; it
becomes module-level functions, which is what it already is in everything but
spelling. `JobExecutor` imports and calls them. Do the mechanical move first and the
de-classmethoding in the same commit only if the diff stays reviewable; otherwise
split into two commits, both mechanical.

### Tests

The existing contract suite is the test. `tests/contract/test_control_plane.py`
alone is 2500+ lines and covers the report shape densely. Not one assertion changes.

### Done when

`git diff --stat` shows a move, the suite is green, and Track A's next commit
touches no file Track B touches.

---

## B3. Cost and time accounting

### What exists

Nothing. No `usage`, `prompt_tokens` or wall-time record anywhere in `apps/`.

### The change

Two funnels, because there are exactly two:

- **Python:** `DirectLLMSemanticEngine._complete()` (`semantic.py:176`) — every
  Python model call passes through it.
- **Node:** `completion()` (`personaActor.js:450`) — same for the run.

Each records, per call: role, provider served (base_url host and model, never the
key), wall time, and `usage.prompt_tokens` / `usage.completion_tokens` when the
response carries them. Totals roll up into the run record and onto the method slide.

Two reasons this is not optional: the economic case is never made in the artifact
itself, and Track A's new root-cause and re-test calls add model calls, so without
this we cannot say what the better report costs.

### Done when

A report states its own token count and wall time, broken down by role, and names
which provider served the run.

---

## B4. The noise floor

### What exists

Every number in the worksheet is n=1 per commit, and `refused` has swung by a factor
of four between cycles that changed nothing relevant. The record contains two
occasions where a one-cycle movement was read as signal and was not.

### The change

Process, not code. Run the same commit three times; record min/max of `refused`,
`legibleShare` and completed runs; write it into `spec.md` as the noise floor.

```
for n in 52 53 54; do bash cycle-cohort.sh $n; done
measure.py cycle52 cycle53 cycle54
```

### Done when

A later cycle can be called better or worse than this one with a reason. **Nothing
else in Tracks B or C can be called an improvement before this exists** — including
C0, whose whole claim is a measured change in `notLookedAt`.

---

## B5. Concurrency and repeat runs

### What exists

Personas are dispatched in a `for` loop over `/v1/runs` (`executor.py`, the loop
below `_prepare_run_session`), one at a time. A run costs 213–516 seconds, so a
three-person cohort is about 20 minutes.

### The change

Concurrency: dispatch the cohort with a bounded pool. **After B1**, because
concurrency against a provider whose fallback does not work multiplies exactly the
failure mode B1 exists to fix — and `MAX_CONCURRENT_MODEL_CALLS=5` in `config.ini`
was tuned defensively for a reason.

Repeats: the same persona at a second seed, and a `reproducedIn` count on each
finding. A finding seen in 2 of 2 runs is a different claim from 1 of 2, and saying
so raises the floor without inventing anything.

### Done when

A three-persona cohort at two seeds each finishes in roughly the wall time of one
sequential cohort, and findings carry a reproduction count.

---

# Track C — hats, capabilities and `/webui`

## C0. The scan accumulates — the ground layer

### What exists, exactly

`scan()` (`scanpath.py:133`) takes `(candidates, size, scanner)` and is **stateless**.
`perceive()` calls it at `perceive.py:279` and then:

```python
fixated = {item["selector"] for item in fixations}
not_looked_at = [item for item in candidates if item["selector"] not in fixated]
```

`fixated` is rebuilt from *this call's* fixations alone, so `not_looked_at` is
"everything this single look did not land on" — not "everything this person has
never seen".

**The fixation budget itself is not the bug.** `choose_pattern()`
(`scanpath.py:47`) gives `pattern, budget, pull = "spotted", 6, 1.6` when
`patience <= 0.35`, reasoning "little patience, so they hunt for the one thing they
came for". Six is a defensible model of an impatient visitor. The bug is that it is
the *same* six: the worksheet measures `fixated == 6` on all 26 of cycle 51's
captures, consecutive captures fixating the identical six, `e10` among them in 23 of
26, 19 of 43 elements ever looked at, and `notLookedAt` holding at 14, 13, 13, 13,
14, 14…

So a `READ` can never make progress, and with `stepBudget()` at
`min(40, max(12, tasks * 8))` = **16** for the standard two-task journey
(`journeytest.js:197`), the budget always runs out. Eleven of twelve inconclusive
runs ended on exactly 16.

### The change, and where the state lives

The perception service is stateless HTTP (`POST /v1/perceive`,
`perception_service/main.py:23`) and should stay that way, so **the run carries the
memory**:

1. `PerceiveRequest` (`models.py:77`) gains `alreadySeen: list[str] = []`. It has
   `model_config = ConfigDict(extra="ignore")`, so an old client that does not send
   it is unaffected.
2. The worker's `perceive()` payload (`perception.js:495`) sends it.
3. `PersonaDirector` accumulates it per run — the union of
   `perception.perceived[].selector` across every look so far — and passes it on each
   call. Per run, not per persona-across-runs: this is what is on the page in front
   of them now, which is why `PersonaMemoryBank` is the wrong home for it.
4. `scan()` takes it and **deprioritises rather than excludes**. A real visitor can
   re-read something; what they do not do is re-read the same six things sixteen
   times while believing they have seen nothing else. A decay multiplier on an
   already-seen candidate's weight, strong enough that a fresh comparable element
   wins, is the whole change.
5. `not_looked_at` becomes `candidates − (alreadySeen ∪ this call's fixations)`.
   That is the line that makes the count fall, and it is what the done-when measures.

### The report consequence, which is not optional

The worksheet flags it: "On screen and never looked at: 'Pricing'" is a published
finding, and part of what it currently measures is **our own scan having no
memory**, not the page's prominence. Until C0 lands those findings are suspect; when
it lands they start meaning what they say. Say so in the report's limitations
section in the same commit, in both directions.

### Two siblings, same budget

Both cost steps out of the same 16 and both are in the worksheet's verbatim trace:

- **Billing-toggle oscillation.** `e17`/`e18` clicked back and forth up to six times
  in one run. Also the same refs as the four pointer events with no measured box, so
  the walk is losing those refs on some steps — probably one defect, not two.
- **Scroll to an offset the page already holds.** `SCROLL:600` nine times in one
  run. These are absolute offsets; scrolling to where you already are does nothing
  and reads as a dead page. Make it a no-op that reports itself rather than a step
  spent.

### Tests

- `not_looked_at` shrinks across successive `perceive()` calls with a growing
  `alreadySeen`.
- An already-seen element still *can* be fixated when nothing else competes
  (deprioritised, not excluded).
- An absent `alreadySeen` behaves exactly as today.

### Done when

`notLookedAt` falls across a run instead of holding at 13–14, and two of three runs
reach a verdict other than inconclusive. **Nothing hat-shaped ships before this.** A
persona that re-reads the same six things for sixteen steps will do exactly that with
a terminal and a login, burning a larger budget across a bigger surface with failures
much harder to read. A `RUN` taken by an agent that has not noticed it already ran
that command is not a capability; it is a loop with a shell.

---

## C1. `/webui` — the configuration surface

### What exists

The store, the roles, the encryption, the reference/secret split, and a Gradio
dialog (`apps/gradio/model_settings_panel.py`, with `model_settings_open` /
`_save` / `_delete` as `api_name` endpoints). What does not exist is a
standalone surface — `grep -ri webui` over the tree returns nothing.

### The change

A small static page plus a router, modelled on the plain llama.cpp provider
connection flow: an OpenAI-compatible endpoint, a model list fetched from
`/v1/models`, per-role selection.

```
apps/webui/
  __init__.py
  router.py            # APIRouter, mounted at /webui
  static/
    index.html         # no build step: one page, hand-written CSS, no bundler
    app.js
    style.css
```

**Mount order matters.** `gr.mount_gradio_app(fastapi_app, demo, path="/")` mounts a
catch-all at the root; `/webui` must be registered on `fastapi_app` **before** that
call or Gradio swallows it.

**Enabled as an advanced option**, off by default:

```python
if os.getenv("AUX_WEBUI_ENABLED") == "1":
    fastapi_app.include_router(webui.router)
```

Disabled, the routes do not exist. Not 403 — absent. A surface that is not
registered cannot be misconfigured, and this one fronts the deployment's provider
keys.

### Routes

| Method | Path | Body / returns |
| --- | --- | --- |
| `GET` | `/webui` | The page |
| `GET` | `/webui/api/settings` | `{roles: {generation: [row], acting: [...], ...}}` — rows from `store.list()`, **metadata only by construction** |
| `PUT` | `/webui/api/settings` | `{role, label, base_url, model, kind, secret_ref \| secret, position}` → `store.save()` |
| `DELETE` | `/webui/api/settings/{provider_id}` | → `store.delete()` |
| `GET` | `/webui/api/models?provider_id=` | Server-side `GET {base_url}/v1/models`; returns **model ids only** |
| `GET` | `/webui/api/hats` | The registry (C2) |
| `PUT` | `/webui/api/hats/{id}` | Create or individualize a hat |
| `POST` | `/webui/api/chat/completions` | Bounded passthrough — a connectivity check |

### The three rules, and how each is enforced

1. **Workspace authentication, and the built-in-provider reservation applies.**
   Every route resolves `IdentityProvider().resolve(authorization, workspace_id,
   "local")` (`auth.py:121`) and scopes to that workspace, exactly as the Gradio
   panel does. `/webui` is subject to `may_use_built_in_providers()`
   (`model_settings.py:91`), not an exception to it: a caller who may not spend the
   Space's keys may not spend them through this page either, and
   `why_not_built_in()` already writes the message.
2. **No route returns a key.** `store.list()` is metadata-only *by construction* —
   its SELECT does not name the `secret` column — so the settings route is safe
   because of what it calls, not because of what it remembers to strip. Where an
   endpoint must be echoed, echo scheme and host only:
   `build_model_provider_probe()` (`app.py`) already does exactly this, because a
   base URL can carry a key in a query string.
3. **The passthrough is bounded.** Rate-limited per workspace, request and response
   size capped, no streaming, no conversation history kept. It answers "does this
   provider answer" in one click. It is not a chat product, and the moment it grows
   a history it becomes one.

### Tests

- With `AUX_WEBUI_ENABLED` unset, `GET /webui` is 404 and no `/webui/api/*` route is
  registered.
- No response body from any route contains a stored key or a `secret_ref`'s value —
  asserted against a store seeded with both kinds.
- A caller outside `default_provider_owners()` with no configured provider gets
  `why_not_built_in()`, not a working call.
- A request for another workspace's `provider_id` 404s rather than deleting it.

### Done when

`/webui` is reachable with `AUX_WEBUI_ENABLED=1`, configures per-role providers a
run actually uses (B1), and returns no secret under any route.

---

## C2. The hat registry

### What exists

`browsingFaculty({abilities, seed, memory})` (`faculty.js:294`) is already the single
place the mounted tool set is chosen:

```js
const tools = [new BrowserTool({ abilities, seed }), new JourneyTool()];
if (memory) tools.push(memory);
return new Faculty(tools);
```

And `Faculty.actionsDefinitionsPrompt()` (`faculty.js:254`) assembles the persona's
vocabulary from whatever is mounted — so **a hat that adds a tool adds vocabulary
without touching the director.** That is the property the whole design rests on and
it is already true.

### The change

A hat is a record, stored in the control-plane SQLite beside providers and
credentials:

```jsonc
{ "hat_id": "hat_...", "workspace_id": "...", "label": "The integrator",
  "tools": ["browser", "journey", "memory", "developer"],
  "roles": {"acting": "llm_abc", "reflection": "llm_def"},   // provider_ids
  "grants": {"mcpServers": [...], "plugins": [...], "developer": {"allowCommands": [...], "hosts": [...]}},
  "profileDefaults": {...} }
```

`browsingFaculty()` becomes `facultyForHat(hat, {abilities, seed, memory})`, with
the current behaviour as the `visitor` preset so nothing changes for an unspecified
run. The `/v1/runs` payload carries `hat` (resolved server-side — the worker gets the
manifest, not an id it would have to look up).

Ship the named hats as presets; the registry is what makes them editable rather than
hardcoded, which is the point of `/webui` having a hats tab at all.

**The capability manifest goes in the report.** The worksheet is right that it is
load-bearing: "I could not find the retention policy" means one thing from a hat
that could only browse and another from one that could also search a docs site. A
finding carries the hat that produced it and what that hat could reach.

### Tests

- `facultyForHat({tools: ["browser","journey"]})` yields exactly today's
  `actionTypes`.
- Adding a tool to a hat changes `actionsDefinitionsPrompt()` with no change to
  `personaDirector.js`.
- An unknown tool name in a hat is refused at save time, not at mount time.

---

## C3. Front-tab links

A row of buttons in the first Gradio tab opening real URLs, so each still works
pasted to a colleague: **Developer Mode** (`/webui#developer`), one per preset hat
(`/webui#hat=<id>`), **Model & capabilities** (`/webui`). Hidden — not disabled —
when `AUX_WEBUI_ENABLED` is unset, because a visible button to a 404 is worse than
no button.

---

## C4. Hat 2 — redaction *(parallel with C0; gates any real signed-in run)*

### What exists

`redactSensitive()` (`safety.js:34`) redacts **values**: keys matching
`password|secret|token|authorization|cookie|api[-_]?key|credit[-_]?card`, and
`value`/`text`/`inputValue` on elements marked `sensitive` or of input type
`password`.

Nothing redacts pixels. Nothing redacts the element tree.

### The three surfaces, and the rule

**Redact at the point of capture, not the point of render.** An artifact already on
disk is already a leak, and the vision critique posts evidence to a model endpoint
before any deck is built.

1. **Pixels** — the screenshot, the element crops, and `seenImageBase64`. Blank the
   boxes of elements the walk marks sensitive, plus a per-credential selector list
   (an account menu, an invoice table), before the bytes are written or encoded.
   The geometry is already held: `elementBox` is on findings and every walked
   element carries `box`.
2. **The element tree** — `elements` in the perceive payload
   (`perception.js:495`), and the snapshots read back by
   `_read_snapshot_elements()` (`executor.py:2419`). `name` and text carry account
   holders' names as readily as any value field. Extend `redactSensitive()` to the
   tree and apply it on the capture path.
3. **The vision-critique request body** — the one that leaves the deployment. It
   must be built from already-redacted evidence, not redacted on its way out, so
   there is one redaction point rather than two that can disagree.

### Two cheap ones

- **Prefer stored state to replaying a password.** `write_state_file()` already
  produces a state file; a run that has one must never take the `capture_session()`
  path. Password replay is more exposure for no gain and trips rate limits and
  challenge scoring a restored session does not.
- **Detect mid-run expiry.** The run knows `authenticatedSession`; re-check per step
  and end the run as a named diagnostic. A run that silently becomes logged-out
  reviews the logged-out product and says nothing about it — the worst failure
  available, because it is invisible in the output.

### Tests that prove the rail

- An account name present in a snapshot does **not** appear in any written artifact.
- A sensitive element's box is blank in the written screenshot bytes.
- A run with a state file never calls `capture_session()`.
- A session expiring mid-run produces a diagnostic, not a finding about the
  logged-out page.

### Done when

A run signs in, reviews a journey behind the login, and its report carries no account
identifier anywhere in text or evidence.

---

## C5. Hat 3 — developer mode

### The shape

`DeveloperTool extends Tool`, mounted alongside `BrowserTool` in the same `Faculty`,
declaring `realWorldSideEffects = true` — which `BrowserTool` already declares and
does not treat as decoration.

```js
get actionTypes() { return ["FETCH", "INSPECT", "RUN", "AUTHENTICATE"]; }
```

| Action | For |
| --- | --- |
| `FETCH` | Download what the page offers; report what actually arrived |
| `INSPECT` | Checksum, size, archive listing, file type — **no execution** |
| `RUN` | One allowlisted command in a scratch directory |
| `AUTHENTICATE` | Exercise a key the product issued, against its own API |

### The rails are the specification

Not hardening added later. If any of these is dropped, the hat does not ship.

| Rail | Where it attaches |
| --- | --- |
| Off unless the run asks | `run.developer.allowCommands` present, or `facultyForHat` does not mount the tool **at all** — the `allowIrreversibleActions` shape (`safety.js:27`, opted into at `executor.py:533`). Mounted-then-guarded is one bug from ungated. |
| Allowlist, constructed argv | No shell. No pipes, substitution or `&&`. `agentBrowser.js:67` already does exactly this (`execFile(cmd, argv)`), for the same reason: some arguments are secrets. |
| Scratch directory per run | Beside `_run_session_dir()`; destroyed with the run. No access to the repo, the artifact store or the credential database. |
| Environment built empty | Never inherited. The worker process holds every provider key the deployment has — and after B1 it also holds workspace keys in run payloads. A subprocess that inherits that hands them to whatever it just downloaded. |
| Egress to declared hosts only | `privateHost()` (`safety.js:7`) already knows which ranges are never legitimate targets. |
| Output is untrusted input | Through `sanitizeUntrustedText()` (`safety.js:45`) before it reaches a prompt. A downloaded README saying "ignore your instructions" is a file, exactly as page text already is. |
| Every invocation is evidence | Command, argv, exit status, duration and output into the timeline like a click, so "the install fails" can be checked rather than believed. |

### Tests that prove the rail

One per rail, each asserting the refusal rather than the success: a command off the
allowlist is refused; a path outside the scratch directory is refused; the child
environment contains no key present in the parent; a request to a private address is
refused; a `RUN` on a hat without `allowCommands` finds no such action mounted (not
"is refused" — *not mounted*).

### Done when

A run downloads what a page offers, verifies it is what the page claimed, and files a
finding when it is not, with the transcript attached.

---

## C6. Hat 4 — role hats

Evaluator, administrator, integrator, compliance reader. One gate:

> **A hat earns its place only if it changes what the system *does*, not what it
> says.**

Same actions in a different tone is a prompt and belongs in a persona profile.
Applied honestly this rejects some of the four — the administrator wants Hat 2's
tools and none of Hat 3's, the integrator wants Hat 3's, and the other two may turn
out to be personas. That is why the gate is written down before they are built.

---

# Ordering

```
B2 ──┬── B1 ──┬── B3
     │        ├── B5
     │        └── C1 ── C2 ── C3 ── C5 ── C6
     └── (Track A)

C0 (+ the two loop fixes)   — independent of B, blocks C5/C6
C4                          — independent of both, blocks any real signed-in run
B4                          — independent, and gates calling any of it an improvement
```

`B2` first and alone; everything rebases. `C0`, `C4` and `B4` start immediately and
in parallel with it — `C0` and `C4` touch the worker and perception service, `B4` is
process. `C1` waits on `B1`, because a `/webui` that configures models no run reads
is worse than offering no setting at all.

# Test strategy

From the worksheet, and it applies to every item above:

- **Each tool is unit-tested against a fake world.** The `Tool` seam takes an
  injected runner already.
- **Each safety rail has a test that proves the rail, not the happy path.** This
  record has three separate cases of a guard that passed by doing less; those are
  the tests that catch it.
- **One live cycle per item**, measured with the same script and the same table, so
  something that makes runs worse is visible immediately rather than at the end.
- **The noise floor applies to all of it.** Nothing here can be called an
  improvement on one run.
