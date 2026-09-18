# Next-cycle implementation plan

Written 2026-09-18, against the tree at `124818e`. Companion to
`docs/next-cycle-worksheet.md`, which holds the measured record and the hats
design; this document schedules the work and says what can run at the same time.

Three strands:

- **Track A — the report.** What the output should achieve.
- **Track B — the backend.** What has to exist underneath for A and C to work.
- **Track C — hats.** The asynchronous extension: capabilities as mountable
  profiles, a llama.cpp-style configuration surface at `/webui`, developer mode.

Tracks B and C are specified item by item — seams, contracts, tests and done-when —
in `docs/next-cycle-tracks-b-c.md`. This document is the ordering argument; that one
is the build spec.

## First: the audit is two dozen cycles out of date

The quality audit this plan started from — *Observed vs Explained*, 68 criteria,
26 strong / 17 partial / 12 weak / 13 absent — was taken at **cycle 26**. The
worksheet's record runs to **cycle 51**. Checking each of its findings against the
tree rather than carrying them forward, most of its worst group is already closed:

| Audit finding | State on this tree |
| --- | --- |
| B1 root cause is the symptom restated | **Closed.** `"rootCause": cls._why_they_expected_that(group)` (`executor.py:1821`) |
| B5 `susceptibleTraits` ships `None` | **Closed.** `cls._traits_behind(group)` (`executor.py:1827`) |
| E6 evidence is a whole-page screenshot | **Closed.** `elementBox` carried for cropping (`executor.py:1819`) |
| E8 the same sentence printed three times | **Closed.** `personaEvidence` takes `sightings`, not the gap quote (`executor.py:1826`) |
| A3 "0.22 of patience" means nothing | **Closed.** `_patience_in_words(cost)` |
| F6 `persona(s)`, `run(s)` | **Closed.** `_plural()` / `verb()` helpers |
| G3 `run_diagnostics` ships `[]` | **Closed.** `_instrument_diagnostics` + `_coverage_diagnostics` (`executor.py:698`) |
| C1/C2 the recommendation is a principle | **Open.** `executor.py:1806`, verbatim below |
| C5 `alternatives` ships `None` | **Open.** Never set; `_finding_slide` fakes one from the recommendation (`executor.py:3761`) |
| C8 no re-test | **Open.** Nothing in the tree |
| H2 cost per review | **Open.** No token or wall-time accounting anywhere |

**So Track A is much smaller than the audit implies, and its remaining items are
concentrated in one place: recommendations.** Anything below that cites the audit
cites it as re-verified, not as received.

## The spine: a settings store that nothing routes through

`apps/api/model_settings.py` exists and is good. It defines four roles
(`generation`, `acting`, `reflection`, `vision`), stores a provider as **model,
endpoint and key together** — its docstring notes that "the failure that cost five
cycles was a fallback that carried the endpoint and not the model" — holds keys the
same two ways `CredentialStore` does, and exposes `chain(workspace_id, role)`
returning an ordered fallback list. `apps/gradio/model_settings_panel.py` renders
the dialog.

**Nothing routes a run through it.** `chain()` has exactly one non-test caller,
`app.py:2805`, and it is an admission gate — *may this workspace run at all* — not
a routing decision:

```python
if _model_settings_store().chain(auth.get("workspace_id") or ... , "acting"):
    return
```

The run itself still reads the environment directly: `executor.py:3366` and
`executor.py:3417` both branch on `os.getenv("OPENAI_API_KEY") or
os.getenv("BLABLADOR_API_KEY")`. So a workspace configures its own provider, is
admitted on the strength of having done so, and then the run spends **the
deployment's** built-in credentials anyway — precisely the outcome the module was
written to prevent.

This is the same shape as the credential gap that `AGENTS.md` recorded for two
cycles: a store, a dialog, a test suite, and no consumer. It is **B1**, it is the
first backend deliverable, and both `/webui` and the per-hat model assignment are
blocked on it — configuring a model that no run reads is worse than not offering
the setting.

## Track A — the report

### A1. Commit to one concrete change *(the largest remaining report defect)*

`executor.py:1806`, unchanged since the audit:

> "Either make {label} do what it reads as doing, or stop it reading that way."

That is a principle, not a recommendation: it restates the problem as a choice and
hands the thinking back to the reader. The benchmark commits — *"put the Danish
database at the top of the menu"*, *"add a counter, which helps the user keep track
of which items have already been added"*.

