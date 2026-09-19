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

**Naming.** Plan items are `RPT-n` (report), `BE-n` (backend) and `CAP-n`
(capabilities/hats). A bare letter-digit code like `B2` or `E7` always means a
criterion of the audit, never a plan item — an earlier draft used `A1`/`B1`/`C1` for
both and the two were indistinguishable. `Hat 1`–`Hat 4` are the worksheet's hats.

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

Anything below that cites the audit cites it as re-verified, not as received.

**But "out of date" is not "handled".** An earlier draft of this plan used the table
above to shrink Track A to four items, and in doing so quietly dropped about
twenty-five criteria that were neither closed nor argued away — including B2,
convention-based reasoning, which the audit rates critical and calls the benchmark's
entire advantage. The appendix at the end now accounts for **all 68**: 8 held,
11 closed, 38 carried into a named item, 11 deferred with a reason. A criterion that
is not worth doing is worth saying so about; one that simply vanishes between drafts
makes the plan look more finished than it is.

The re-verification still changes the shape of the work: the report track's centre of
gravity moves from "the root cause is the symptom restated" — closed — to
recommendations and to the depth of a root cause that now exists.

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
cycles: a store, a dialog, a test suite, and no consumer. It is **BE-1**, it is the
first backend deliverable, and both `/webui` and the per-hat model assignment are
blocked on it — configuring a model that no run reads is worse than not offering
the setting.

## Track A — the report

### RPT-1. Commit to one concrete change *(the largest remaining report defect)*

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
never filled; it goes when RPT-1 fills it.

### RPT-2. Give the root cause depth, and stop it falling back to the symptom

The generation already exists — `_why_they_expected_that()` (`executor.py:1694`). This
is about what it is asked, and what happens when it declines to answer.

**The fallback.** `executor.py:3760` still resolves the panel as `rootCause or
mechanism or observation`. For any finding whose source sets no `rootCause`, the
symptom still prints in a box labelled analysis. A panel that cannot be filled
honestly should render **nothing**. `executor.py:3811` already refuses to print it
when it equals the issue text; this is the same rule one step earlier. Pair it with
the audit's E8 rule: refuse any panel whose text substantially repeats another on the
same slide, and treat that as a generation failure rather than hiding it.

**The depth.** Four audit criteria — three absent, one partial — all answerable by the
same call with more in its prompt, and none needing data we do not already hold:

- **Name the convention** (B2, absent, critical). The benchmark's best sentences are
  all this shape: *"as this is the case on other free apps"*, *"users expect chat
  icons to open as pop-up windows as they are used to this from other services"*.
  That is *why* the expectation existed, and the audit calls it the benchmark's
  entire advantage. Mark it explicitly as inference, never as measurement, so it
  cannot be mistaken for something observed.
- **Name the property that set it** (B6, partial). Which part of the control — the
  label, the position, the grouping, the colour. The element's measured properties
  are in the group already. *"The word `trial` on a primary button"* is a root cause;
  *"they expected a trial"* is the symptom again.
- **Name the mechanism** (B4, absent, high). We use scan pattern, fixation budget,
  goal pull and acuity internally and name none of them in a finding. The audit's
  version of this stings: the benchmark *opens* by declaring it is based on knowledge
  about human cognition, and we have more of that machinery than it does and hide all
  of it. **Gated on CAP-0** — with a scan that has no memory, "this sat outside the
  F-pattern their eye followed" is not a safe claim.
- **State the mental model** (B3, weak). Summarise each persona's expectations across
  the whole run into one stated model of what they thought the product *was*, then
  note where the page contradicted it.

And one quote fix (F5): quote the persona's **affect** line — what they felt — rather
than the factual reflection, which is what makes a quote worth printing at all.

### RPT-3. Say how you would know it worked

Nothing in the tree does this. Every finding is a falsifiable prediction: fix this
and the persona's expectation holds next run. Emit a re-test line per finding — the
persona, the task, the expectation that should hold — and re-run it against the
fixed page. No human review can close that loop; it is the thing to be known for.

### RPT-4. Report yield — what gets found

The worksheet §2 is better grounded than the audit on yield, because it is measured
over seven reports rather than one. Its list, plus the audit's coverage gaps:

- **Say what worked** (D9). `elements_to_preserve` is empty in 6 of 7 reports, though
  the perception data already knows what was legible, prominent and found quickly.
  Ground each one in a *met* expectation — this control did what the visitor
  predicted, first try — rather than generic praise. A review that only lists faults
  is half a review.
