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

### RPT-1. Commit to one concrete change — **done**

*(Line references below are as originally written; after BE-2 the report half moved
to `services/report_service/assembler.py`. The recommendation string was at
`assembler.py:1037` when this landed.)*

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

**What shipped.** A committed recommendation and a real `alternatives` entry for
`_broken_promise_finding` (`"Promised more than it did: …"` — the worksheet's own
worked example, "Start 3-day free trial"), decided by one rule read from data the
run already recorded rather than asked of a model: **nothing visible happened** →
commit to building the behaviour the label already promises (the label is the
evidence of intent; the cheapest fix is to make it true) — **something happened,
just not what was promised** → commit to relabelling, since the behaviour already
exists and evidently works. Both branches embed the control's own `label`, so two
different pages produce two different sentences, which is what the acceptance test
checks. The rejected half of the either/or moves to `alternatives`, with a stated
rationale, and `_finding_slide`'s synthesis fallback is now unreachable for this
finding type without being deleted for the finding types that still need it.

`_committed_recommendation()` shares its classification (`label`, `wanted`, `silent`)
with `_why_they_expected_that()` (RPT-2's root-cause generation) through a new
`_expectation_shape()` — factored out rather than duplicated, so the recommendation
and the root cause can never reason from two different readings of the same
encounter. This is a template, not a model call, matching how `_why_they_expected_that`
already worked: the commitment is defensible because it is read from what the run
measured (did anything visible happen, and what verb did the visitor's own words
use), not invented.

Five new tests, including the plan's own acceptance criterion made concrete: two
different `label`s produce two different, non-identical sentences, each containing
its own control's name.

### RPT-2. Give the root cause depth, and stop it falling back to the symptom — **done**

The generation already exists — `_why_they_expected_that()` (`executor.py:1694`, now
`services/report_service/assembler.py` post-BE-2). This is about what it is asked, and
what happens when it declines to answer.

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

**What shipped.** The fallback: `_finding_slide`'s root-cause panel now reads only
`item.get("rootCause")` -- no `mechanism`, no `observation` -- and is left out
entirely when there is none, per the stated rule. E8: `_panel_duplicates()` (Jaccard
overlap on stemmed content words, threshold 0.45 -- higher than
`_merge_similar_findings`' 0.18 same-issue bar, since two panels on one slide are
expected to share more vocabulary before one is truly saying nothing new) replaces
the old byte-equality check, so a paraphrase of the symptom is refused the same as
an exact repeat. B2: `_why_they_expected_that()` now closes with a convention
sentence keyed on the same `wanted` classification RPT-1 already computes, explicitly
prefixed "This rests on a general web convention, not something this run measured" --
never phrased as though this run had observed another site, because it has not. B3:
new `_persona_mental_model()` walks a persona's whole
`persona.expectation`/`persona.reflection` timeline (not only the unmet pairs the
broken-promise findings group), classifies each with the same verb-matching RPT-1
uses, and states the dominant pattern and how often it held -- `""` rather than a
guess when fewer than two expectations exist to support a stated pattern. Wired onto
`persona_narration[].mentalModel` in `executor.py`. F5: a `feelings` list, sourced
from `persona.affect`'s own `feeling` text (already recorded by
`personaDirector.js`'s `affectInWords()`, previously read nowhere on the Python
side), now takes priority in `_broken_promise_finding`'s `personaEvidence` over
`sightings` and the factual `gaps` quote.

**B4 ("name the mechanism"), found already substantially shipped rather than
built new.** Checked against the audit's own complaint ("scan pattern, fixation
budget, goal pull and acuity... name none of them in a finding") against the
current code, not the plan's description of code as it stood when written:
`_never_looked_at_finding`'s summary already states the scan pattern, fixation
budget and the "why" reasons inline (`{scan.get('pattern')}` etc.), and
`_unreadable_finding`'s `rare_only` branch already cites acuity and contrast
sensitivity. Duplicating either into a separate `rootCause` field would itself be
refused by the new E8 check as a near-duplicate of the issue panel that already
states it, so the root-cause panel is correctly absent for these two finding
classes today -- an honest absence per this section's own fallback rule, not a
gap. Nothing was built here because nothing was missing once checked against the
tree rather than the plan's own two-cycle-old description of it.

**Tests.** Five new: E8's paraphrase refusal, B2's convention sentence and its
explicit inference marker, B3's mental-model text (both the isolated method and an
end-to-end `combined_test` run reaching `persona_narration`), and F5's
quote-priority (feeling present vs. absent, falling back to sightings never
straight to the factual gap). One existing test rewritten for the removed
fallback (the byte-equality check it exercised is now folded into E8's broader
one) rather than broken by it. Full regression: 463 Python tests
passing (same 3 pre-existing unrelated failures as baseline), 277 Node tests
unaffected (this track touched only `services/report_service/assembler.py` and
`apps/api/executor.py`).

### RPT-3. Say how you would know it worked — **partly done**

Nothing in the tree does this. Every finding is a falsifiable prediction: fix this
and the persona's expectation holds next run. Emit a re-test line per finding — the
persona, the task, the expectation that should hold — and re-run it against the
fixed page. No human review can close that loop; it is the thing to be known for.

**What shipped.** `ReportAssembler._retest_prediction(finding, persona_names,
tasks)` states, per finding, exactly who it should be re-run against and what
should no longer happen: *"Falsifiable: on a re-run against the fixed page,
{persona(s)} attempting "{task}" should no longer produce "{title}". If it does,
the fix did not hold."* Wired onto every finding in `executor.py` right after F8's
step-ordering (`finding["retest"]`, set only when a persona can actually be
attributed -- the placeholder "No pain points detected"/"Journey ended early"
entries and anything with no personaId get none, honestly, rather than a
prediction naming nobody). Printed on both HTML surfaces: the slide deck (a
"How you would know it worked" panel beside grounding) and the flat
`_presentation` list.

**Not attempted, stated rather than silently dropped: "re-run it against the
fixed page."** The line names what a re-run would check; nothing here triggers
one. Actually closing the loop needs a live browser against a real, already-fixed
target and a mechanism to schedule and correlate that follow-up run against the
finding it verifies -- a new job type and a live target this sandbox cannot reach
from a report-generation call, in the same category as BE-4's noise floor. The
falsifiable prediction is the buildable, testable half of this section; the
automated re-run is not, here.

