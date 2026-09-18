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

- [ ] **Find out why a run ends inconclusive.** All three personas hit
      frustration 1.00 and confusion 1.00 in most cycles. Read the last five steps
      of an inconclusive run and name the step where it stopped making progress.
      Do this before changing anything.
- [ ] **Check whether 16 actions is enough.** Runs end "still going after 16
      actions". If the step budget is the binding limit rather than the persona's
      patience, the verdict is an artifact of the budget and says nothing about
      the page.
- [ ] **The 13 remaining refusals.** All were frame refusals before cycle 51 made
      the screenshot primary; check what they are now. A refused step still costs
      the persona a turn.
      *Done when:* two of three runs reach a verdict other than inconclusive.

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
