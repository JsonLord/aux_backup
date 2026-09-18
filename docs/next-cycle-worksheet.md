# Next development cycle — worksheet

Written after cycle 51. Every number here is measured, not estimated; the
measuring script is `measure.py` in the session scratchpad and reads parsed JSON
rather than grepping it, for reasons recorded in spec.md §55.6h.

## Where the last eight cycles left it

| cycle | captures | refused | read nothing | legible | price in report | verdicts |
|-------|---------:|--------:|-------------:|--------:|----------------:|----------|
| 44 | 28 | 23 | 0 | 0.97 | 171 | 1 failed, 2 inconclusive |
| 45 | 17 | 36 | 0 | 0.89 | 91 | 1 failed, 2 inconclusive |
| 46 | 45 | 0 | **25** | **0.29** | 98 | 1 failed, 1 passed, 1 inconclusive |
| 47 | 38 | 8 | 0 | 0.85 | 34 | 1 failed, 2 inconclusive |
| 49 | 19 | 24 | 0 | 0.76 | 68 | 1 failed, 2 inconclusive |
| 50 | 28 | 34 | 0 | 0.79 | 361 | 3 inconclusive |
| 51 | 26 | **13** | 0 | 0.79 | **545** | **1 passed**, 1 inconclusive, 1 failed |

What is settled: the price is read and quoted in every cycle since 44; no report
denies a price it read; no capture passes while measuring nothing; the screenshot
reaches the whole page and carried all 26 of cycle 51's captures on its own.

What is not: no cycle has had all three runs complete, and refusals still swing
by a factor of four between cycles that changed nothing relevant. **Read any
single-cycle movement in `refused` as noise unless it survives three runs at the
same commit.**

## The one measurement this cycle needs first

Nothing below can be judged without it. Every number above is n=1 per commit, and
this record contains two occasions where a one-cycle movement was read as signal
and was not.

- [ ] **Run the same commit three times and record the spread.** Cheapest possible
      version: `for n in 52 53 54; do bash cycle-cohort.sh $n; done`, then
      `measure.py cycle52 cycle53 cycle54`. Write the min/max of `refused`,
      `legibleShare` and completed runs into spec.md as the noise floor.
      *Done when:* a later cycle can be called better or worse than this one
      with a reason.

## 1. Journeys that finish — the binding constraint

Three findings per report, one or two of them about our own run rather than the
site. The report is dominated by not-finishing because the runs do not finish.
Everything in section 2 is starved until this moves.

**This section's questions were open when the worksheet was written and are
answered below. Read "Context from the runs" before picking anything up.**

- [x] ~~Find out why a run ends inconclusive.~~ Answered: the step budget, not
      the persona. See *Why runs end inconclusive*.
- [x] ~~Check whether 16 actions is enough.~~ Answered: 16 is `2 tasks x 8`, and
      11 of 12 inconclusive runs ended on exactly 16. The verdict is an artifact
      of the budget.
- [ ] **Give the scan a memory.** This is the root cause and the one thing to do
      first. See *The treadmill* — a persona cannot accumulate knowledge of a
      page, so a READ can never make progress and the budget always runs out.
      *Done when:* `notLookedAt` falls across a run instead of holding at 13-14,
      and two of three runs reach a verdict other than inconclusive.
- [ ] **Stop the billing toggle oscillation.** `e17` (Annual) and `e18` (Monthly)
      are clicked back and forth up to six times in one run. Either the click
      produces no change the persona can perceive, or the change is not carried
      into the next step's view.
- [ ] **Stop scrolling to an offset the page is already at.** `SCROLL:600` nine
      times in one 16-step run. An absolute scroll to the current position is a
      no-op that costs a step and reads as the page not responding.
- [ ] **The 13 remaining refusals.** Every one is "N of N regions" -- a total
      mismatch, not a partial one -- and 5 of 13 are the look *after* acting.

## 2. Report yield