- **Stop filing our own run as the leading finding.** "Users could not finish the
  tasks" leads at high severity with a recommendation about reading our report.
  `run_diagnostics` exists for this and now works.
- **A deterministic sweep** (D4). Contrast is done and strong; add target size, focus
  visibility, heading order, alt text and form labels, so coverage does not depend on
  a persona stumbling onto something. All measurable on captures already taken.
- **Promote a corroborated read gap** (A7, D6). One person misreading a block is
  perception; three is the page. Both criteria ask for the same rule. **Gated on
  CAP-0**, and this is the sharpest case for that gate: today a read gap is partly an
  artefact of our own scan having no memory, so promoting one now would publish our
  bug as the page's.
- **Grouped controls whose actions differ in kind** (D7). The geometry is already
  captured. Proximity implying similar function is a relationship *between* elements,
  not a property of one, which is why no per-element check finds it.
- **A wait that exceeds this person's tolerance** (D8). Modelled per persona and
  never reported.
- **A scorecard** (A2). Task success, actions taken, where each run stopped — and
  **expectations met vs missed**, which is already in the log as `matched`. A report
  that only shows misses hides its own hit rate.

*Done when:* a report carries ten or more findings about the site, at least two of
them positive, and states its own hit rate. H5 follows from this and BE-5 together:
the floor rises without anything being invented.

### RPT-5. Evidence and re-design in the product's own language

Two items the audit rates high, both with the data already in hand:

- **Annotate the evidence** (E7, absent, high). Bare screenshots make a reader hunt
  for the thing being discussed. Draw the element's box and a number onto the
  capture, straight from coordinates already held — `elementBox` has shipped on
  findings since the cropping work.
- **Draw the re-design in the product's own language** (C4, weak, high). The
  re-design panel is live, working, sandboxed HTML, which the audit rates a category
  advantage over the benchmark's flat image — and it renders a generic `#0066ff`
  button on white in system-ui, so it reads as a sketch rather than a proposal. The
  measured palette, type sizes and radii are all collected by the element walk
  already; pass them into the prompt. While there, label the frame as working code
  and offer the source beside it (C3).

### RPT-6. The reader-facing lines

Seven changes at the render boundary, over data already computed. Grouped because
each is a line or two; kept separate from RPT-4 because none of them changes what the
system *finds* — only what a reader is told.

| Audit | Change |
| --- | --- |
| B7 | Print the severity derivation beside the chip: "medium — one person, a fifth of their patience, not blocking" |
| F1 | Lead the summary with the judgement — what works, where it loses people, the one thing to change. Counts underneath |
| F2 | State scope as intent up front, including **what was not reviewed** |
| F8 | Order findings by the step at which they occurred, so they accumulate into a story; severity governs only the "fix first" slide |
| G4 | Print `evidence_language: observed` on the introduction slide — the strongest sentence we can write about ourselves, and it never reaches the reader |
| E11 | Run our own luminance check over the deck palette in the test suite. A contrast review that fails contrast would be embarrassing, and nothing checks it |
| A9 | Record model id and temperature per run, and say plainly that the persona's wording is not reproducible, only its disposition (rides with BE-3) |


## Track B — the backend

### BE-1. Route runs through the settings store *(first, and blocking)*

As above. `chain()` returns an ordered list precisely so the second entry is the
fallback; make the run walk it, record which provider actually served each call,
and stop reading provider keys out of the environment at `executor.py:3366` and
`executor.py:3417`. A run served by the fallback is a run whose reproducibility
claim differs, so the served provider belongs in the report.

### BE-2. Extract the report assembler

`apps/api/executor.py` is **3843 lines** and holds both the run half and the report
half. Track A rewrites the report half; BE-1 rewrites the run half. They will collide
on every commit. `services/report-service/` exists and contains only `__init__.py`.

**A single mechanical commit** — move the finding builders, report assembly and
slide rendering across, change no behaviour, keep every test green. Both other
tracks rebase onto it. It is worth more than it looks: it is the difference between
three tracks running in parallel and three tracks taking turns.

### BE-3. Cost and time accounting

Nothing records tokens or wall time. Two reasons to add it: the economic case is
never made in the artifact itself, and RPT-1 and RPT-3 both add model calls, so without
it we cannot say what the better report costs.

### BE-4. The noise floor *(the worksheet's §0, and it gates judging any of this)*

Every number in the record is n=1 per commit, and `refused` has swung by a factor
of four between cycles that changed nothing relevant. Run the same commit three
times, record min/max of `refused`, `legibleShare` and completed runs, and write it
into `spec.md` as the noise floor.