Three new tests: the prediction's shape (persona named, task named, title named,
several affected personas grouped rather than only the first one silently, no
prediction when nobody is attributable), an end-to-end `combined_test` run
reaching `critical_pain_points[].retest`, and both HTML surfaces printing it.
Full regression: 466 Python tests passing (same 3 pre-existing unrelated
failures as baseline), 277 Node tests unaffected (Python-only change).

### RPT-4. Report yield — what gets found — **partly done**

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

**What shipped.** D9: `_preserved_from_met_expectations()` -- the positive to
`_pain_points_from_expectations`' misses, sharing its `_promise_label` grouping
key and its rule for what counts as a promise (a control, not a scroll or a
read), grounded in a real met expectation's own text rather than generic praise.
"Stop filing our own run as the leading finding": confirmed already true --
`_is_run_diagnostic`/`run_diagnostics` already separates harness failures from
usability findings; nothing further was needed. A2: `_run_scorecard()` -- task
success, actions taken, and expectations met vs missed, drawn from the same
`matched` field the misses use so the two can never disagree about what a "miss"
is -- on the report as `scorecard` and printed on the intro slide (`"2 of 3 tasks
completed, 75% of expectations held"`). D7:
`_grouped_controls_with_differing_actions()` -- a simple flood-fill proximity
clustering over each snapshot's interactive elements (`_cluster_by_proximity`,
boxes within 16px read as one visual group), flagged when a cluster's roles
imply different kinds of action (a link beside what reads as a sibling button,
say). D4 (partial): `_small_touch_targets()` -- a deterministic sweep for WCAG
2.5.8's 24x24px minimum pointer target, over box geometry alone.

**A7/D6 ("promote a corroborated read gap"), found already substantially
shipped, the same shape RPT-2's B4 turned out to be.** `_unreadable_finding`
already promotes severity by corroboration -- `len(personas) > 1` reads as "Hard
to read for several personas" (medium, numbered among the problems) versus a
single ordinary-profile miss staying "low" and a single rare-profile miss
staying "info" and excluded entirely (`rare_only`). `_never_looked_at_finding`
does the same (`"high" if len(personas) > 1 else "medium"`). This is the rule
this section asks for -- one person is perception, more than one is the page --
already built before CAP-0's memory fix made it safe to build, and already
gated the same way (a corroborated finding is never published from a scan that
had no memory of what it had already shown a persona). Nothing new here.

**D4, the other four checks, and D8: not attempted, stated rather than
silently narrowed.** Heading order, alt text, form labels and focus visibility
all need a field this codebase has never seen on a snapshot element -- a tag or
heading-level, an `alt` attribute, a label association, a focus-visible style --
checked the same way RPT-5/C4 checked before declining to guess at a palette
field, and found absent from every fixture and every live payload shape
referenced anywhere in this tree. Guessing field names that may not exist would
either silently find nothing (indistinguishable from "the page is fine") or
crash on a real payload. D8 ("a wait that exceeds this person's tolerance") has
no real signal to build from either, once checked against what `behavior.js`
actually computes: `readMs` is a *simulated reading duration* (how long this
persona would take to read the text already on screen), not a measurement of
page response latency, and the "wait" coping decision's `durationMs` is set to
exactly `computeWaitTolerance()`'s own threshold by construction -- a persona
who chooses to wait never, by the code's own arithmetic, waits longer than they
would tolerate. There is no measured "the page took this long and this persona
would not have tolerated it" quantity anywhere in the timeline to report;
building one would need new instrumentation (a real page-response-latency
measurement), not wiring data that already exists.

Eight new tests: D9's grounding and cross-label consistency with the
broken-promise side (2), A2's scorecard math and its intro-slide line (2), D7's
clustering algorithm plus both the flagged and not-flagged cases (3), D4's
target-size sweep (1). Full regression: 474 Python tests passing (same 3
pre-existing unrelated failures as baseline), 277 Node tests unaffected (this
track touched only `services/report_service/assembler.py` and
`apps/api/executor.py`).

### RPT-5. Evidence and re-design in the product's own language — **done**

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

**What shipped.** E7: `_draw_evidence_marker()` (PIL) outlines a finding's element
box and numbers it directly on the crop; `_crop_element_data_uri()` gained a
`number` param; the deck prints the same number beside the finding's title
(`finding["evidenceNumber"]`), via one counter per report continued from
`_synthesize_pain_points`'s vision findings into `_attach_verdict_screenshots` so
two region crops never draw the same digit. C4: `_sample_palette()` reads real
colours from the screenshot's own pixels (the element's region, and the page
background sampled from the corner farthest from it) and grounds the redesign
prompt in them instead of a generic default. C3: the panel is now labelled
"Re-design — working code, not a mockup".