Currently 1–4 findings about the site, against 15–40 in the reference review.
The evidence chain per finding is already strong — provenance, measured impact,
element box, cropped region, root cause, proposed redesign markup — so this is
about breadth, not depth.

- [ ] **Say what worked.** `elements_to_preserve` is empty in 6 of 7 reports. The
      perception data already knows what was legible, prominent and found
      quickly; nothing reads it that way. A review that only lists faults is half
      a review.
- [ ] **Stop filing our own run as the leading finding.** "Users could not finish
      the tasks" leads at high severity and its recommendation is advice about
      reading our report. It belongs in `run_diagnostics`, which already exists.
- [ ] **Add a deterministic sweep** so coverage does not depend on a persona
      stumbling: contrast, tap-target size, heading order, alt text, form labels.
      These are measurable on every capture already taken.
- [ ] **A scorecard**: task success, actions taken, where each run stopped. The
      numbers exist in the timeline and are never totalled.
      *Done when:* a report carries ten or more findings about the site, at least
      two of them positive.

## 3. Carried over

- [ ] **#22 pointer travel is live but half-aimed.** 7 of 11 hands had a box in
      cycle 51; the rest recorded `measured: false`. Find where the walk had no
      box for a ref the actor targeted.
- [ ] **#39 vision critique.** Five claim types are now checked against
      measurements. The untested direction is a claim about something the run
      never looked at — the guard should not silently pass those.
- [ ] **Tiled full-page captures.** `--full` returns the current viewport tiled to
      the document height. Unused by perception now, but the evidence screenshots
      the vision critique reads still come from it.

## Ground rules this record has paid for

1. **Look at the artifact.** Five cycles of hypotheses ended in one crop of an
   image that had been on disk the whole time. The run keeps its refused
   captures now; open one before theorising.
2. **A measurement of the record is a measurement.** Two metrics here were wrong
   in the same way the code was — a grep over raw JSON that missed `£`, and
   a pattern that counted persona plans as report claims.
3. **Constrain, do not delete.** Two guards this cycle failed by producing less:
   captures that passed by measuring nothing, and task generation that shipped
   ten placeholders because a label did not match exactly.
4. **A guard that cannot run is not a guard that passed.** Say so out loud in the
   record whenever a check is skipped.


---

# Context from the runs

Everything here is read out of cycles 47, 49, 50 and 51 — the four cycles run
after the capture became reliable. No estimates.

## Why runs end inconclusive

`stepBudget()` in `journeytest.js` is `min(40, max(12, tasks * 8))`. The standard
journey has two tasks, so **the budget is 16**, and every inconclusive run in
every cycle ended on exactly 16 actions. "Still going after 16 actions" is the
run hitting its ceiling, not a persona giving up.

The comment above that function argues eight actions per task "is more than a
real visitor spends before they have either done the thing or given up", citing a
live agent run that finished in three clicks. Eleven of twelve runs contradict it.

Frustration is *not* what stops most runs. Two of cycle 50's three runs ended at
0.40 and 0.44 frustration, well inside tolerance, and still hit 16.

| cycle | verdict | actions | ended at | duration |
|---|---|---:|---|---:|
| 51 | **passed** | 6 | frustration 0.11 | 251s |
| 51 | failed | 12 | gave up, frustration 0.70 | 275s |
| 51 | inconclusive | 16 | budget | 359s |
| 50 | inconclusive | 16 | budget, frustration 0.40 | 445s |
| 50 | inconclusive | 16 | budget, frustration 0.44 | 460s |
| 49 | failed | 3 | gave up early | 213s |

A run costs 213-516 seconds. A three-person cohort is about 20 minutes, not the
45-70 the older figures in spec.md suggest.

## The treadmill — why a READ can never make progress

The scan fixates a fixed budget of **6 elements per look**, and it has no memory
between looks. Measured on cycle 51's inconclusive run, 26 captures:

- `fixated` is **6 on every single capture**, whether the page offered 15, 20, 29
  or 30 elements.
- Consecutive captures fixate the **identical six**. `e10` was one of the six in
  **23 of 26** captures.