*Done when:* a later cycle can be called better or worse than this one with a
reason. **No item in this plan can be called an improvement before this exists.**

### BE-5. Concurrency and repeat runs

Personas run sequentially, so time grows linearly, and a three-person cohort is
about 20 minutes. Repeat runs at different seeds turn A8/G6 into a real claim — a
finding seen in 2 of 2 runs is a different claim from 1 of 2. Both land after BE-1,
because concurrency against a provider with no working fallback multiplies the
failure mode BE-1 exists to fix.

## Track C — hats, capabilities and `/webui`

Design rationale in `docs/next-cycle-worksheet.md`. A hat is what the agent can
**do** (`Tool`s in `Faculty`), what it **knows** (`PersonaMemoryBank`, the profile),
and what it **thinks with** (the `model_settings.py` roles — which exist, and which
BE-1 makes real).

### CAP-0. The ground layer — the scan accumulates *(nothing hat-shaped ships first)*

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

### CAP-1. `/webui` — the configuration surface *(the main thing that does not exist)*

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

### CAP-2. The hat registry

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

### CAP-3. Front-tab links

In the first Gradio tab, a row of buttons opening `/webui` deep links: **Developer
Mode** (`/webui#developer`), one per preset hat (`/webui#hat=<id>`), and **Model &
capabilities**. Each is a real URL, so it still works pasted to a colleague. Hidden
when `AUX_WEBUI_ENABLED` is unset, rather than linking to a 404.

### CAP-4. Hat 2 — redaction *(parallel with CAP-0; gates any real signed-in run)*

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

### CAP-5. Hat 3 — developer mode

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

### CAP-6. Hat 4 — role hats, and the gate that rejects most of them

Evaluator, administrator, integrator, compliance reader — with one rule: **a hat
earns its place only if it changes what the system does, not what it says.** Same
actions in a different tone is a prompt and belongs in a persona profile. Applied
honestly this rejects some of the four, which is why it is written down before they
are built rather than after.

## How the three tracks run in parallel

`BE-2` (the extraction) lands first and alone; everything rebases onto it. `BE-1` is
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
BE-2 ──┬── BE-1 ──┬── BE-3
       │          ├── BE-5 ──── RPT-4 (H5), RPT-6 (A9 rides with BE-3)
       │          └── CAP-1 ── CAP-2 ── CAP-3 ── CAP-5 ── CAP-6
       │
       └── RPT-1 ──┬── RPT-3
                   ├── RPT-5
                   └── RPT-6

CAP-0 (+ the two loop fixes) ──┬── RPT-2 (the B4 mechanism item only)
                               └── RPT-4 (the A7/D6 read-gap item only)