**Deviation, stated rather than silently narrowed.** The plan assumed "the
measured palette, type sizes and radii are all collected by the element walk
already." Checked against every fixture and test in this codebase: they are not.
journeytest-core's DOM snapshot (what `_read_snapshot_elements()` reads) carries
no colour, font-size, or radius field anywhere this codebase has ever seen —
only `fontPx`/`fontWeight` exist, and only on `perception.js`'s own candidate
walk (a different pipeline, used for the scan/eye-tracking simulation, never
threaded to a finding's `elements` list). Rather than assume an unverified
external schema, C4 reads the one place colour verifiably is: the screenshot's
own pixels, via PIL. Any `fontPx`/`color` an element happens to carry is still
used opportunistically in the prompt, never assumed present.

9 new tests. Full regression: 450 Python tests passing (same 3 pre-existing
unrelated failures as baseline) at the point this landed.

### RPT-6. The reader-facing lines — **done**

Seven changes at the render boundary, over data already computed. Grouped because
each is a line or two; kept separate from RPT-4 because none of them changes what the
system *finds* — only what a reader is told.

| Audit | Change | Status |
| --- | --- | --- |
| B7 | Print the severity derivation beside the chip: "medium — one person, a fifth of their patience, not blocking" | done, see below |
| F1 | Lead the summary with the judgement — what works, where it loses people, the one thing to change. Counts underneath | done |
| F2 | State scope as intent up front, including **what was not reviewed** | done |
| F8 | Order findings by the step at which they occurred, so they accumulate into a story; severity governs only the "fix first" slide | done |
| G4 | Print `evidence_language: observed` on the introduction slide — the strongest sentence we can write about ourselves, and it never reaches the reader | done |
| E11 | Run our own luminance check over the deck palette in the test suite. A contrast review that fails contrast would be embarrassing, and nothing checks it | done |
| A9 | Record model id and temperature per run, and say plainly that the persona's wording is not reproducible, only its disposition (rides with BE-3) | see BE-3 |

**What shipped, and one honest narrowing on B7.** F1: `_executive_summary` now
leads with `"The one thing to change: …"` and, when one exists, `"What works:
…"`, before any count. F2: the intro slide states `Scope: only the tasks
below, against {url}. Other pages, flows, and states of the product were not
exercised and are not represented in this review.` F8: `_order_by_step()`
sorts findings by the leading zero-padded step number in their own
`evidenceScreenshot`/`screenshotRef` filename — a real convention both this
codebase's own captures (`personaDirector.js`'s `keepSeenImage`/
`keepRefusedCapture`, `"003-as-they-saw-it.jpg"`) and journeytest-core's own
action captures (`"001-click-e21-after.png"`) already use, not a guess at an
undocumented format; a finding with no derivable step (most verdict-level
blockers, which are claims about the whole run rather than one screenshot)
sinks to the end via a stable sort rather than being given a fabricated
position. Severity now governs only `_impact_analysis`'s own "what to fix
first" ordering, untouched. G4: `evidence_language: {value}` is now printed
verbatim on the intro slide. E11: a new test reads the deck's own generated
CSS (not a hand-copied snapshot of it) and checks every severity chip, body
text, and the title slide against WCAG AA's 4.5:1 — all pass today, so this
is a regression guard, not a fix.