- Across the whole run, **19 of 43** elements were ever looked at. Twenty-four
  legible, on-screen elements were never seen by anyone, and could not have been.
- `notLookedAt` therefore never falls: 14, 13, 13, 13, 14, 14, 14, 14, 14, 14…

So when a persona says *"read the 16 other things on the page I have not looked
at"* — which cycle 51's failed run said eight times in a row — the next look
returns the same six things and the count stays at 16. It is a treadmill, and it
is structural rather than a modelling choice about attention: a real visitor
remembers what they have already read.

**This also inflates a finding the report publishes.** "On screen and never
looked at: 'Pricing'" is measured, but part of what it measures is our own scan
having no memory, not only the page's prominence. Treat those findings as
suspect until the scan accumulates.

## The loops, by name

`e6` = the "Pricing" nav link. `e17` = "Annual · save 17%". `e18` = "Monthly".

One 16-action run, verbatim:

```
CLICK:e6 → SCROLL:700 → CLICK:e17 → SCROLL:500 → CLICK:e18 → SCROLL:500
→ SCROLL:500 → CLICK:e18 → SCROLL:500 → CLICK:e17 → SCROLL:500 → SCROLL:700
→ CLICK:e17 → GIVE_UP → SCROLL:700 → CLICK:e17
```

Three distinct loops, each costing steps from the 16:

1. **Billing toggle oscillation** — `e17`/`e18` clicked back and forth, up to six
   times in one run. The persona is trying to see the price change and either it
   does not, or the change does not reach the next step's view.
2. **Scroll to a position already held** — `SCROLL:600` nine times in one run.
   These are absolute offsets; scrolling to where you already are does nothing and
   looks like a dead page.
3. **The READ treadmill** above.

Also visible in that trace: a `GIVE_UP` at action 14 followed by two more
actions. A run that decided to leave kept going.

## What a passing run looks like

Cycle 51's passed run, in full — six actions, no loop:

```
CLICK:e6 → READ:the rest of the pricing page → CLICK:e17
→ READ:the 13 other things → READ:the 13 other things → DONE
```

Verdict: *"Completed what they came to do. The company is offering a paid
subscription for teams. After a 3-day free trial, it costs…"* It reached the
answer before the treadmill could catch it.

## The failed run produced a real finding

Cycle 51's give-up is worth reading as a UX result rather than a run failure:

> "The page lists the costs clearly, but it does not plainly state what the
> company is offering or who it is for."

That is a genuine value-proposition finding, arrived at by a persona who read the
price successfully. It is the kind of observation the report exists to produce,
and it currently reaches the reader as a run that failed.

## Capture and pointer, as they now stand

- **Refusals: 13** in cycle 51, down from 34. Every one is "N of N regions" — a
  total mismatch, never partial. Five of thirteen are the look after acting,
  which points at the page changing under a click rather than at the capture.
- **Sources:** all 26 captures came from the page screenshot. The viewport frame
  was not needed once it stopped being asked first.
- **Pointer:** 11 events, 7 with a measured box, **4 with none — all of them
  `e17` or `e18`**, the same toggle the runs oscillate on. The walk loses those
  refs on some steps, which is probably the same defect as the oscillation.
- **Misses: 0 of 7.** The hand-scatter model has never once put a click outside
  its control on this site. Either the scatter is too small to matter at these
  control sizes, or it is not doing anything.

## Numbers worth keeping as a baseline

| measure | cycle 47 | 49 | 50 | 51 |
|---|---:|---:|---:|---:|
| captures | 38 | 19 | 28 | 26 |
| refused | 8 | 24 | 34 | 13 |
| legible share | 0.85 | 0.76 | 0.79 | 0.79 |
| captures reading nothing | 0 | 0 | 0 | 0 |
| price quoted in report | 34 | 68 | 361 | 545 |
| report denies a price | 0 | 0 | 0 | 0 |
| findings about the site | 4 | 1 | 1 | 1 |
| positives | 0 | 0 | 0 | 0 |