CAP-4   — independent of both, gates any real signed-in run
BE-4    — independent, and gates calling any of it an improvement
```

`CAP-1` needs `BE-1` because a `/webui` that configures models no run reads is worse
than no setting at all. `RPT-1` needs nothing — the root-cause generation it builds on
already ships.

**Two items are partly gated on `CAP-0`, and only partly.** `RPT-2` can name the
convention, the property and the mental model immediately; only its *mechanism* claim
waits, because a scan with no memory cannot support "this sat outside the F-pattern
their eye followed". `RPT-4` can do everything except promote a corroborated read gap,
which would publish our own scan's blind spot as the page's. Both start now and finish
after `CAP-0`; neither is blocked as a whole.

## Risks worth naming now

- **`/webui` becoming an open proxy to the provider key.** The largest new attack
  surface here, and the deployment's keys are exactly what `model_settings.py` was
  written to reserve. Mitigated by CAP-1's three rules and by the routes not existing
  when `AUX_WEBUI_ENABLED` is unset.
- **Hat 3 is remote code execution by design.** The guard list is the spec.
- **Hat 2 without CAP-4 leaks real account data** into artifacts and into outbound
  vision-critique request bodies.
- **Track A raises cost per review.** RPT-1 and RPT-3 add model calls; BE-3 exists so this
  is measured rather than discovered.
- **Judging any of this on one run.** `refused` has swung fourfold with nothing
  relevant changed. BE-4 is not optional overhead; it is what makes the rest
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

## Appendix: all 68 audit criteria, and where each one went

The audit *Observed vs Explained* (cycle 26) is the origin of Track A and of several
Track B items. Carrying it forward selectively without saying so would make the plan
look more complete than it is, so every criterion is listed here with one of four
dispositions:

- **held** — already strong; the work is not losing it.
- **closed** — the audit named a gap and this tree closes it, with the anchor.
- **carried** — in the scope of a named plan item.
- **deferred** — consciously not this cycle, with the reason. Not the same as forgotten.

**8 held · 11 closed · 38 carried · 11 deferred.**

Standing and weight are the audit's own, at cycle 26. Where a standing reads "strong"
and the disposition is "closed", the audit rated the criterion strong but named a
residual gap, and it is that gap which closed.

### A — Evidence and epistemic strength (10)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| A1 | Evidence basis: observed or predicted | strong | critical | **held** — Protect it. No generated sentence enters a finding unless a recorded event backs it. |
| A2 | Falsifiability of each claim | strong | critical | **carried** — → **RPT-4** — met vs missed as a run statistic; already logged as `matched`. |
| A3 | Cost quantification | strong | high | **closed** — `_patience_in_words(cost)` anchors the scale in words. |
| A4 | Artifact traceability | strong | high | **deferred** — Stamp each evidence figure with its step number and elapsed time. Render-boundary, nothing depends on it. |
| A5 | Contradiction checking against the run | strong | high | **closed** — Five claim types now checked. Residue — a claim about something the run never looked at — is worksheet §3 #39. |
| A6 | Absence of finding vs absence of measurement | strong | high | **closed** — `_instrument_diagnostics` + `_coverage_diagnostics` (`executor.py:698`). |
| A7 | Cross-persona corroboration | partial | high | **carried** — → **RPT-4**, gated on CAP-0. Same rule as D6. |
| A8 | Sample size and variance | weak | high | **carried** — → **BE-5** — repeat runs at a second seed. |
| A9 | Reproducibility | partial | medium | **carried** — → **RPT-6**, riding with BE-3's per-run provider and model record. |
| A10 | Honesty when the run fails | strong | critical | **held** — Residue — lower confidence on findings from an incomplete run — goes with B8 into **BE-5**. |

### B — Root cause analysis (8)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| B1 | Root cause, or the symptom said twice | weak | critical | **closed** — `_why_they_expected_that()` (`executor.py:1694`), used at `executor.py:1821`. |
| B2 | Convention-based reasoning | absent | critical | **carried** — → **RPT-2**. The audit calls this the benchmark's entire advantage. |
| B3 | Mental-model articulation | weak | high | **carried** — → **RPT-2** — one stated mental model per persona per run. |
| B4 | Cognitive principle cited | absent | high | **carried** — → **RPT-2**, gated on CAP-0: a scan with no memory cannot support a scan-path claim. |
| B5 | Trait linkage — why this user | absent | high | **closed** — `_traits_behind(group)` (`executor.py:1827`). |
| B6 | Where the expectation came from | partial | medium | **carried** — → **RPT-2** — which property of the control set the expectation. |
| B7 | Severity justification | strong | high | **carried** — → **RPT-6** — print the derivation beside the chip. |
| B8 | Per-finding confidence | partial | medium | **carried** — → **BE-5** — confidence needs a reproduction count to mean anything. |

### C — Recommendations (9)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| C1 | Specificity of the design move | weak | critical | **carried** — → **RPT-1**. |
| C2 | One named change per finding | weak | high | **carried** — → **RPT-1**. |
| C3 | Developer-ready output | strong | high | **carried** — → **RPT-5** — label the frame as working code, offer the source. |
| C4 | Visual fidelity of the re-design | weak | high | **carried** — → **RPT-5** — the measured palette, type and radii are already collected. |
| C5 | Alternative solutions | absent | high | **carried** — → **RPT-1** — the rejected half of the either/or belongs here. |
| C6 | Trade-offs named | absent | medium | **carried** — → **RPT-1** — one sentence on what the change costs, or drop the recommendation. |
| C7 | Effort and impact framing | absent | medium | **carried** — → **RPT-1** — class each change as copy, layout or behaviour. |
| C8 | How you would know it worked | absent | high | **carried** — → **RPT-3**. |
| C9 | Prioritisation | partial | medium | **carried** — → **RPT-1** — order on cost x people x effort class, and print the rule. |

### D — Problem identification and coverage (10)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| D1 | Flow coverage | partial | critical | **carried** — → **CAP-0** — the 16-step budget is what caps coverage today. Flow-per-journey task shape deferred with G2. |
| D2 | Multi-step journeys | partial | high | **carried** — → **CAP-4** — Hat 2 is what reaches anything behind a login. |
| D3 | Localisation and language | absent | medium | **deferred** — Locale as a persona attribute plus a mismatch finding class. No measurement in hand; nothing depends on it. |
| D4 | Accessibility and contrast | strong | high | **carried** — → **RPT-4** — target size, focus visibility, heading order, alt text, form labels. |
| D5 | Legibility as this person sees it | strong | high | **closed** — Already fixed per the audit. Verify it produces a finding on the next run that hits it. |
| D6 | Copy and content findings | partial | medium | **carried** — → **RPT-4**, gated on CAP-0. Same rule as A7. |
| D7 | Information architecture and grouping | weak | high | **carried** — → **RPT-4** — grouped controls whose actions differ in kind. |
| D8 | Performance and waiting | absent | low | **carried** — → **RPT-4** — a wait beyond this person's modelled tolerance. |
| D9 | Positive findings | strong | medium | **carried** — → **RPT-4** — ground each in a met expectation. |
| D10 | Error, empty and edge states | absent | medium | **deferred** — Needs a task shape that deliberately submits something invalid, inside the destructive-action rules. A new capability, not a report change. |

### E — Report craft (12)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| E1 | Deck format at 16:9 | strong | medium | **held** — — |
| E2 | Section numbering that means something | strong | low | **deferred** — Suppress sub-numbering below two findings in a group. Cosmetic. |
| E3 | Contents page | strong | low | **held** — — |
| E4 | Authorship and dating | partial | low | **deferred** — Name the method and version as author, with run date and job id. Cosmetic. |
| E5 | Template consistency across findings | strong | high | **closed** — Follows B1; the template was already right. |
| E6 | Before and after, side by side | strong | high | **closed** — `elementBox` carried for cropping (`executor.py:1819`). |
| E7 | Annotation on evidence | absent | high | **carried** — → **RPT-5** — draw the box and a number from coordinates already held. |
| E8 | Redundancy control | weak | high | **closed** — The instance is closed (`personaEvidence` takes `sightings`, `executor.py:1826`). The general render guard → **RPT-2**. |
| E9 | Typography | partial | medium | **deferred** — One display and one body face at a fixed scale. Cosmetic. |
| E10 | Colour as information | partial | medium | **deferred** — One hue per flow group through divider, chip and callout. Cosmetic. |
| E11 | The report's own accessibility | partial | medium | **carried** — → **RPT-6** — luminance check over the deck palette, in the test suite. |
| E12 | Portable export | absent | medium | **deferred** — Print stylesheet with page breaks. **Top of this list**: the benchmark is a PDF, and a PDF is what gets mailed to a client. |

### F — Narrative and audience (8)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| F1 | Executive summary | partial | high | **carried** — → **RPT-6** — lead with the judgement, counts underneath. |
| F2 | Scope stated up front | partial | medium | **carried** — → **RPT-6** — scope as intent, including what was *not* reviewed. |
| F3 | Method disclosure | strong | high | **held** — Keep it short enough that it is read. |
| F4 | Audience targeting | weak | medium | **deferred** — A one-page summary pitched at whoever commissioned the run. |
| F5 | Quotation from the user | strong | high | **carried** — → **RPT-2** — quote the affect line, not the factual reflection. |
| F6 | Jargon control | partial | medium | **closed** — `_plural()` / `verb()` helpers. |
| F7 | Length discipline | strong | low | **held** — — |
| F8 | Arc across findings | absent | medium | **carried** — → **RPT-6** — order by the step at which it happened. |

### G — Process transparency (6)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| G1 | Persona provenance | strong | medium | **deferred** — A "who we sent" slide contrasting the personas on the traits that mattered. |
| G2 | Task provenance | partial | medium | **deferred** — Constrain task generation at the point of generation. See worksheet ground rule 3 — the last guard here failed by producing less. |
| G3 | Run diagnostics reaching the reader | weak | high | **closed** — `_instrument_diagnostics` + `_coverage_diagnostics` (`executor.py:698`). |
| G4 | Evidence language declared | strong | medium | **carried** — → **RPT-6** — one line on the introduction slide. |
| G5 | Schema versioning | strong | low | **held** — — |
| G6 | Stability across repeat runs | weak | high | **carried** — → **BE-5**. |

### H — Operational (5)

| | Criterion | Standing | Weight | Disposition |
| --- | --- | --- | --- | --- |
| H1 | Turnaround | strong | high | **held** — — |
| H2 | Cost per review | strong | high | **carried** — → **BE-3**. |
| H3 | Scaling to more users | strong | high | **carried** — → **BE-5**. |
| H4 | Reliability | partial | critical | **carried** — → **BE-1**. Routing through `chain()` *is* the fallback fix. |
| H5 | Consistency of output volume | weak | high | **carried** — → **RPT-4** and **BE-5** together — the floor rises without anything being invented. |