Require a concrete noun and verb — add, move, relabel, remove — commit to the one
we think is right, and move the rejected half into `alternatives`, which is read at
`executor.py:3761` and never written. The acceptance test is the interesting part:
**reject any recommendation that would read identically on a different page.** A
recommendation carrying no noun drawn from the page under test is a failed
generation, not a recommendation.

Note that `_finding_slide` currently synthesises `alternatives` from the
recommendation when the field is empty. That fallback exists because the field was
never filled; it goes when A1 fills it.

### A2. Stop the slide falling back to the symptom

`executor.py:3760` still resolves the root-cause panel as `rootCause or mechanism
or observation`. With A1's root cause now generated, that last fallback is the only
remaining path by which the symptom can print in a box labelled analysis — for
findings from sources that set no `rootCause`. A panel that cannot be filled
honestly should render **nothing**. `executor.py:3811` already refuses to print it
when it equals the issue text; this is the same rule, applied one step earlier.

### A3. Say how you would know it worked

Nothing in the tree does this. Every finding is a falsifiable prediction: fix this
and the persona's expectation holds next run. Emit a re-test line per finding — the
persona, the task, the expectation that should hold — and re-run it against the
fixed page. No human review can close that loop; it is the thing to be known for.

### A4. Report yield, from the worksheet's own list

The worksheet §2 is better grounded than the audit here, because it is measured
over seven reports rather than one:

- **Say what worked.** `elements_to_preserve` is empty in 6 of 7 reports, though the
  perception data already knows what was legible, prominent and found quickly. A
  review that only lists faults is half a review.
- **Stop filing our own run as the leading finding.** "Users could not finish the
  tasks" leads at high severity with a recommendation about reading our report.
  `run_diagnostics` exists for this and now works.
- **Add a deterministic sweep** — contrast, tap-target size, heading order, alt
  text, form labels — so coverage does not depend on a persona stumbling onto
  something. All measurable on captures already taken.
- **A scorecard**: task success, actions taken, where each run stopped. The numbers
  are in the timeline and are never totalled.

*Done when:* a report carries ten or more findings about the site, at least two of
them positive.

## Track B — the backend

### B1. Route runs through the settings store *(first, and blocking)*

As above. `chain()` returns an ordered list precisely so the second entry is the
fallback; make the run walk it, record which provider actually served each call,
and stop reading provider keys out of the environment at `executor.py:3366` and
`executor.py:3417`. A run served by the fallback is a run whose reproducibility
claim differs, so the served provider belongs in the report.

### B2. Extract the report assembler

`apps/api/executor.py` is **3843 lines** and holds both the run half and the report
half. Track A rewrites the report half; B1 rewrites the run half. They will collide
on every commit. `services/report-service/` exists and contains only `__init__.py`.

**A single mechanical commit** — move the finding builders, report assembly and
slide rendering across, change no behaviour, keep every test green. Both other
tracks rebase onto it. It is worth more than it looks: it is the difference between
three tracks running in parallel and three tracks taking turns.

### B3. Cost and time accounting

Nothing records tokens or wall time. Two reasons to add it: the economic case is
never made in the artifact itself, and A1 and A3 both add model calls, so without
it we cannot say what the better report costs.

### B4. The noise floor *(the worksheet's §0, and it gates judging any of this)*

Every number in the record is n=1 per commit, and `refused` has swung by a factor
of four between cycles that changed nothing relevant. Run the same commit three
times, record min/max of `refused`, `legibleShare` and completed runs, and write it
into `spec.md` as the noise floor.

*Done when:* a later cycle can be called better or worse than this one with a
reason. **No item in this plan can be called an improvement before this exists.**

### B5. Concurrency and repeat runs

Personas run sequentially, so time grows linearly, and a three-person cohort is
about 20 minutes. Repeat runs at different seeds turn A8/G6 into a real claim — a
finding seen in 2 of 2 runs is a different claim from 1 of 2. Both land after B1,
because concurrency against a provider with no working fallback multiplies the
failure mode B1 exists to fix.

## Track C — hats, capabilities and `/webui`

Design rationale in `docs/next-cycle-worksheet.md`. A hat is what the agent can
**do** (`Tool`s in `Faculty`), what it **knows** (`PersonaMemoryBank`, the profile),
and what it **thinks with** (the `model_settings.py` roles — which exist, and which
B1 makes real).

### C0. The ground layer — the scan accumulates *(nothing hat-shaped ships first)*

The worksheet measures this precisely on cycle 51's 26 captures: `fixated` is **6
on every single capture** whatever the page offered; consecutive captures fixate the
**identical six**; `e10` was among them in 23 of 26; **19 of 43** elements were ever
looked at; and `notLookedAt` never falls — 14, 13, 13, 13, 14, 14…