Remember the first item on this worksheet: these are one run per commit, and
`refused` has swung by a factor of four with nothing relevant changed. The stable
claims are the zeros — no capture reads nothing, no report denies a price it
read.

---

# Project vision: hats

The system today has one hat. A persona browses, looks, and reports on what a
visitor can see and do. Everything real it can reach is behind
`BrowserTool` — and that is the whole shape of the product's ceiling: it can
only review what a logged-out stranger can reach from the front page.

A hat is a bundle of three things the codebase already keeps separately:

| part | where it lives now | what a hat adds |
|---|---|---|
| what it can *do* | `Tool` in `faculty.js`, declaring `actionTypes` and `realWorldSideEffects` | new tools |
| what it *knows* | `PersonaMemoryBank`, the profile | role knowledge, standing context |
| what it *thinks with* | `model_settings.py` roles (generation / acting / reflection / vision) | a role's own model choice |

So a hat is not a new subsystem. It is a set of tools, a memory, and a model
assignment, and the seams for all three exist. `Faculty.actionsDefinitionsPrompt()`
already builds the persona's action vocabulary from whatever tools are mounted,
so a hat that adds a tool adds vocabulary without touching the director.

## Sequencing, and why the ground layer comes first

**None of this ships before the scan has a memory.** A persona that re-reads the
same six things for sixteen steps will do exactly that with a terminal and a
login as well — it will just burn a larger budget on a bigger surface, and the
failures will be harder to read. The order is not negotiable:

1. The scan accumulates (§1). Runs finish.
2. Credentials and the logged-in journey (hat 2) — the smallest real extension,
   and the one with machinery mostly built.
3. Developer mode (hat 3).
4. Role hats (hat 4+).

Each stage is testable while the next is being written; that is the point of
building them as tools rather than as modes.

---

## Hat 1 — The visitor (shipped)

What exists. Browses, perceives through a modelled eye, states an expectation
before acting, reflects against what it can actually see, gives up when a real
person would. Everything below inherits this: a hat that acts without stating
an expectation first produces activity, not a review.

## Hat 2 — The signed-in visitor

**The point:** most of a product is behind a login. A review that stops at the
marketing page is reviewing the brochure.

Already built: `CredentialStore` with encryption at rest and per-workspace,
per-owner scoping; `issue_identity(persona_id, origin, domain)`;
`loginCapture.js`; `sessionStatePath` plumbed through `runWithJourneyTest`; a
credentials panel in the UI; `_prepare_run_session` handing a session file to a
run.

Still to build:

- [ ] **Prefer stored session state to replaying a password.** A captured
      storage-state (cookies, localStorage) signs a run in without the run ever
      holding a secret. Password replay is the fallback for sites that expire
      state, not the default path.
- [ ] **Re-authentication mid-run.** Sessions expire; a run that silently becomes
      logged-out reviews the logged-out product and says nothing about it. Detect
      it and say so in the record, the same way a refused capture says so.
- [ ] **Redact what a signed-in page shows.** This is the load-bearing one. Every
      screenshot, crop, snapshot and `beneath` probe in a logged-in run may carry
      an account name, an email, an invoice. `safety.js` has `redactSensitive`
      for values; evidence needs the same treatment for pixels and for the
      accessibility tree before anything is written to an artifact.
- [ ] **Test accounts only, and say so.** A stored credential is scoped to an
      origin and a workspace. The UI should make it plain that these are
      throwaway accounts on systems the operator controls, and refuse to treat a
      personal account as a test fixture.

*Done when:* a run signs in, reviews a journey behind the login, and its report
carries no account identifier anywhere in text or evidence.

## Hat 3 — Developer mode

**The point:** a large class of product failure is not visible in a browser at
all. "The download is broken", "the install instructions do not work", "the API
key from the dashboard is rejected", "the SDK snippet on the docs page does not
run". A reviewer who can open a terminal can check the promises a page makes.

The tool is `DeveloperTool`, mounted alongside `BrowserTool` in the same
`Faculty`, declaring `realWorldSideEffects = true`.