B7's shipped version is narrower than the audit's example. "Medium — one
person, a fifth of their patience, not blocking" implies a severity actually
*derived* from an affected count and a patience fraction by a real formula;
no such formula exists anywhere in this codebase today — severity mostly
comes from whichever source produced the finding (the vision worker's own
judgement, or the max of a synthesized group's members), not a computation
this code performs. `_severity_derivation()` reports the real numbers a
finding actually carries (affected-person count, a frustration delta when
`claimedImpact`/`behavioralImpact` is present, and blocking/not-blocking) and
degrades to whichever subset is real for that finding's source, rather than
inventing a "fifth of their patience" figure with no computation behind it.

Four new tests (plus two existing tests updated for the reordered summary
text and the new redesign caption). Full regression at this point: 454 Python
tests passing (same 3 pre-existing unrelated failures as baseline).


## Track B — the backend

### BE-1. Route runs through the settings store — **done**

As above. Everything else on this track depends on it, and so does CAP-1.

Planned in detail in `docs/next-cycle-be-1.md`, which found two things this
section's sketch did not. The work spans **four** processes, not two — the control
plane, `persona_service`, the journey worker and the eyeson worker — though both
Node workers already accept an injected endpoint, model and key, so only the wiring
above them reads the environment. And the admission decision **cannot be re-derived
at run time**: `may_use_built_in_providers()` needs an auth dict, a job carries only
`workspace_id` and `owner_user_id`, and in `hf_token` mode that id is an HF `sub`
while `space_owner()` yields a username — so a run would deny the Space's own owner
the credentials reserved for them. It is decided at job creation, where `auth`
exists, and recorded on the job.

### BE-2. Extract the report assembler — **done**

`apps/api/executor.py` was 3843 lines and held both halves. The report half now
lives in `services/report_service/` (underscore, matching `persona_service` and
`perception_service` — the hyphenated `report-service/` stays the empty placeholder
it was, as `persona-service/` is):

| | lines |
| --- | --- |
| `apps/api/executor.py` | 3843 → **637** |
| `services/report_service/assembler.py` | 2904 (`ReportAssembler`, 91 members) |
| `services/report_service/helpers.py` | 441 (module-level helpers) |

**Deviation from this plan, stated rather than buried.** The plan said the moved
`@classmethod`/`@staticmethod` members "become module-level functions, which is what
they already are in everything but spelling". They did not. They moved as a class,
`ReportAssembler`, which `JobExecutor` now inherits. The reason is that a
function-level extraction is not a move: 62 members reference each other through
`cls.`/`self.`, and two of them (`cls._vision_timeout()`, `cls._worker_error()`)
reference the run half, so every one of those call sites would have to be rewritten
and the two back-references redesigned. As a mixin, every reference resolves exactly
as before — through the MRO instead of within one class body — and the diff is
provably a move. De-classmethoding is a separate, later, also-mechanical commit.

**What is not verbatim.** 3543 of the original's 3560 non-blank lines moved
untouched. The 17 that changed: the class header gains its base; six places that
reached the class by name (`JobExecutor._flow_label`, `._NOT_A_PROBLEM`,
`._RARE_ACUITY`, `._RARE_CONTRAST`, `._what_stopped_them`) now name
`ReportAssembler`, which is where those attributes moved and which `JobExecutor`
inherits; and `_download_name` became a module function in `helpers.py` with
`_download_name = staticmethod(download_name)` left on the class — because a module
helper (`_evidence_reference_summary`) calls it and a module function cannot reach
back into the class without a circular import. That binding shape is the one
`_plural = staticmethod(plural)` already used a few lines away.

`apps.api.executor` re-exports the fourteen helper names that the run half still
calls or that other modules import by name, so no importer changed.

**Verification.** 393 passed / 3 failed before, 393 passed / 3 failed after, the same
three by name — all three need `dspy`, which `AGENTS.md` deliberately leaves
uninstalled. Not one assertion changed.

### BE-3. Cost and time accounting — **done**

Nothing records tokens or wall time. Two reasons to add it: the economic case is
never made in the artifact itself, and RPT-1 and RPT-3 both add model calls, so without
it we cannot say what the better report costs.

**What shipped, both funnels named in the detail spec.** Node: `completion()`
(`personaActor.js`) accepts an optional `role` and `usageLog` array; on a call
that actually answers, it pushes `{role, endpoint, model, temperature, wallMs,
promptTokens, completionTokens}` -- never on a retried attempt that failed, which
spent no tokens to account for. `llmActor()` owns one log per run
(`decide.usageLog`), fed by all three of its call sites (acting, reflection,
adherence, each under its own role), and `journeytest.js` attaches it to the run
result as `modelUsage`. Python: `DirectLLMSemanticEngine._complete()` records the
same shape onto `self.usage_log`; `compile_behavior`/`compile_abilities` pass
`role="persona.behavior"`/`"persona.abilities"`, and the report's own redesign
calls (`_generate_redesign_fragment`) pass `role="report.redesign"` and drain
into a `usage_sink` list `_attach_redesigns` threads through.

`ReportAssembler._model_usage_summary()` rolls both funnels into one summary --
total calls, wall time, prompt/completion tokens (kept as `None` rather than a
fabricated `0` when nothing in the chain ever returned a `usage` object), broken
down `byRole`, and every distinct `{endpoint, model}` that actually served a
call. It lands on the report as `model_usage` and is printed on the "How this
review was made" slide, per the "done when" clause.

**A9, which the RPT-6 table said would ride with this.** When `model_usage` is
non-empty, a limitations line states plainly that this run's model calls used
temperature > 0 and will not reproduce the same persona wording on a re-run --
only the compiled behavior/ability profile (the persona's disposition) is
reproducible, not its exact phrasing.

**Not accounted for, stated rather than silently narrowed.** Persona
generation's own model calls (`compile_behavior`/`compile_abilities`) are
recorded onto `self.usage_log` and tested directly, but nothing in this change
threads them into a specific report's `model_usage` -- persona compilation runs
as its own artifact-producing step, earlier and in a different job than
`combined_test`, and the persona artifact carries no usage field for a later
report to read back. `model_usage` on a report today covers exactly the model
calls `combined_test` itself makes: the run's own acting/reflection/adherence
calls (Node) and this report's own redesign generation (Python). Threading
persona-compile usage into a specific downstream report is a real gap, not
fixed here.

Seven new tests: four Python (one engine-level usage-log test, two
`_model_usage_summary`/report-level tests, one slide-deck rendering test) and
three Node (a real completion's usage record, a failed retry never billed,
reflection/adherence billed under their own role). Full regression: 458
Python tests passing (same 3 pre-existing unrelated failures as baseline),
277 Node tests passing.

### BE-4. The noise floor *(the worksheet's §0, and it gates judging any of this)*

Every number in the record is n=1 per commit, and `refused` has swung by a factor
of four between cycles that changed nothing relevant. Run the same commit three
times, record min/max of `refused`, `legibleShare` and completed runs, and write it
into `spec.md` as the noise floor.

*Done when:* a later cycle can be called better or worse than this one with a
reason. **No item in this plan can be called an improvement before this exists.**

**Not attempted, and why.** This needs `cycle-cohort.sh` and `measure.py`, which the
worksheet places in "the session scratchpad" — a prior session's temp directory, not
committed to this repository — plus a pinned `agent-browser` binary and network
access to a live target site and model provider. None of the environments this cycle
has been worked in so far had all three. Whoever picks this up first should either
locate or rebuild `measure.py` (its job, per the worksheet, is straightforward:
parse the run JSON for `refused`, `legibleShare`, and completed-run counts across
three same-commit cohorts and report the min/max) and commit it alongside the noise
floor it produces, so the next person is not solving this same problem again.

### BE-5. Concurrency and repeat runs — **partly done**

Personas run sequentially, so time grows linearly, and a three-person cohort is
about 20 minutes. Repeat runs at different seeds turn A8/G6 into a real claim — a
finding seen in 2 of 2 runs is a different claim from 1 of 2. Both land after BE-1,
because concurrency against a provider with no working fallback multiplies the
failure mode BE-1 exists to fix.

**What shipped: concurrency.** The sequential `for persona in personas:` loop
became `_dispatch_persona_run()` (the same per-persona logic, unchanged, only
parameterised) called through a `ThreadPoolExecutor`, sized off
`MAX_CONCURRENT_MODEL_CALLS` (the same knob `config.ini` already tuned
defensively for exactly this failure mode, so this follows BE-1's own budget
rather than picking a separate one) and bounded above by the cohort size.
Results are written into a pre-sized list by submission index and only
assigned to `journeys` once every future has completed, so the strict
positional correspondence `zip(journeys, personas)` relies on everywhere
downstream (`thoughts_by_persona`, the scorecard, `_impact_analysis`, vision
critique) holds exactly as before, regardless of which request actually
finishes first. Session-file cleanup (`finally: shutil.rmtree(...)`) still
waits for every future, not just the one that failed, because cancelling
in-flight requests would race deleting a session file others are mid-request
against. A rejected run (a 422, an unreachable worker) still fails the whole
job, matching the sequential loop's own behaviour as closely as true
concurrency -- which has already started every run by the time any of them
can fail -- allows: the first error wins rather than none of them being
started.

**What shipped: the reproduction count, without the repeat-seed dispatch.**
`_merge_similar_findings()` now computes `reproducedIn` -- the count of
distinct `runId`s in a merged cluster -- for every finding, not only ones
that were actually merged, so a cohort that never repeats a persona still
gets an honest `reproducedIn: 1` on everything rather than a field that only
sometimes appears. This is the mechanism BE-5's "reproducedIn count" asks
for, real and tested, but **inert until something actually dispatches a
repeated run**, which was not built.

**Not attempted: dispatching a persona at a second seed, stated rather than
narrowed silently.** The report-building pipeline this touches
(`thoughts_by_persona`, `mental_models_by_persona`, `persona_names`,
`_run_scorecard`, `_impact_analysis`, `_collect_vision_pain_points`) is built
throughout on a strict one-journey-per-persona invariant, keyed by
`persona_id` in several places (`thoughts_by_persona = {persona.get("id"):
... for journey, persona in zip(journeys, personas)}`). Dispatching the same
persona twice would make two journeys share one `persona_id`, and every one
of those dict-keyed structures would silently overwrite the first run's data
with the second's rather than erroring -- a correctness bug, not a missing
feature, and one this sandbox has no live run to catch by testing against
real output. The concrete next step for whoever picks this up: build an
expanded per-run persona list (each repeat carrying a synthetic id such as
`f"{persona_id}#{seed}"`), thread it everywhere `personas` currently is
zipped against `journeys`, and keep the original `personas` list only for
counts that should stay per-persona (`impact_analysis.personasTested`, the
scorecard's row-per-persona shape) rather than per-run.

Four new tests: concurrent dispatch proven by two requests actually
overlapping in wall time (not just both completing), journeys staying in
persona order regardless of completion order, a rejected run still failing
the whole job, and the pool never exceeding `MAX_CONCURRENT_MODEL_CALLS` in
flight at once -- plus one for `reproducedIn` (a finding seen in two runs
counted as 2, a same-run duplicate phrasing never double-counted as two
reproductions). Full regression: 478 Python tests passing (same 3
pre-existing unrelated failures as baseline; the four concurrency tests were
run three times each to check for flakiness and produced identical results
every time), 277 Node tests unaffected (this track touched only
`apps/api/executor.py` and `services/report_service/assembler.py`).

## Track C — hats, capabilities and `/webui`

Design rationale in `docs/next-cycle-worksheet.md`. A hat is what the agent can
**do** (`Tool`s in `Faculty`), what it **knows** (`PersonaMemoryBank`, the profile),
and what it **thinks with** (the `model_settings.py` roles — which exist, and which
BE-1 makes real).

### CAP-0. The ground layer — the scan accumulates — **partly done**

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

**What shipped.** The memory mechanism, in full: `scan()` (`scanpath.py:133`) takes
`already_seen` and deprioritises rather than excludes (`ALREADY_SEEN_DECAY = 0.35`);
`perceive()` computes `not_looked_at` against `candidates − (fixated ∪ already_seen)`,
exactly the line the detail spec named; `PerceiveRequest` carries `alreadySeen`
(`extra="ignore"`, so an old caller is unaffected); the worker's `PerceptionClient`
forwards it; `PersonaDirector` accumulates the union of fixated selectors into
`this.everSeen` across the run and sends it on every `perceive()` call. The report's
limitations section now states, in both directions, that a "never looked at" finding
draws on a scan with per-run memory as of this change, and that reports from before
it should be read with that caveat. Twenty tests across Python and Node, each
proving a specific claim: deprioritised-not-excluded, an untrustworthy capture's
fixations never joining the run's memory (state that outlives one retried attempt),
an absent `alreadySeen` behaving exactly as before, and the wiring at every hop.

**One deviation, found while accumulating the memory, not anticipated by the
detail spec.** `PersonaDirector.everSeen` must only accumulate from a call whose
capture the perception service itself trusts. The step is retried whole when
`perception.capture.trustworthy === false`, and `everSeen` is instance state that
outlives one attempt — folding in a discarded measurement's selectors would decay
elements this person has never actually seen, permanently, from data the run itself
threw away. Guarded and covered by its own test.

**What is not done, and why it is not a code gap.** The two "cheap siblings" —
billing-toggle oscillation and scroll-to-an-already-held-offset — are not built.
`faculty.js`'s `SCROLL` handler forwards `amount` to `browser.scroll({direction,
amount})` as what reads, in this repository, as a **relative** delta; the worksheet
describes `SCROLL:600` as **an absolute offset** the run keeps re-requesting. That is
a claim about `agent-browser`'s behaviour under the pinned driver
(`@baguette-studios/journeytest-core`), which is not installed in every environment
this cycle was worked in (no `node_modules`, no live browser) and could not be
verified from source in that environment. Building a no-op against a guessed API
risks shipping code that either does nothing or throws against the real driver.
Left for whoever can run a live `agent-browser` session to confirm the semantics
first.

**The second half of the done-when — "two of three runs reach a verdict other than
inconclusive" — is a live-run measurement**, and requires the same infrastructure
`BE-4` does (a live target site, real model credentials, several live cohorts) plus
`measure.py`, which is referenced by the worksheet as living in a prior session's
scratchpad and is not committed to this repository. It was not run. The mechanism
that should produce that outcome is built and tested at the unit and integration
level; confirming the outcome itself is `BE-4`'s job, on real infrastructure.

### CAP-1. `/webui` — the configuration surface — **done**

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

### CAP-2. The hat registry — additive only — **partly done**

**`browsingFaculty()` does not change, and is not renamed.** Browsing is what every
job so far needs and it works; it is the floor every hat stands on, not one option
among several. Its eight call sites stay untouched — including the module-level
`ACTION_TYPES`, `ACTION_VOCABULARY` and `ACTION_CONSTRAINTS` in `personaActor.js`
(`personaActor.js:32,52,53`), which are computed at import and are exactly the kind
of thing a rename makes drift quietly.

A hat records what it **adds**, and there is no field in which it could record a
removal:

```jsonc
{ "hat_id": "hat_...", "workspace_id": "...", "label": "The integrator",
  "adds": ["developer"],                                     // extra faculties only
  "roles": {"acting": "llm_abc", "reflection": "llm_def"},
  "grants": {"mcpServers": [...], "plugins": [...],
             "developer": {"allowCommands": [...], "hosts": [...]}},
  "profileDefaults": {...} }
```

A new `facultyWith(extras, {abilities, seed, memory})` **calls** `browsingFaculty()`
and appends. So a hat cannot take the browser away — not because a rule forbids it,
but because nothing can express it. A hat with no extras is byte-for-byte today's
faculty.

Order matters and falls out for free: `Faculty.processAction()` offers an action to
each tool until one claims it, so appending means `BrowserTool` keeps first claim on
`READ`, `CLICK`, `SCROLL`, `TYPE` and `GO_BACK`. A new faculty cannot shadow a
browsing action even by accident.

Because `Faculty.actionsDefinitionsPrompt()` (`faculty.js:254`) assembles the
vocabulary from whatever is mounted, an added faculty adds vocabulary without
touching the director.

The worksheet's **capability manifest** belongs here: a report should state which
hat produced a finding and what that hat could reach, because "I could not find the
retention policy" means different things from a browser alone and from a browser
plus a docs search.

**What shipped.** `facultyWith(extras, {abilities, seed, memory})`
(`services/journey-worker/node/src/faculty.js`) exactly as specified: calls
`browsingFaculty()` first and only ever appends, so "a hat with no extras is
byte-for-byte today's faculty" is provable by construction (the empty-extras case
literally calls `browsingFaculty()` and returns it unmodified) rather than merely
intended. A `registerFaculty(name, factory)`/`FACULTY_REGISTRY` pair is where a
future hat's tool factory would register itself -- empty today, since nothing
past browsing has been built yet (CAP-5 would be the first real registrant). An
extra named but not registered throws rather than silently producing a hat with
fewer capabilities than it claims. `PersonaDirector` takes an optional
`hatExtras` and calls `facultyWith(hatExtras, ...)` instead of `browsingFaculty()`
directly when given one, wired through from `journeytest.js`'s `input.hatExtras`,
so the registry is reachable from a real run today, not just callable in
isolation.

The persisted half: `apps/api/hats.py`'s `HatRegistry`, the same SQLite-adapter
shape `CredentialStore`/`ModelSettingsStore` already use -- `put`/`get`/
`list_hats`/`delete`, workspace-scoped, storing exactly the record shape this
section specified (`adds`/`roles`/`grants`/`profileDefaults`, no field anywhere
that could express a removal). `executor.py`'s `_combined_test` resolves a job's
`hatId` (when given one) into that hat's `adds` and sends it as `hatExtras` on
the `/v1/runs` payload -- a hat id that fails to resolve falls back to plain
browsing rather than failing the run, deliberately milder than an unregistered
*faculty name* at `facultyWith()`, which still refuses loudly on the worker side.

**Deliberately not attempted here: validating a hat's `adds` against the
worker's live `FACULTY_REGISTRY`.** They are two different processes in two
different languages; asking the worker to validate on every hat write would
make `hats.py` a second place a hat's real capabilities could drift from what
the worker actually has registered -- the exact failure this section exists to
prevent structurally. A hat can be created naming a faculty nothing implements
yet; the run that tries to use it is where that surfaces, loudly, via
`facultyWith()`'s own refusal, which is the one place drift cannot happen
because it is the only code path that builds a faculty at all.

**Not attempted: the capability manifest, and a UI for hat CRUD.** Both are real
gaps, stated rather than narrowed silently. The capability manifest ("which hat
produced a finding and what it could reach") has nothing to attach to yet --
every run today uses either plain browsing or plain browsing plus a hat whose
only registered extra is a test fixture, so a manifest field would say
"browsing" on every finding in every real report until CAP-5 gives it something
else to say. A Gradio panel for creating/listing/deleting hats (the natural next
piece of CAP-3's own front-tab work) was not built for the same reason: CRUD
against an empty capability list has limited value before there is a second
capability to add.

Fourteen new tests: four in `faculty.test.js` (no-extras equivalence, an
unregistered name refused, an extra appended never prepended, an appended tool
unable to shadow browsing even when it tries), two in `personaDirector.test.js`
(`hatExtras` reaching the faculty, and its absence leaving the faculty
unchanged), and eight Python (`test_hat_registry.py`: label required, `adds`
type-checked, an empty-adds hat matches the plain-browsing shape, a hat records
only what it adds, workspace scoping for listing and for get/delete, and two
executor-level tests proving a resolved `hatId` reaches the run payload as
`hatExtras` while no `hatId` sends no `hatExtras` field at all). Full
regression: 486 Python tests passing (same 3 pre-existing unrelated failures as
baseline), 283 Node tests passing (up from 277).

### CAP-3. Front-tab links — **partly done**

In the first Gradio tab, a row of buttons opening `/webui` deep links: **Developer
Mode** (`/webui#developer`), one per preset hat (`/webui#hat=<id>`), and **Model &
capabilities**. Each is a real URL, so it still works pasted to a colleague. Hidden
when `AUX_WEBUI_ENABLED` is unset, rather than linking to a 404.

**What shipped.** Two of the three links, at the top of the Analysis Orchestrator
tab: **Model & capabilities** (`gr.Button(link="/webui")`) and **Developer Mode**
(`gr.Button(link="/webui#developer")`), both real anchors via Gradio's `link=`
(so they work pasted outside the app, per the spec), in a `gr.Row(visible=…)` gated
on `apps.webui.is_enabled()` — the same check CAP-1's router registration uses, so
the button and the surface it points at agree by construction rather than by two
copies of the same env-var read staying in sync. Hidden, not disabled: the row's
`visible` is `False` when the flag is unset, checked directly on the Blocks graph
rather than only on the rendered HTML.

**Not built: one button per preset hat.** There is no hat registry yet — CAP-2 does
not exist — so there is nothing to enumerate and nothing to link to. Building a
placeholder list now would be UI for data that has no source.

**A defensible gap on the "Developer Mode" link, stated rather than hidden.**
`/webui#developer` is a real, 200-returning URL, satisfying the letter of "not a
404" — but the `/webui` page does not yet read `location.hash` to show anything
different from the plain settings view, because developer mode (Hat 3, CAP-5) is
not built either. Clicking it today opens the same page "Model & capabilities"
does. Kept rather than dropped, because the plan names it and the destination is
honest about what it currently is (the configuration surface, which developer mode
will eventually be a section of) rather than a dead link — but whoever builds CAP-5
should wire `app.js` to the fragment at the same time, or drop this link if that
turns out to be the wrong shape once hats exist.

### CAP-4. Hat 2 — redaction *(parallel with CAP-0; gates any real signed-in run)* — **done**

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

**What shipped.** All three redaction surfaces the detail spec named, plus both
"cheap" items.

1. **Pixels.** `ReportAssembler._redact_boxes_in_image()` (assembler.py, PIL
   `ImageDraw`) blanks the boxes of any element on a per-run selector list before
   the bytes are stored, cropped, or sent anywhere — applied once, at
   population time, in `_collect_vision_pain_points` (before `screenshot_bytes`
   is populated, so `_synthesize_pain_points`'s later crop sees the same
   already-redacted bytes) and in `_attach_verdict_screenshots` (which gained
   its own DOM-snapshot pairing via `_elements_for_screenshot` — it never had
   one before this).
2. **The element tree.** `ReportAssembler._redact_element_fields()` blanks
   `name`/`text`/`value`/`inputValue` for a listed selector before an element
   list built from `_read_snapshot_elements()` reaches the outbound
   vision-critique payload — the Python-side counterpart of the worker's
   `redactSensitive`/`markSelectorsSensitive` pair, which now also redacts an
   element's accessible `name` (previously value-only) and gained
   `markSelectorsSensitive(elements, selectors)` for a selector list with no
   native "this is sensitive" signal of its own (an account menu, an invoice
   row). `PersonaDirector.lookOnce()` applies both to `seen.elements`
   immediately after the walk, before anything downstream — `perceive()`'s
   request body included — can see the unredacted tree.
3. **The vision-critique request body.** Built from evidence already redacted
   by (1) and (2) at the point of capture, never redacted on its way out —
   the single redaction point the spec asked for.

**The one designed deviation.** The spec's own wording ("blank the boxes of
elements the walk marks sensitive") assumes a live `sensitive`/`inputType`
signal already reaches a walked element. It does not: `redactSensitive()` had
exactly one caller before this (`evidence.js`, a persona's own recorded action)
and nothing in this codebase ever set `sensitive` or `inputType` on a walked
DOM element. The selector list (`redactSelectors`, resolved by the control
plane from a signed-in run's credential and threaded through `/v1/runs` →
`PersonaDirector` → `markSelectorsSensitive`) is the mechanism actually built
and tested; the latent value-based path stays in place as the other half of
the same function, unused until something starts marking elements sensitive on
its own.

**The two cheap ones, both true, one newly guaranteed rather than assumed.**
"Prefer stored state to replaying a password" was already true by construction
— `_prepare_run_session` (executor.py) calls only `write_state_file()`;
`capture_session()` has exactly one caller anywhere in this codebase,
`credentials_panel.py`'s explicit "sign in" button, never a run's own path —
and is now pinned with a test that fails loudly (`capture_session` raises) if
that ever stops being true rather than staying true by omission. Mid-run
expiry detection is new: `PersonaDirector` takes `authenticatedSession`
(resolved from whether the run was given a state file, in `journeytest.js`,
before the director is constructed so the check has it from the first step);
each step, a `"Sign in"`/`"Log in"` prompt appearing in the walked elements
where none was expected ends the run immediately, before the persona is asked
to act on what is now the logged-out page. This is deliberately *not* wired
through the existing `ending: "abandoned"` path, which produces a
`persona-stopped` blocker — a claim about the product. A new ending,
`"diagnostic"`, was added to `verdict()`: `status: "inconclusive"`, both
criteria `"not-observed"`, `blockers: []`, so a session that drops out mid-run
never reads as a usability failure of the page. The report side gained a
matching `_INSTRUMENT_FAILURES` entry (`journey.session_expired`,
`report_service/helpers.py`) so it surfaces as a `run_diagnostic` — same class
as `persona.perception_unavailable` — rather than silently vanishing.

**What this heuristic is, and is not.** The sign-in-prompt check is a
reasonable signal built from what this codebase can observe (the walked
accessibility tree), not a verified live-infrastructure result — no live
browser or real login flow was exercised in this sandbox. A site that shows a
"Sign in" link to an already-authenticated user for an unrelated reason (a
second account switcher, say) would false-positive; that tradeoff — ending the
run on a false signal rather than silently reviewing a possibly-logged-out
page — is judged the safer one and is what the detail spec's own priority
("the worst failure available, because it is invisible in the output") asks
for, but it has not been checked against a real site.

**Tests.** Fourteen new across the whole track, covering every rail the detail
spec named. Seven in Python (`tests/contract/test_control_plane.py`,
`test_browser_credentials.py`): pixel redaction blanks only the given region
and passes bytes through unchanged with no boxes; box-to-selector matching
requires both a listed selector and a box; element-field redaction blanks the
four fields for a listed selector only; a verdict-sourced screenshot is
blanked before cropping when its region is listed, and untouched when it is
not; a full round-trip through `_collect_vision_pain_points` proves an
account name never reaches the outbound request body and the pixels the
model receives are already blanked; a stored-state run is proven to never
call `capture_session()`; a session that stops reading as signed in ends the
run as a diagnostic with no blocker and no findings, is recorded, and reaches
the report as a `run_diagnostic`. Seven in Node (`safety.test.js`,
`personaDirector.test.js`): a sensitive element's accessible name is redacted
alongside its value; a selector on this run's redact list is marked sensitive
and one off the list is not; no list and no marker is a no-op; an
account-menu selector named as sensitive never leaves the process, in both
the outbound `perceive()` payload and the director's own `result.elements`;
an unmarked element is unaffected with no list; a session that stops reading
as signed in ends the run as a diagnostic; the same page with no
authenticated session is read as ordinary, not an expiry. Full regression:
445 Python tests passing (the same 3 pre-existing, unrelated failures as the
established baseline), 274 Node tests passing (up from 272 before this
track).

### CAP-5. Hat 3 — developer mode — **done**

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

**What shipped, every rail from the table.** `services/journey-worker/node/src/
developerTool.js`'s `DeveloperTool extends Tool`, registered with CAP-2's own
registry (`registerFaculty("developer", factory)`) rather than hardcoded into
`faculty.js` — the two stay decoupled, and any future hat's tool registers the
same way. **Off unless the run asks**: the factory returns no tool at all when
`grants.developer.allowCommands` is empty (`facultyWith` was extended to accept
a falsy factory return as "do not mount", a small, direct consequence of this
rail), so a hat without commands never mounts `DeveloperTool` — proven by a test
asserting `RUN`/`FETCH` are *absent* from `actionTypes`, not merely refused.
**Allowlist, constructed argv**: `_run` calls `execFile(command, args)` with an
array, the same shape `agentBrowser.js`'s `runOnce` already uses — no shell, so
no pipes, substitution or `&&`. **Scratch directory per run**: built beside the
run's own artifact directory in `journeytest.js`
(`${outputDir}/developer-scratch/${runId}`, the same "run-scoped, destroyed with
the run" shape `_run_session_dir()` uses on the Python side), removed in the
run's own `finally` block regardless of whether anything used it; every FETCH/
INSPECT/RUN path is resolved and checked against it before use, refusing `../`
escapes. **Environment built empty**: `execFile(..., { env: {} })`, never
`...process.env` — verified with a real child process, not a mock: the test sets
a secret in the *test's own* environment and asserts it does not reach a real
subprocess's stdout. **Egress to declared hosts only**: every FETCH/AUTHENTICATE
target goes through `privateHost()` first (blocking `127.0.0.1`, link-local,
and the RFC1918 ranges) and then, when the run declared specific hosts, through
that allowlist too — both proven against a real refusal, not a mock, plus one
proving a *non-private* host outside the declared list is refused on its own
account. **Output is untrusted input**: RUN's stdout/stderr pass through
`sanitizeUntrustedText()` before reaching the timeline. **Every invocation is
evidence**: `processAction` records action type, target, duration and outcome
into the timeline as a `developer.invocation` event on every path, success or
failure, via one `record()` closure so no branch can forget to call it.

Wired end to end, not only callable in isolation: `PersonaDirector` accepts
`grants`/`scratchDir` and passes them through `facultyWith`; `journeytest.js`
builds the scratch directory and reads `input.grants`; `executor.py` resolves a
job's hat into `hatExtras` *and* `grants` (CAP-2 only threaded `adds`; this
extends the same resolution to also read `grants`) and sends both on the
`/v1/runs` payload.

Ten new tests in `developerTool.test.js`, one per rail from the detail spec's
own list plus two beyond it: a command off the allowlist refused, a path
outside the scratch directory refused, the child environment holding no parent
key (against a real subprocess), a private address refused for both FETCH and
AUTHENTICATE, a host outside the declared list refused independent of
privateHost, a hat with no `allowCommands` mounting no RUN/FETCH action at all
(not refused — absent), a hat that does grant them mounting the tool appended
after browsing, every invocation recorded as evidence, and a full FETCH-then-
INSPECT round trip against a real local HTTP fixture server proving the
"done when" clause directly: download what a page offers, verify by checksum
that it is what was claimed. Plus one Python test proving a hat's `grants`
(not only its `adds`) reach the run payload. `npm run check` now also checks
`developerTool.js`. Full regression: 487 Python tests passing (same 3
pre-existing unrelated failures as baseline), 292 Node tests passing (up from
283).

### CAP-6. Hat 4 — role hats, and the gate that rejects most of them — **done**

Evaluator, administrator, integrator, compliance reader — with one rule: **a hat
earns its place only if it changes what the system does, not what it says.** Same
actions in a different tone is a prompt and belongs in a persona profile. Applied
honestly this rejects some of the four, which is why it is written down before they
are built rather than after.

**The gate, applied to each of the four, honestly.**

- **Integrator — passes, and needs no new code.** Wants Hat 3's (CAP-5's
  developer) tools: FETCH to pull a page's declared assets, RUN to invoke an
  allowlisted verification command, AUTHENTICATE to exercise an issued key
  against the product's own API. That is a real change in what the system can
  *do* -- CAP-5's own `DeveloperTool` is exactly this. And it needs zero new
  production code, because CAP-2's registry already expresses it completely:
  `HatRegistry.put(label="The integrator", adds=["developer"], grants=
  {"developer": {"allowCommands": [...], "hosts": [...]}})` is the whole hat.
  This is, in fact, the literal worked example this section's own CAP-2 JSON
  sketch used before either CAP-2 or CAP-5 was built. Proven end to end by
  `test_cap5_a_hats_grants_reach_the_run_payload_for_a_mounted_tool_to_read`
  (Python: a hat record's `grants` reach the run) and
  `developerTool.test.js`'s "a hat that does grant allowCommands mounts the
  tool" (Node: that grant actually mounts `DeveloperTool`) -- the integrator
  hat is those two tests composed, not a third thing to build.
- **Administrator — fails the gate as stated.** "Wants Hat 2's tools and none
  of Hat 3's" reads as though it should be built the same way as the
  integrator, but Hat 2 (CAP-4's redaction) is not a `Tool` the registry
  mounts at all -- it is unconditional behaviour `PersonaDirector.lookOnce()`
  already applies to every signed-in run, driven by a credential's own
  `redactSelectors`, not by a hat. There is no capability for an
  "administrator" hat record to `adds`: a hat naming no extras is, by CAP-2's
  own construction, byte-for-byte the plain browsing floor -- identical to no
  hat at all. Nothing here changes what the system *does* beyond what already
  happens unconditionally, so this fails the gate outright rather than
  earning a place, and is not built.
- **Evaluator and compliance reader — fail the gate, are personas.** Neither
  names a capability outside browsing; both describe a stance (judgemental,
  compliance-focused) applied to the same actions every persona already
  takes. That is a prompt -- a persona profile's goals, traits and
  `minibio`, compiled by `services/persona_service` -- and belongs there, not
  in the hat registry. Not built here, because CAP-6's job is the gate, not a
  persona for every plausible stance; if either is ever wanted, it is a
  `persona_service` change, a different track entirely.

**Done when**, restated honestly: the gate has been applied to all four
candidates and the verdict written down before any of them were built, per
this section's own reason for existing ("that is why the gate is written down
before they are built"). One of four passes, needs nothing new, and is proven
by tests CAP-2/CAP-5 already wrote for an unrelated reason; three are
rejected, on stated grounds, rather than built and found wanting afterward.

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

## CAP-1, as built

`apps/webui/` — a router and three static files, no build step. Registered on
`fastapi_app` before the Gradio catch-all, which a test asserts on the source,
because getting that order wrong 404s the page in the deployed Space while every
other test still passes.

The three rules hold by construction rather than by discipline, which is what the
tests check:

- **Off unless asked for.** Without `AUX_WEBUI_ENABLED=1` the routes are never
  registered — absent, not forbidden. The test asserts `app.routes` contains no
  `/webui` path at all, not merely that a request 403s.
- **No route returns a key.** The settings route returns `store.list()`, whose
  SELECT does not name the `secret` column. Endpoints are cut to scheme and host,
  and the test saves a provider whose base URL carries `?token=sk-…` to prove the
  path goes too. A pasted key is sent once on save and cleared from the form.
- **The passthrough is bounded.** One completion, capped prompt and reply, no
  stream, no history, and rate-limited per workspace. The tests assert the second
  check in a row is refused and that exactly one message is sent.

Two things the page does not do, and should not: it never accepts a key in order
to *read* one back, and it takes a Space secret by the **name** of the variable,
so the recommended path never has a secret cross the wire at all.

Model discovery asks the endpoint server-side, by `provider_id` — the browser
names a row, never a credential.