The mechanism is `services/perception_service/perceive.py:283`:

```python
fixated = {item["selector"] for item in fixations}
not_looked_at = [item for item in candidates if item["selector"] not in fixated]
```

`fixated` is rebuilt from *this call's* fixations alone. The scan has no memory
between looks, so a `READ` can never make progress, and with `stepBudget()` at
`min(40, max(12, tasks * 8))` = **16** for the standard two-task journey
(`journeytest.js:197`), the budget always runs out. Eleven of twelve inconclusive
runs ended on exactly 16.

A persona that re-reads the same six things for sixteen steps will do exactly that
with a terminal and a login — burning a larger budget across a bigger surface, with
failures much harder to read. A `RUN` taken by an agent that has not noticed it
already ran that command is not a capability; it is a loop with a shell.

Two cheap siblings, both costing steps out of the same 16 and both in the
worksheet's trace: the **billing-toggle oscillation** (`e17`/`e18` clicked back and
forth up to six times) and **scrolling to an offset the page already holds**
(`SCROLL:600` nine times in one run).

*Done when:* `notLookedAt` falls across a run instead of holding at 13–14, and two
of three runs reach a verdict other than inconclusive.

### C1. `/webui` — the configuration surface *(the main thing that does not exist)*

Modelled on the plain llama.cpp provider-connection flow: an OpenAI-compatible
endpoint, a model list fetched from `/v1/models`, per-role selection. The store and
the roles are already there; this is the surface over them, and the place a hat is
edited.

```
apps/webui/
  __init__.py
  router.py            # APIRouter mounted at /webui
  static/              # index.html, app.js, style.css -- no build step
```

Mounted on `fastapi_app` **before** `gr.mount_gradio_app(fastapi_app, demo,
path="/")`, because the Gradio mount at `/` otherwise swallows it.

| Route | Purpose |
| --- | --- |
| `GET /webui` | The page |
| `GET /webui/api/models` | Server-side `GET {base}/v1/models`; model ids only |
| `GET`/`PUT` `/webui/api/settings` | Per-role provider rows, over `ModelSettingsStore` |
| `GET`/`PUT` `/webui/api/hats[/{id}]` | The registry: read, individualize, create |
| `POST` `/webui/api/chat/completions` | Bounded passthrough, so "does this answer" is one click |

**Enabled as an advanced option**, off by default: `AUX_WEBUI_ENABLED=1`. Disabled,
the routes are never registered rather than returning 403 — a surface that does not
exist cannot be misconfigured.

Three rules, all of which the codebase already models:

1. **It reuses workspace authentication and the built-in-provider reservation.**
   `may_use_built_in_providers()` already decides who may spend the deployment's
   keys; `/webui` is subject to it, not an exception to it.
2. **It never returns a key.** Settings store the *name* of an environment
   variable, as `KIND_REFERENCE` does. Where an endpoint is echoed, echo scheme and
   host only — `build_model_provider_probe()` already does exactly this.
3. **The passthrough is bounded.** Rate-limited, size-capped, a connectivity check
   rather than a chat product.

### C2. The hat registry

A hat is a record: mounted tool set, profile defaults, role-to-provider assignments,
and capability grants (plugins, MCP servers). `browsingFaculty()` (`faculty.js:294`)
is already the one place the mounted set is chosen; it becomes `facultyForHat()`.
Because `Faculty.actionsDefinitionsPrompt()` (`faculty.js:254`) assembles the
vocabulary from whatever is mounted, a hat that adds a tool adds vocabulary without
touching the director. Ship the named hats as presets; the registry is what makes
them editable rather than hardcoded.

The worksheet's **capability manifest** belongs here: a report should state which
hat produced a finding and what that hat could reach, because "I could not find the
retention policy" means different things from a browser and from a docs search.

### C3. Front-tab links

In the first Gradio tab, a row of buttons opening `/webui` deep links: **Developer
Mode** (`/webui#developer`), one per preset hat (`/webui#hat=<id>`), and **Model &
capabilities**. Each is a real URL, so it still works pasted to a colleague. Hidden
when `AUX_WEBUI_ENABLED` is unset, rather than linking to a 404.

### C4. Hat 2 — redaction *(parallel with C0; gates any real signed-in run)*

The one piece of hat work with no dependency on the ground layer: it touches
`safety.js` and the evidence path, not the director.