Proposed actions, deliberately few:

| action | for |
|---|---|
| `FETCH` | download what the page offers, and report what actually arrived |
| `INSPECT` | checksum, size, archive listing, file type — no execution |
| `RUN` | one allowlisted command in a scratch directory |
| `AUTHENTICATE` | exercise a key or token the product issued, against its own API |

**The safety design is the feature, not a wrapper around it.** These are the
parts that must exist before the first `RUN`:

- [ ] **Off unless asked for, per run.** The same shape as
      `browserSafety.allowIrreversibleActions`: a run declares
      `developer.allowCommands` or the tool is not mounted at all. A capability
      that is mounted and then guarded is one bug away from ungated.
- [ ] **An allowlist of commands, not a shell.** No pipes, no substitution, no
      `&&`. The argument vector is constructed, never interpolated — the same
      rule `agentBrowser.js` already follows, and for the same reason: some of
      the arguments are secrets.
- [ ] **A scratch directory per run, destroyed with it.** Nothing outside it is
      readable or writable. No access to the repo, the artifact store, or the
      credential database.
- [ ] **No secrets in the environment handed to it.** The environment is
      constructed empty and filled deliberately; it never inherits the worker's,
      which holds every provider key the deployment has.
- [ ] **Egress to declared hosts only,** and `privateHost()` in `safety.js`
      already knows which ranges are never legitimate targets.
- [ ] **Output is untrusted input.** Anything a command prints goes through
      `sanitizeUntrustedText` before it reaches a prompt. A downloaded README
      that says "ignore your instructions" is a file, not an instruction, and the
      project already treats page text that way.
- [ ] **Every invocation is evidence.** Command, arguments, exit status, duration
      and output land in the timeline like a click does, so a finding that says
      "the install fails" can be checked rather than believed.

*Done when:* a run downloads the thing a page offers, verifies it is what the
page claimed, and files a finding when it is not — with the transcript attached.

## Hat 4 — Role hats

**The point:** "can a visitor use this" is one question. An organisation has
others, and they are asked by people with different knowledge, different
tolerances, and different definitions of a blocker.

A role hat is a persona plus standing knowledge plus a tool set. Sketches:

- **The evaluator** — has a budget, a shortlist and a deadline; judges against
  alternatives rather than in isolation. Values: pricing clarity, migration cost,
  proof it works.
- **The administrator** — sets the product up for other people. Lives in settings,
  permissions, seat management, SSO. Wants Hat 2's tools and none of Hat 3's.
- **The integrator** — wants Hat 3's tools. Reads the docs, takes the key, runs
  the snippet, reports where the promise and the artifact diverge.
- **The compliance reader** — looks for the data-handling page, the subprocessor
  list, the retention statement. Reports what could not be found, which is the
  finding.

Each is a config, not a code path. The gate on adding one is whether it changes
what the system *does*, not what it *says*: a hat that produces the same actions
in a different tone is a prompt, and belongs in a persona profile rather than
here.

- [ ] **A capability manifest per hat**, so a report can state which hat produced
      a finding and what that hat was able to reach. A reader needs to know
      whether "I could not find the retention policy" came from someone who could
      only browse or from someone who could also search the docs site.

---

## What this changes about testing

Every hat widens what a run can touch, so the test strategy widens with it rather
than after it:

- **Each tool is unit-tested against a fake world** — the `Tool` seam takes an
  injected runner already, which is how `travelTo` is tested without a browser.
- **Each safety rail has a test that proves the rail, not the happy path.** An
  allowlist needs a test that a command off it is refused; a redactor needs a
  test that an account name in a snapshot does not reach an artifact. This record
  has three separate cases of a guard that passed by doing less — those tests are
  the ones that catch it.
- **One live cycle per hat**, measured with the same script and the same table, so
  a hat that makes runs worse is visible immediately rather than at the end.
- **The noise floor from §0 applies to all of it.** A hat cannot be called an
  improvement on one run.