Every screenshot, crop, snapshot and `beneath` probe in a signed-in run may carry
an account name, an email, an invoice. `redactSensitive()` (`safety.js:34`) redacts
*values*; nothing redacts pixels, and nothing redacts the accessibility tree.
Evidence needs the same treatment for both before anything is written to an
artifact — and before this is offered to anyone whose account is not their own test
account.

Plus: prefer stored session state to replaying a password, and detect mid-run
expiry — a run that silently becomes logged-out reviews the logged-out product and
says nothing about it, which is the worst failure available because it is invisible
in the output.

*Done when:* a run signs in, reviews a journey behind the login, and its report
carries no account identifier anywhere in text or evidence.

### C5. Hat 3 — developer mode

`FETCH`, `INSPECT`, `RUN`, `AUTHENTICATE`, mounted as `DeveloperTool` alongside
`BrowserTool` with `realWorldSideEffects = true`. **The safety design is the
feature, not a wrapper around it** — the worksheet's seven-item list is the
specification, not hardening to add afterwards, and if any item is dropped the hat
does not ship. In short: off unless a run asks for it (the
`allowIrreversibleActions` shape — mounted-then-guarded is one bug from ungated);
an allowlist with a constructed argv, never a shell; a scratch directory destroyed
with the run; an environment built empty rather than inherited from a worker
holding every provider key; egress only to declared hosts through `privateHost()`;
output through `sanitizeUntrustedText()`; and every invocation in the timeline like
a click.

### C6. Hat 4 — role hats, and the gate that rejects most of them

Evaluator, administrator, integrator, compliance reader — with one rule: **a hat
earns its place only if it changes what the system does, not what it says.** Same
actions in a different tone is a prompt and belongs in a persona profile. Applied
honestly this rejects some of the four, which is why it is written down before they
are built rather than after.

## How the three tracks run in parallel

`B2` (the extraction) lands first and alone; everything rebases onto it. `B1` is
the other thing with a queue behind it. After those two, the tracks own disjoint
files:

| Track | Owns | Must not touch |
| --- | --- | --- |
| A — report | `services/report-service/**` | the run half, `app.py` |
| B — backend | `executor.py` run half, `apps/api/model_*.py`, `app.py` readiness | `services/report-service/**` |
| C — hats | `apps/webui/**`, `services/journey-worker/node/src/**`, `services/perception_service/**`, `app.py` tab links | `services/report-service/**`, `executor.py` |

`app.py` is touched by B (readiness) and C (tab links), in different functions
hundreds of lines apart; `docs/` is touched by all three. Both are ordinary merges.

```
B2 ──┬── B1 ──┬── B3
     │        ├── B5
     │        └── C1 ── C2 ── C3 ── C5 ── C6
     │
     ├── A1 ── A2 ── A3 ── A4
     │
     └── C0 (+ the two loop fixes)
         C4   (parallel with C0; gates any real signed-in run)
         B4   (independent, and gates calling anything an improvement)
```

`C1` needs `B1` because a `/webui` that configures models no run reads is worse than
no setting at all. `A1` does not need `B1` — the root-cause generation it builds on
already ships.

## Risks worth naming now

- **`/webui` becoming an open proxy to the provider key.** The largest new attack
  surface here, and the deployment's keys are exactly what `model_settings.py` was
  written to reserve. Mitigated by C1's three rules and by the routes not existing
  when `AUX_WEBUI_ENABLED` is unset.
- **Hat 3 is remote code execution by design.** The guard list is the spec.
- **Hat 2 without C4 leaks real account data** into artifacts and into outbound
  vision-critique request bodies.
- **Track A raises cost per review.** A1 and A3 add model calls; B3 exists so this
  is measured rather than discovered.
- **Judging any of this on one run.** `refused` has swung fourfold with nothing
  relevant changed. B4 is not optional overhead; it is what makes the rest
  reviewable.

## What "done" looks like

- No recommendation in a generated deck would read identically on a different page,
  and `alternatives` carries the committed-against option rather than being faked
  from the recommendation at render time.
- A panel that cannot be filled honestly renders nothing.
- A run routes through `ModelSettingsStore.chain()`, degrades to the second
  provider instead of ending, and the report says which provider served it.
- `notLookedAt` falls across a run, and two of three runs reach a verdict.
- `/webui` is reachable with `AUX_WEBUI_ENABLED=1`, configures per-role models a
  run actually uses, and returns no secret under any route.
- A hat created in `/webui` mounts a different tool set, and the persona's action
  vocabulary changes with no director change.
- A signed-in run produces no artifact containing unredacted account data.
- A noise floor is recorded in `spec.md`, so the next cycle can be called better or
  worse with a reason.
