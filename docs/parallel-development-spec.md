# Parallel development spec

Written 2026-09-23, against the tree at `915173a`. It reconciles four sources:

- the audit *Observed vs Explained*: 68 criteria, taken at cycle 26;
- the report contract in `spec.md` §29–§31, as rated in `last_runs/REPORT_CRITERIA.md`;
- the cycle record in `docs/next-cycle-worksheet.md`, cycles 44–51;
- the live snapshot in `last_runs/`, one persona against `https://open-design.ai/`,
  job `job_90142999fc7640a0924ebef82c2be471`, 2026-09-22.

The one-page board version is `docs/parallel-development-overview.md`.

It replaces the three-track schedule in `docs/next-cycle-plan.md` ("How the three
tracks run in parallel"). That plan's items are nearly all built. This document
schedules what is left, and it does so as **ten lanes that run at the same time**.
Each lane has its own files, input contract, offline inner loop and metric. The
metric is read by one shared scorer, and a lane does not grade itself.

**Naming.** Lanes are `L0` to `L9`. Items are prefixed by lane: `RUN`, `JRN`,
`EVD`, `FND`, `SEC`, `PRS`, `SCL`, `HAT`, `PSN`, `OPS`. A bare letter-digit code
such as `B2` or `E7` is still an audit criterion. `RPT-n`, `BE-n` and `CAP-n` are
still the previous plan's items. `§n` is a section of `spec.md`.

---

## 1. Where it stands

The cycle record, one run per commit against `taoshq.com`:

| | 49 | 50 | **51** |
|---|---|---|---|
| refused | 24 | 34 | **13** |
| price in report | 68 | 361 | **545** |
| sources | mixed | mixed | **26/26 screenshot** |
| verdicts | 1 failed, 2 inconc. | 3 inconc. | **1 passed**, 1 inconc., 1 failed |

Since cycle 51, the previous plan's items have landed. Here is their status:

| Done | Partly done | Not started |
|---|---|---|
| RPT-1, RPT-2, RPT-5, RPT-6, BE-1, BE-2, BE-3, CAP-1, CAP-4, CAP-5, CAP-6 | CAP-0 (the loop siblings), CAP-2 (manifest, CRUD UI), CAP-3 (per-hat buttons), RPT-3 (the re-run), RPT-4 (four sweep checks, D8), BE-5 (repeat seeds) | **BE-4, the noise floor.** `measure.py` and `cycle-cohort.sh` were never committed. They lived in a session scratchpad that no longer exists. |

Against the report contract, `REPORT_CRITERIA.md` rates §30 at 6 met, 2 partial
and 1 missing. The missing section is §30.4, the experience trajectory. §9 is
rated higher than the run supports (see 2h).

**Nothing has been measured twice.** Every figure in the record is n=1 per
commit, and `refused` has moved by a factor of four between commits that changed
nothing relevant. That is the reason the run factory (L0) comes before anything
else in this document.

## 2. What the last run shows that the documents do not

This is the first live run since the RPT, BE and CAP work landed. Every claim below
was read from `last_runs/artifacts/*.json`, or from a crop opened and looked at.
The site is different from cycles 44–51, so no figure here can be compared with
those cycles.

**a. The finding the report leads with is false.** The executive summary says
*"The one thing to change: Fails WCAG AA contrast: 'Video'"*. The report has four
"Fails WCAG AA" findings, all at high severity. Their ratios are 1.13, 1.03, 1.03
and 1.04:1. Two of the crops were opened. The "Video" crop is 1212×36 px of blank
page under the row of pills, with a faint background grid. The "Italiano" crop is
86×15 px of white. This is §55.3's rule 2 ("no ink is not low contrast") and rule 4
("1.00:1 is not a measurement") failing again. The likely mechanism is still a
hypothesis. `optics.py:356` flags `nothingDrawn` only when internal *and* edge
contrast are both under 0.02 *and* ink is at or below 0.0005. A patterned
background would clear those thresholds without any text being drawn. → **EVD-1**,
**FND-1**

**b. A run failure is filed as a usability finding.** *"Users could not finish the
tasks they came to do"* (`source: criteria`, high) sits in `critical_pain_points`,
and `run_diagnostics` is `[]`. The run ended because its budget ran out, which is
an ending of the harness. RPT-4 records this as "already true". It is true for
harness failures and not for budget endings. → **SEC-1**, **JRN-4**

**c. The persona cannot leave.** From step 1 to step 10, frustration goes
0.13 → 1.00 and confusion reaches 1.00 at step 7. The probability of abandoning
never exceeds **0.033**. At `behavior.js:160` the controller sets
`copingMode = "abandoning"` when tolerance is crossed, and line 163 overwrites it
unconditionally, so the tolerance check has no effect. The run ends
"inconclusive" at the budget (12 = `max(12, 1×8)`). For a person at frustration
1.0, leaving is the finding. → **JRN-1**

**d. The loop has moved, not gone.** The action trace is
`Pricing ↔ Start free for 30 days`, seven alternating clicks. "Pricing" was clicked
four times under three different refs (`e153`, `e27`, `e367`). The adherence gate
scored the last three actions 3, 4 and 0 against a threshold of 7. All three are
recorded with `passed: false`, and the run took them anyway: two of the three have
a pointer event on the page. The judge is also judging blind. Its objection to a
click on `e367` was *"Clicks unrelated 'e367' despite … clear pricing goal"*, and
`e367` is the Pricing link. It sees the ref, not the label.
`state.repeatedEventCounts` is recorded, and no control flow reads it. → **JRN-2**,
**JRN-3**

**e. CAP-0 works live.** On page one, `notLookedAt` goes 47 → 27 → 8. After
navigation it goes 30 → 0. The fixation budget is 22. All 12 captures were
trustworthy and none was refused. All 10 pointer events had a measured box, with 0
misses. This is the first live confirmation of the scan-memory half of CAP-0's
done-when.

**f. Yield is up, but most of the structure is empty.** The report has 14 findings,
13 of them about the site, and 1 positive. Per finding, the fields are filled as
follows:

| field | filled |
|---|---|
| `retest` | 14/14, all from one template |
| `reproducedIn` | 14/14, always 1 |
| `alternatives` | 5/14, with `effort` set on only 1 |
| `rootCause` | 4/14 |
| `personaEvidence` | 5/14, 2 of them *"You are calm."* |
| `grounding` | 1/14 |
| `confidence` | 0/14 |
| `videoTimestampMs` | 0/14 |

Every timeline event already carries `videoTimeMs`. Expectations: 0 met, 6 missed.

**g. The report praises and faults the same control.** The one preserved element
is *"The prominent 'Download OpenDesign free' button"*. Finding 12 is *"Promised
more than it did: Download OpenDesign free"*. Nothing reconciles the two.
→ **FND-5**

**h. The evidence channels are empty.** The run's artifact lists are all empty:
`snapshots`, `console`, `network`, `uiChanges` and `videoClips`.
`REPORT_CRITERIA.md` §9 says DOM snapshots "exist per-screenshot… see
`artifacts.snapshots`", but that list is empty. §9 should be *partial*, not *met*.
→ **EVD-2**

**i. Where the time goes.** The run took 243 s. It made 55 model calls using
53,278 tokens, with 176 s of model wall time. By role:

| role | calls | model wall time |
|---|---|---|
| adherence | 21 | **83 s (47%)** |
| acting | 22 | 44 s |
| reflection | 9 | 43 s |
| redesign | 3 | 5.5 s |

The adherence judge is the largest single lever on run speed. → **JRN-3**, **OPS-3**

**j. Storage is ephemeral.** The deploy log says: *"No writable /data mount found;
using ephemeral in-container storage — reports will not survive a Space
restart."* → **OPS-1**

## 3. How the lanes work

A lane has the following parts. A lane missing any of them is not ready to hand to
an agent.

| part | meaning |
|---|---|
| **Owns** | Paths only this lane edits. They are disjoint from every other lane after RUN-0. |
| **Consumes / produces** | Named contracts from §4, and nothing else. A lane never reads another lane's internals. |
| **Inner loop** | Offline, seconds to a minute. It runs against the frozen fixtures and the replay of `last_runs/`. It never needs the Space. |
| **Outer loop** | The shared live cycle (RUN-2), 6–8 minutes. It is run for acceptance, not for iteration. |
| **Metric** | One or more rows of the scoreboard (§5), computed by `measure.py` from artifacts. |

The rules:

1. **Contracts change first, alone, and only by adding.** A contract change is a PR
   that changes three things: the contract document, a fixture, and a test that
   the consumer tolerates the field being absent. It merges before the producer PR
   and before the consumer PR. A field is never renamed or removed while any
   consumer reads it.
2. **Fixtures before live.** Every lane's inner loop runs against
   `tests/fixtures/contracts/` and the replay of `last_runs/`. The live Space is
   for acceptance. Iterating against it is what made one cycle a day the ceiling.
3. **One scorer.** Only `scripts/cycle/measure.py` says whether a run got better.
   It reads the fields where the report speaks (§55.6h), parses JSON rather than
   grepping it, and never reads the persona's own sentences.
4. **The noise floor gates the word "better".** A movement that is within the
   recorded floor (RUN-6) is reported as unchanged. Before the floor exists,
   nothing is called an improvement on one run. This rule applies to every lane.
5. **Small PRs, one lane each, branch `lane/<Ln>/<item>`.** Rebase onto the base
   branch daily. A PR that touches two lanes' paths is split, or it goes through
   the lane that owns the contract between them.
6. **The existing non-negotiables still hold.** They are listed in
   `docs/next-cycle-handover.md`: faculties are added and never replaced; no key is
   logged; a capability is mounted only when a run asks for it; every rail has a
   refusal test; services do not share a database. So do the worksheet's ground
   rules: look at the artifact, a measurement of the record is a measurement,
   constrain rather than delete, and a guard that cannot run has not passed.

## 4. Contracts between lanes

Each contract gets a short file in `docs/contracts/`, plus a fixture in
`tests/fixtures/contracts/` derived from `last_runs/`. L0 owns the directory, and
each contract's producer owns the content of its file.

| id | contract | producer → consumers | additions this cycle |
|---|---|---|---|
| **K1** | `journey-timeline`: the event types `persona.{perception,expectation,reflection,affect,pointer,adherence}`, `journey.*`, and their `data` fields | L1, L2 → L3, L4, L0 | `journey.ending.reason` ∈ {`completed`, `gave_up`, `budget`, `diagnostic`} (JRN-4); `persona.loop` (JRN-2); `persona.wait` with measured ms (JRN-7); walked-element `tag`, `headingLevel`, `alt`, `labelFor`, `focusVisible`, `color`, `fontPx`, `radius` (EVD-6, EVD-7) |
| **K2** | `finding` (UXPainPoint) | L3 → L4, L5, L0 | `confidence` (FND-3); `evidenceKind` ∈ {observed, inferred, grounded, proposed} per claim (SEC-6); `videoTimestampMs` and `step` (SEC-5); `alternatives[].effort` ∈ {copy, layout, behaviour} and `tradeOff` (FND-4); `instances[]` for grouped findings (FND-1) |
| **K3** | `ux.report` | L4 → L5, L0 | `experience_trajectory` (SEC-2), `ranked_alternatives` (SEC-3), `knowledge_basis` (SEC-4), `evidence_index` (SEC-7), named `journey_outcome` counts (SEC-8) |
| **K4** | `scoreboard`: metric names and definitions | L0 → everyone | §5 |
| **K5** | `run request`: the `/v1/runs` payload | L6, L7, L9 → L1 | per-run seed and synthetic run id `persona_id#seed` (SCL-1); `retestOf` (SCL-3) |
| **K6** | `vision cache`: recorded vision-critique responses per screenshot | L3 → L0 | Needed for offline replay (RUN-3) |

## 5. The scoreboard

`measure.py` computes the scoreboard on every live cycle and every replay. The
baseline column is the `last_runs/` run. It is n=1, one persona, one task, a
different site from the cycle record, and no noise floor has been measured.

| group | metric | baseline | target |
|---|---|---|---|
| journey | verdicts passed / failed / inconclusive | 0 / 0 / 1 | ≥ 2 of 3 non-inconclusive per target, over 3 same-commit cohorts |
| | budget-hit share | 1/1 | ≤ 1/3 |
| | runs ending at frustration ≥ 0.9 without leaving | 1/1 | 0 |
| | loops (same label clicked ≥ 3 times, or A↔B ≥ 2 times) | 1 | 0 |
| | executed actions with adherence below threshold | 2 (pointer-confirmed; a 3rd failed action has no matching pointer event either way) | 0 |
| | expectations met rate | 0/6 | reported, no target (it is the site's number) |
| perception | captures / refused | 12 / 0 | within the noise floor |
| | legible share (pooled) | 0.84 | within the noise floor |
| | `notLookedAt` slope within a page | falls | falls |
| | pointer measured / missed | 10/10, 0 | ≥ 95% measured |
| findings | findings about the site / positives | 13 / 1 | ≥ 10 / ≥ 2 (RPT-4's done-when) |
| | run diagnostics among findings | **1** | 0 |
| | "Fails" at ratio < 1.2 with no verified ink | **4** | 0 |
| | same control both preserved and faulted | **1** | 0 unless the report reconciles them |
| | contentless persona quotes | 2 | 0 |
| fill rates, per site finding | alternatives with effort | 1/13 | 13/13 |
| | confidence | 0/13 | 13/13 |
| | videoTimestampMs, when a screenshot exists | 0/8 | 8/8 |
| | rootCause | 4/13 | every class that can state one honestly |
| | grounding | 1/13 | ≥ half |
| contract | §30 sections met / partial / missing | 4 / 4 / 1, by `measure.py`'s own computation (§5 and §9 downgraded from the hand rating's 6/2/1 — §5 requires every finding to carry its core fields, not most; §9 requires all four evidence channels, not two) | 9 / 0 / 0, computed rather than rated by hand |
| | §31 four-way tag present per claim | no | yes |
| cost | run wall (s) / model calls / tokens | 243 / 55 / 53k | reported every cycle |
| | adherence share of model wall | 47% | ≤ 25% |
| | cohort wall, 3 personas × 2 targets | not measured | ≤ 8 min |
| stability | findings with `reproducedIn` ≥ 2 in a repeat cohort | not measured | ≥ 1/3 |

## 6. The lanes

### L0 · Run factory and scoreboard (`RUN`)

**Why it comes first.** A cycle today is done by hand: a deploy, a POST, polling,
downloading, and reading JSON. The scripts that measured cycles 44–51 are gone.
Replacing hand work with a command, and live iteration with an offline replay, is
what turns "one cycle a session" into "a cycle per merge".

**Owns:** `scripts/cycle/**` (new), `tests/replay/**` (new),
`tests/fixtures/contracts/**` (new), `docs/contracts/**` (new),
`docs/scoreboard.md` (new), `last_runs/**`, and a `runs/` entry in `.gitignore`.
Once, for RUN-0 only: `apps/api/executor.py` and `services/report_service/**`.

| item | what | done when |
|---|---|---|
| **RUN-0** | **The seams. First, alone, mechanical, in the same way as BE-2.** (1) Extract `assemble_report(journeys, personas, tasks, url, *, vision, redesign)` out of `_combined_test` (`executor.py:131`, roughly lines 200–490), where dispatch and assembly are currently interleaved. (2) Split `assembler.py` (3882 lines) by responsibility. Producers go to `findings/{expectation,perception,vision,structure,merge}.py`. Report-level parts go to `sections/{summary,scorecard,impact,preserve,narration,…}.py`. Rendering goes to `render/{deck,presentation}.py`, which is `assembler.py:3431–3882`. Pixels go to `media.py` (crop, marker, redact, palette). A mixin may stay where references demand it, as BE-2 found. | The failing tests are identical by name before and after. No assertion changes. L3, L4 and L5 now own disjoint files. |
| | **(1) done.** `ReportAssembler.assemble_report()` (a `@classmethod`, `services/report_service/assembler.py`) is `_combined_test`'s old lines 227–490, moved verbatim apart from `self.`→`cls.` and four job/data reads turned into plain arguments (`job_id`, `url`, `vision`/`redesign` — one provider chain, resolved once in `_combined_test` since only it may read `job` — and `send_vision_options`). `_combined_test` now ends by resolving those four values and calling `self.assemble_report(...)`; it still owns everything before that (persona/task loading, session/credential/hat setup, the concurrent dispatch pool). Verified: 488/3/3 Python, identical failure names to baseline; 292/292 Node, both before and after. **(2) not attempted this pass, stated rather than silently dropped.** `assembler.py` is now ~4575 lines (3882 + the moved method's ~700 with its docstring). A real responsibility split needs either several mixins combined the way BE-2 already combines `ReportAssembler` into `JobExecutor`, or module functions taking `cls`-shaped state explicitly — both are a second mechanical move at real risk of import cycles (findings producers call into render helpers for evidence crops; sections call findings producers), and RUN-1/RUN-3, which everything else waits on, need the `assemble_report` seam, not the file layout. Left for a dedicated pass once RUN-1/RUN-3 are unblocking other lanes. |
| **RUN-1** | Commit `measure.py` with every metric in §5. It reads parsed JSON, only from the fields where the report speaks, and emits JSON plus a Markdown row. | Run on `last_runs/`, it reproduces the baseline column of §5 exactly. |
| | **Done.** `scripts/cycle/measure.py` computes every §5 row from `last_runs/artifacts/ux_report__*.json` and `journey_log__*.json` — journey/perception metrics from the raw journey log (the file `RUN-3`'s replay is built from, so a rebuilt report scores the same), findings/fill-rate/contract/cost metrics from the assembled report. `compute_metrics(run_dirs)` is importable; `main()` writes JSON and a Markdown row. 13 tests in `tests/contract/test_measure.py` pin every group against `last_runs/`, plus unit tests for `has_loop`, `not_looked_at_slope` and `step_budget`. Building the real scorer corrected two hand-counted figures from earlier in this spec, both now fixed at every row they appeared in: **executed actions below threshold** is 2, not 3 — only 2 of the 3 sub-threshold adherence events have a matching `persona.pointer` event within 5s, and the scorer refuses to claim the 3rd executed without that evidence; **video-timestamp fill rate** is 0/8, not 0/9 — the denominator is findings *about the site* (excluding the misfiled `tasks-completed` diagnostic SEC-1 relocates), and that diagnostic happens to carry `evidenceScreenshot`. The §30 contract row is now `4/4/1` by real computation, not `6/2/1` by hand: `measure.py` downgrades §5 (critical pain points) and §9 (full evidence) from "met" to "partial" against the stricter, named checks in the scorer's own `report_contract_sections()` — every finding must carry its core fields for §5, and all four evidence channels must be non-empty for §9, not just the two that happen to be. Verified: 501 passed / 3 failed (Python, same 3 baseline failures by name), 292 Node unaffected (Python-only change). |
| **RUN-2** | Commit `run_cycle.py --targets … --personas … --repeats … --commit …`. It confirms deploy and readiness, submits the cohort over the benchmark set, polls, downloads every artifact to `runs/<cycle>/<target>/` (gitignored), calls `measure.py`, and appends a row to `docs/scoreboard.md`. | One command produces a scoreboard row, with no hand steps. |
| **RUN-3** | **Offline replay.** `replay_report.py <run-dir>` calls `assemble_report()` on a saved run. It remaps screenshot paths, and it reuses cached vision responses (K6) instead of calling the model. | The report is rebuilt from `last_runs/` in under 30 s. L3, L4 and L5 iterate against this rather than the Space. |
| | **Done, with one real deviation from "reuses cached vision responses (K6)."** `scripts/cycle/replay_report.py` calls `ReportAssembler.assemble_report(vision=[], redesign=[], worker_configured=True)` — both are true no-ops (`_collect_vision_pain_points`/`_generate_redesign_fragment` return immediately on an empty-but-not-`None` provider list, confirmed by reading their own guard clauses, not assumed), so replay makes zero network calls rather than replaying a cached one. K6 (the vision cache) is not built this pass: `last_runs/` carries no recorded vision responses to replay from, and building the cache needs a live run to populate it first — a chicken-and-egg RUN-4 (live cycles) resolves, not RUN-3. Stated as a real gap: today's replay is *vision-absent*, not *vision-replayed*, and the diff against the live report documents exactly what that costs (below). `replayed in 0.17s` on `last_runs/`, well under the 30s bound. **`build_screenshot_remap()`, not in the original plan's one-line description.** A saved run's screenshot/video paths point at the deployment's own filesystem, which does not exist here; `last_runs/` keeps 6 renamed files (`AGENTS.md`'s own naming). Recovered the original-path → local-file mapping from `logs/job_final.json`'s `output_artifacts` (written in the exact creation order `_browser_outputs()` emits: every screenshot in `journey.artifacts.screenshots` order, then the video — verified, not assumed: every one of the 6 recovered mappings was cross-checked against the local file's own magic bytes, and all 6 matched), then rewrote every occurrence of an original path anywhere in the journey's JSON tree (`_remap_paths`, a generic recursive substitution — covers `artifacts.screenshots`, `artifacts.video`, and `persona.perception`'s own `seenImage`, without naming every field). Result: all 6 kept screenshots remap cleanly on `last_runs/`; `matched_findings_missing_screenshot_crop` is empty. **`_served_by`, a third run-half back-reference RUN-0 missed.** Making `assemble_report` callable on bare `ReportAssembler` (not only through `JobExecutor`) surfaced that `cls._served_by(journeys)` was still only defined on `JobExecutor` — a real oversight in RUN-0, not a deliberate deferral like `_vision_timeout`/`_worker_error`: it reads only `journeys`, summarises a report field, and belongs beside `_model_usage_summary` on the same grounds BE-2 already used for everything else in `ReportAssembler`. Moved (`apps/api/executor.py` → `services/report_service/assembler.py`), unchanged apart from the move; `_vision_timeout`/`_worker_error` stay genuine back-references (environment reads, live HTTP error formatting) and are correctly never reached with `vision=[]` (both calls sit behind `_collect_vision_pain_points`'s own early return). **What actually differs from the live report, verified rather than assumed** (`diff_reports()`, and `tests/contract/test_replay_report.py`'s own assertions on it): the one `eyeson-vision-synthesis` finding is absent; three findings lose `redesignHtml`; `elements_to_preserve` goes from 1 to 0 — confirmed by calling `_praise_from_verdicts`/`_preserved_from_verdicts`/`_preserved_from_met_expectations` directly against this journey, all three return `[]`, so the live report's one preserved element came entirely from the vision worker's own declared `raw_strengths`, which `vision=[]` never fetches; `model_usage.byRole` loses `report.redesign` (no Python-side model call happened) and is otherwise identical, because the Node-side usage log is baked into each journey's own `modelUsage`, unaffected by replay. Ten new tests (`tests/contract/test_replay_report.py`): the no-network-call guarantee (a monkeypatched `urlopen` that raises), the documented diff categories on `last_runs/`, the remap's magic-byte cross-check on both a match and a deliberate mismatch, a count-mismatch case left unmapped rather than guessed, the recursive substitution's exact-match-only behaviour, and both missing-input refusals (no persona profile, no job metadata) naming what is missing. Full regression: 511 Python tests passing (same 3 pre-existing baseline failures by name), 292 Node tests unaffected. |
| **RUN-4** | **Snapshot v2.** `last_runs/` currently holds only 6 PNGs, so crops cannot be recomputed. It must hold a replayable run directory (`run.json`, `events.ndjson`, `screenshots/` including the `*-as-they-saw-it.jpg` files) and the vision cache, within about 15 MB. `refresh_last_runs.py` automates steps 1–8 of `last_runs/AGENTS.md`, overwriting in place. | Running `refresh_last_runs.py` then `replay_report.py last_runs/` gives the same ux.report as the live run, apart from timestamps. |
| **RUN-5** | **Golden invariants** in `tests/replay/`, run on every PR. They cover §55.3 rules 2–4 (no "Fails" without ink; no ratio near 1.00 treated as a measurement), no run diagnostic among the findings, every §30 section present, and every artifact reference resolving (§53.2 #2). | The invariants fail on today's `last_runs/` (2a, 2b) and pass once EVD-1, FND-1 and SEC-1 land. |
| | **Done, "every §30 section present" scoped honestly rather than asserted early.** `tests/replay/test_golden_invariants.py` (new) checks four report-level properties against `replay_report.replay(last_runs)`: no `false_contrast_findings()` (FND-1, reusing `measure.py`'s own classifier rather than a second copy), no `misfiled_diagnostics()` (SEC-1, same reuse), every cited `evidenceScreenshot`/`screenshotRef` resolves to a real local file (§53.2 #2, exercising RUN-3's remap), and no finding leaks a leading-underscore temp field (a general-purpose guard, not scoped to FND-1's two named fields — the next finding builder that stashes working state on the dict gets caught the same way). **Both directions of "prove both," using real data rather than a code revert.** `test_the_live_snapshot_violates_the_invariants_this_file_guards` runs the *same* checks against the static, unmodified `last_runs/artifacts/ux_report__*.json` — the actual pre-fix output this session started from, still on disk — and confirms it fails all three defect-shaped ones (4 false-contrast findings, 1 misfiled diagnostic, no `experience_trajectory`); the four "now" tests confirm today's replay passes every one. No git checkout needed: the "before" state is real, not simulated. **"Every §30 section present" is pinned, not asserted as fully achieved.** The plan's own wording said "pass once EVD-1, FND-1 and SEC-1 land" — but two sections (§6 eyeson review, needing live vision; §8 knowledge basis, needing SEC-4) are honestly still missing on an offline, vision-absent replay, pending lanes this session did not touch. A golden test asserting "0 missing" today would be lying about the tree's real state — worse than useful, since the FIRST thing anyone would do on a failure is disable the check. Instead `ASSERTED_CONTRACT = {"met": 5, "partial": 2, "missing": 2}` pins today's real, computed state (`measure.py`'s own `report_contract_sections()`), with the module's own docstring instructing whoever closes §6/§7/§8/§9 to update the number in the same PR — and a separate, permanent assertion that §4 (SEC-2) specifically is never missing again, since that is the one this session actually closed. Six tests, all passing: the proof, and the four invariants themselves. Full regression: 540 Python tests passing (same 3 baseline failures by name), 292 Node tests unaffected. |
| **RUN-6** | **The noise floor (BE-4).** Three same-commit cycles over the benchmark set. Record the min and max of every metric in §5 in `spec.md` §56 and in `docs/scoreboard.md`. | A later cycle can be called better or worse with a reason. |
| **RUN-7** | **The benchmark set, pinned.** Targets: `taoshq.com` (the record for cycles 1–51: the pricing page and billing toggle), `open-design.ai` (this snapshot: download and value proposition), and one signed-in site the operator controls, for L7. Each target has two fixed tasks. Three pinned persona artifacts with fixed seeds span patience, persistence and acuity. The last persona had persistence 0.8 and exploration 0.9, a profile that never quits. | Every live cycle runs the same inputs, so rows are comparable. |
| **RUN-8** | **CI.** The repository has no `.github/`. Add a workflow for the Python suite (with the baseline's three dspy failures listed as known), the Node suite, and `tests/replay/`. | Every lane PR gets the same gate without anyone running it by hand. |
| | **Done.** `.github/workflows/tests.yml` (new): two parallel jobs on every push and PR. `python` installs the exact package set `docs/next-cycle-handover.md`'s own baseline procedure names (kept in sync with that file, not a second list) and runs `pytest tests/ --ignore={e2e,load,integration}` — the same command this session's every item was verified against — with the three dspy-gated tests removed by `--deselect`, named explicitly, rather than left to fail the job silently or masked by installing dspy (`AGENTS.md` keeps it uninstalled deliberately). `tests/replay/` is not a separate job or step: nothing in `pytest.ini` restricts discovery and it is not in the ignore list, so RUN-5's golden invariants fail the same job a unit test would; called out by name in the step regardless, so a failure there reads clearly in the Actions UI. `node` runs `npm run check` (a syntax check across every source file) then `npm test`, with no `npm ci` — the worker's test suite does not import `agent-browser`/`journeytest-core` directly, verified locally, repeatedly, this session, with `node_modules` absent throughout. Verified by running both jobs' exact commands locally rather than trusting the YAML: the Python command gives `540 passed, 3 skipped, 3 deselected` (exit 0); `npm run check` and `npm test` both exit 0 with `node_modules` absent, matching the job as configured. |

### L1 · Journeys that finish (`JRN`)

**Owns:** `services/journey-worker/node/src/{behavior,personaDirector,personaActor,adherence,memoryBank,journeytest,faculty,replay}.js` and their tests.
**Produces:** K1. **Inner loop:** `node --test`, plus `replayFromEvidence()` (`replay.js`) over the snapshot's affect events.

| item | what | evidence | done when |
|---|---|---|---|
| **JRN-1** | Make abandoning reachable. Remove the dead assignment (`behavior.js:160`, overwritten at `:163`). When tolerance is crossed, make abandoning the dominant score rather than one term in a softmax that `reread`/`retry`/`explore` outweigh at a persistence of 0.8. | 2c: p(abandon) ≤ 0.033 at frustration 1.00 | No run ends at frustration ≥ 0.9 still browsing. A replay of the snapshot's affect series for this profile abandons by the step where tolerance is crossed. |
| | **Done, with "replay" read as re-scoring the real recorded states rather than literally re-invoking `replayFromEvidence()`.** The dead assignment was `BehaviorController.apply()` computing `this.state.copingMode = "abandoning"` off the same tolerance check, then unconditionally overwriting `copingMode` (and never touching `abandoned`) three lines later from `coping.decision.type` — a correctly-computed label the rest of the function threw away, not a bug in the tolerance math itself. Moved that same arithmetic into a shared `abandonTolerance(profile)` (`repeatFailureTolerance + persistence * 0.35`, unchanged), now called from `copingScores()`, the one place that can actually change what gets sampled. `copingScores` builds its `scores` object as before, then, only when `state.consecutiveFailures > 1 && state.frustration > abandonTolerance(profile)`, adds `1 + clamp(frustration - tolerance) * 4` to `scores.abandon` — zero effect below tolerance or on an isolated single failure (both proven by exact-value assertion against the unboosted formula, not just "the score changed"), growing with how far over. **Verified fresh against the real trajectory, not the prior session's transcript.** `last_runs/artifacts/journey_log__*.json`'s 10 `journeytest.persona.affect` events carry the real profile's exact final `state` per step but not the raw `event` object `apply()`/`replayFromEvidence()` need as input (confirmed: only `state`/`coping`/`probabilities`/`feeling` are persisted) — so a literal `replayFromEvidence()` run over this snapshot is not reconstructable, a real gap in what "replay" can mean here, stated rather than papered over. What *is* checkable, and was re-run this session against the actual persisted profile (`persistence: 0.8`, `repeatFailureTolerance: 0.5` → tolerance `0.78`) and all 10 real states: `copingScores`/`probabilities` are pure functions of `(profile, state, context)`, and the fix lives entirely inside them, so evaluating both the pre-fix and post-fix formula against every real recorded state is equivalent to replaying this specific fix, independent of how each state was reached. Result, `context: {}` both sides for a fair comparison: steps 1–8 (below tolerance) unchanged to 4 decimal places (e.g. step 8: 0.0173 both); step 9 (frustration 0.889, first step past tolerance) 0.0272 → 0.3316, leader flips from `reread` to `abandon`; step 10 (frustration 1.000, the run's last step) 0.0359 → 0.6154, `abandon` the clear leader — this session's own re-derivation lands on the same step-10 figure (0.615) the prior session's transcript claimed, to 3 decimals. On the shared test-file fixture (`persistence: .25`, tolerance `0.2875`, a much less persistent profile) the same shift is visible sooner: pre-fix p(abandon) peaks under 0.09 and `impulsive_retry`/`backtrack` lead at every step through frustration 1.00 sustained; post-fix, the second repeated failure alone crosses tolerance and `abandon` leads at 0.665, rising to 0.989 by the third. Four new tests in `test/behavior.test.js` (12 total, up from 8): `abandonTolerance`'s formula on two profiles; the boost's three-way gate (below tolerance, above tolerance with only one failure, above tolerance with two — each checked against the unboosted formula by exact value, not just inequality); the leader flip through a real `BehaviorController` run on the shared fixture; and a fully deterministic end-to-end case (seed 8, second failure) where the *actual sampled* `coping.decision.type` is `"abandon"` and `state.abandoned`/`copingMode` become `true`/`"abandoning"` — proving the wiring, not just the probability. Full regression: 296 Node tests passing (292 + these 4, no other file touched), 540 Python tests passing / 3 skipped / 3 deselected (this is a Node-only change; run anyway per this session's standing discipline of checking both suites on every commit). |
| **JRN-2** | Break loops. Recognise the same control across refs by its label (the three "Pricing" refs), and recognise A↔B alternation. Emit `persona.loop`. Tell the director what already happened ("you have clicked Pricing three times; each time …"). Make coping switch to explore, backtrack or abandon. | 2d; worksheet: `e17`/`e18` × 6 | Loops = 0 over a cohort. |
| | **Done, with "Loops = 0 over a cohort" left honestly open -- that number needs a live rerun (RUN-2/RUN-6), out of scope here same as every other live-acceptance criterion this session.** New `services/journey-worker/node/src/loopDetector.js` (not in L1's literal file list -- a new sibling of `replay.js`, the same class of deviation RUN-3's `_served_by` move was: small, single-purpose, no existing owner). `detectLoop(recent, current)` tracks the run's real, ordered, label-keyed action history (an 8-action window) and reports two independent things: `repeated` (this exact control, 3 or more times in the window -- matching `measure.py`'s own, independently-written `_LOOP_LABEL_MIN = 3`, confirmed by name rather than assumed) and `alternating` (a strict A, B, A, B in the last 4). `outcomeEvent()` (personaDirector.js) takes an optional third `label` argument and its `repeatKey` uses it when given, falling back to the ref exactly as every existing caller's two-argument call already did -- so the escalating-repetition math `reduceState()` already had for exactly this case (`repeatedEventCounts`, unbounded, whole-run) now actually engages instead of seeing three different once-used ref keys. `run()` computes the label once per step (`nameOf(target, perception)`, falling back to the ref) and reuses it three ways: `describeTarget()` (already imported from personaActor.js for reflection prompts) now renders the persona's own `history` entries the same way its system prompt already insists on ("CLICK the \"Pricing\"", not "CLICK e153" -- the history shown back to the model contradicted its own instructions never to mention refs, a real adjacent defect this closes as part of the same fix); the loop detector's key; and `outcomeEvent`'s new label argument. When a loop is detected, `persona.loop` is recorded (`repeated`/`alternating`/the action/the label) and a notice in the persona's own words (`loopNotice()`, e.g. `You keep going back and forth between "Pricing" and "Start free for 30 days" without getting anywhere.`) is pushed into `history` -- read on the very next actor call, not only kept for a report nobody in the run itself reads. **Verified against the exact real sequence, reconstructed and checked twice.** `last_runs/artifacts/journey_log__*.json`'s 12 `persona.expectation` events, with the 2 whose proposal was never performed (coping sampled `reread` the step before, which skips acting entirely) left out -- confirmed by their missing a following `persona.pointer`/`persona.affect` pair, not assumed -- give the real 10-action performed sequence. Run through `detectLoop` (`tests/loopDetector.test.js`'s own last test, and independently by hand before that): silent through the first 6 actions, `alternating` fires on action 7 (the second Pricing→Start-free round trip), both `alternating` and `repeated=3` on action 8, `repeated=4` on action 9 once the alternation itself breaks into a same-control repeat, `repeated=3` on action 10 -- the detector recognises the whole real degenerate sequence from the point it actually became one, using only the two mechanical rules, no special-casing of this example. `measure.py`'s own `has_loop()`, run against this same run's raw `timeline` (unfiltered by execution -- it counts the 2 skipped proposals too, a stated, deliberate asymmetry from `loopDetector.js`'s performed-only scope, since a scorer grading a finished run and a mechanism steering one mid-run have different reasons to be lenient or strict), independently confirms `True` on this baseline, and its own click-label sequence matches the reconstruction byte for byte. **`copingScores` (behavior.js), calibrated against the same real profile JRN-1 used, not guessed.** `context.loopRepeatCount`/`context.loopAlternating` (computed by the director, passed alongside `taskImportance`/`progressVisible`) boost `explore`/`backtrack` by 1.1 and suppress `continue`/`retry`/`impulsive_retry` by 0.8/0.8/0.6 -- the three options that produced the loop, not only their replacements, because lifting the replacements alone still left `reread` (which changes nothing about what happens next) leading at every real state checked. A first version boosted only `explore`/`backtrack`/gave `abandon` nothing, and re-scoring the real run's own last step (frustration 1.00, tolerance already crossed by JRN-1) showed why that was wrong: p(abandon) fell from JRN-1's own 0.615 to 0.284, diluted by softmax renormalisation exactly where the previous item had just made it competitive. `abandon` now gets its own, smaller +0.7 share of the same boost -- calibrated so it is negligible below tolerance (0.010 to 0.015 at frustration 0.55, where `explore` correctly takes over from `reread` at 0.412 instead) and holds firm at or above JRN-1's own figure once tolerance is also crossed (0.615 to 0.617 at frustration 1.00, `backtrack` a strong second). A loop compounds with crossed tolerance rather than fighting it. **What this does not do.** `reread`/`wait`/`seek_help` are untouched -- re-reading during a loop is a legitimate reconsideration, not the pattern itself. `explore` itself still has no distinct effect in `run()`'s own coping switch (only `backtrack`, which presses `Alt+ArrowLeft`, and the history notice -- read by the actor on the very next call -- actually change what happens); adding one was judged out of scope beyond what "make coping switch to explore, backtrack or abandon" asks for, since the persona-visible notice is already the primary lever on the next real click and a new director-side branch for `explore` specifically would be a larger, less-verifiable change on top of an already multi-part item. Sixteen new Node tests: `test/loopDetector.test.js` (new, 10 -- `actionKey`'s fallback, the repeat threshold firing and growing, a different control in between not resetting the count, strict-alternation's exact shape rejecting `A,B,C,B` and `A,A,A`, the bounded window aging an old occurrence out, `loopNotice`'s wording, and the full real-sequence regression above); `test/personaDirector.test.js` (+3 -- `outcomeEvent`'s label argument and its two-argument fallback directly, three different refs recognised as one repeat with `repeatedEventCounts["CLICK:Pricing"]` confirmed 3 in the run's own final state, and an across-refs alternation confirmed both as a recorded `persona.loop` event and in the next actor call's own `history`); `test/behavior.test.js` (+3 -- no-context regression guard, the boost's exact six-term formula under both trigger conditions with the real leader flip away from a `seek_help`/`impulsive_retry` tie, and the composition-with-JRN-1 case proving the loop boost adds to the tolerance-crossing boost rather than replacing or diluting it). Full regression: 312 Node tests passing (296 + these 16), 540 Python tests passing / 3 skipped / 3 deselected (Node-only change; both suites checked per this session's standing discipline). |
| **JRN-3** | Make the adherence gate a gate. After its attempts are used up with a score below threshold, pick a coping action, not the rejected action. Give the judge the target's label and box, not only its ref. Then cut its cost: skip it when the action matches the persona's stated plan, or give it a cheaper per-role model through `/webui`. | 2d: 3 actions scored below threshold (3, 4, 0); a matching `persona.pointer` event confirms 2 of the 3 executed anyway (`e367` at 166740ms, `e3` at 212500ms), the 3rd (`e367` at 196575ms) has no pointer event within 5s either way, so `measure.py` counts it as unconfirmed rather than assumed — `e367` was judged "unrelated" while it was the Pricing link; 2i (47% of model wall) | Executed actions below threshold = 0 (measure.py's `executed_actions_below_threshold`). No objection names a bare ref. Adherence share ≤ 25%. |
| | **Done on the first two parts; the cost-cutting third is explicitly not attempted, for a stated reason below.** `AdherenceGate.settle()` (adherence.js) already returned the last, most-criticised attempt when nothing passed -- correct, TinyTroupe's own choice, documented on the method: "refusing to act is not something a person does." The actual bug was one level up: `run()` (personaDirector.js) used `settled.decision` unconditionally, never reading `settled.adherence.passed`, so the rejected action reached `perform()` regardless -- exactly what a live run showed happening twice, confirmed by a matching `persona.pointer` event. `settle()`'s own contract is untouched; `run()` now checks `settled.adherence.passed === false` (`gateExhausted`) and, when true, never calls `perform()` on that decision. **What replaces it is sampled, not fixed, and deliberately never touches `reduceState`.** `sampleCoping(controller.profile, controller.state, {taskImportance:0.6}, controller.random)` is called read-only -- its result is used to decide what happens, never fed through `apply()` -- because the gate failing to find an in-character action is the simulation harness's own limit, not the page disappointing anyone, and running it through the state reducer would inflate frustration/confusion for a reason that has nothing to do with the product being tested, contaminating the very trajectory numbers SEC-2 and JRN-1 depend on. Only `backtrack` gets a distinct response, because it already has one, real and safe: `browser.press("Alt+ArrowLeft")`. Every other sampled type -- including `abandon`, deliberately: ending the run because its own proposals kept missing this person is not a reason the run itself should end -- becomes what `reread` already means in this file: look again, decide fresh next turn, recorded in the persona's own history as `"thought about it, but that did not sound like you -- you looked again instead"` (the same read-on-the-next-turn channel JRN-2's loop notices use). **The label fix, verified against the exact diagnosed defect.** `actionBrief(decision, label)` (adherence.js) renders `the "Pricing"` instead of a bare ref when a label is available, falling back to the ref exactly as every pre-existing call already did; `AdherenceGate.settle(profile, decision, regenerate, nameFor)` takes an optional per-attempt resolver, called fresh for every regeneration (not once for the whole gate call), because a regenerated action can name a different control than the one just rejected. `personaDirector.js` passes `(target) => nameOf(target, perception)`, built fresh each step since `perception` is this step's own look, not a value the gate could hold across steps. A dedicated test (`test/adherence.test.js`) reconstructs the exact live shape -- a judge asked to score `e367` -- and confirms the rendered prompt now reads `the "Pricing"` and never contains `e367` at all. **The box, scoped down from the original one-line ask.** No existing consumer (checked: `report_service/*.py`, `apps/api/*.py`, `scripts/cycle/measure.py`) reads a box off adherence data, and no other prompt-builder in this codebase (personaActor.js's acting or reflection prompts) embeds raw coordinates in text a judge reasons over -- boxes are for visual crops, not textual judgement. Read literally anyway, minimally: `targetBox` (already computed via `boxOf()` for the expectation event, now computed once and reused) is attached to the recorded `persona.adherence` event alongside `targetLabel`, so a rejected action carries real evidence of where it was aimed, without inventing prompt text nothing would act on. **A real defect found by testing this against a real scripted run, not assumed correct from reading the diff.** Building an integration test surfaced that a rejected `DONE`/`GIVE_UP` now hit the same `gateExhausted` path as any other action -- meaning a harsh judge finding some small wording flaw in an ending could trap a persona who had already decided to leave, looping "look again" for the rest of the step budget. This risk did not exist before this item, because the old code ignored `passed` and let a rejected DONE through anyway; making rejection actually block something (the whole point of this item) created it. Fixed by resolving `endsRun = proposed.action?.type === "DONE" || proposed.action?.type === "GIVE_UP"` before the gate is even called, and skipping `gate.settle()` entirely for those two types -- which is also real, if narrow, cost-cutting: one fewer judge call for every ending action, on the same footing as this item's own third clause. **The third clause -- "skip it when the action matches the persona's stated plan," or a cheaper per-role model through `/webui` -- is left open, on purpose, not silently dropped.** Neither reading was implemented: "matches the persona's stated plan" has no single unambiguous referent in this codebase (no field named a "plan"; candidate readings -- matching a stated task, matching the prior turn's expectation, exempting low-risk action types -- were each considered and none was clearly what was meant, and guessing wrong here risks silently under-judging actions that should be checked, which is a worse failure than leaving the question open); the cheaper-model route needs a webui-configurable model role distinct from the existing `reflectModel`/`JOURNEY_REFLECT_MODEL` (already used for `judgeAdherence`, confirmed by reading `personaActor.js`'s `llmActor`), which is cross-cutting UI/config surface outside this lane's node-only file ownership. **`measure.py`'s own `executed_below_threshold` (RUN-1, confirmed by reading it rather than assumed) needs no change.** It already detects exactly this defect's signature -- a `persona.adherence` event marked `passed: false` matched to a `persona.pointer` event on the same target within 5 seconds -- and that signature structurally cannot occur again: `perform()`, which is what emits `persona.pointer`, is never reached for a `gateExhausted` decision. Whether a live cohort actually now scores 0 is RUN-2/RUN-6's to show, same as every other live-acceptance number this session states rather than claims. Eight new tests: `test/adherence.test.js` (+4 -- `actionBrief`'s label rendering and ref fallback, the judge prompt built from a resolved label with the ref confirmed absent, `nameFor` called fresh per attempt with two different labels observed across one gate call, and the no-resolver backward-compatibility case); `test/personaDirector.test.js` (+4, integration-level -- a rejected action never reaching `perform()` with the persona told in its own history, the judge's prompt text confirmed free of the raw ref end to end, `DONE`/`GIVE_UP` confirmed to reach zero judge calls for both ending types, and a fully deterministic case, seed 5, where one real failing click builds real state and the second action's rejection is replaced by a `sampleCoping` result that presses back rather than clicking the rejected target -- found empirically against the real sampler, the same way every seed-pinned test this session used). **Two of these were proven to actually catch the bug, not just pass by construction**: reverting `endsRun` to `false` failed 3 tests (the DONE/GIVE_UP exemption test directly, plus two others as a side effect of their own scripts ending in a now-gated DONE); separately reverting `gateExhausted` to `false` (with `endsRun` intact) failed the 2 tests specific to the core fix. Full regression: 320 Node tests passing (312 + these 8, across the two files), 540 Python tests passing / 3 skipped / 3 deselected (Node-only change; both suites checked per this session's standing discipline). |
| **JRN-4** | Name why a run ended. `journey.ending.reason` ∈ {completed, gave_up, budget, diagnostic}. `budget` is reported as a harness limit, not a verdict about the page. This is K1's change, and SEC-1 consumes it. | 2b; worksheet: 11 of 12 inconclusive runs ended exactly at budget | No usability finding comes from a `budget` ending. |
| **JRN-5** | The two CAP-0 siblings, carried over. Check agent-browser's `scroll` semantics on 0.31.1 in a live session (RUN-2 makes that cheap), then skip scrolling to an offset already held. Detect a click that produces no perceived change (the billing toggle). | Worksheet: `SCROLL:600` × 9 | Both occur 0 times on `taoshq.com`. |
| **JRN-6** | End the run on `GIVE_UP`. The worksheet trace has two actions after a give-up. | Worksheet trace | A test proves it, and it holds live. |
| **JRN-7** | D8, waiting. Measure page response latency per action (navigation start to settled) and emit `persona.wait` {measuredMs, toleranceMs}. RPT-4 found that no real latency is recorded today. | RPT-4's stated gap | The event is present on every action. FND-11 consumes it. |
| **JRN-8** | D10 and D1 task shapes. Add "submit something invalid" inside `safety.js`'s destructive-action rules. Add "continue into what the first flow opens". | Audit D1 (critical), D10 | Each shape produces at least one finding class on the benchmark set. |

### L2 · Perception and evidence capture (`EVD`)

**Owns:** `services/perception_service/**`, and `services/journey-worker/node/src/{perception,revealKeeper,cursorKeeper,viewportStream,agentBrowser,evidence,physical}.js`.
**Produces:** K1 (perception fields). **Inner loop:** `pytest tests/contract/test_perception*.py`, plus the snapshot's crops as fixtures.

| item | what | evidence | done when |
|---|---|---|---|
| **EVD-1** | Close the no-ink gap. A region whose ratio is below about 1.2 and which holds no glyph-shaped ink must be flagged `nothingDrawn`, even on a patterned background. Add the "Video" and "Italiano" crops as fixtures, since they are the counter-examples the current thresholds miss. | 2a | All 4 of the snapshot's "Fails" findings become "Declared but not drawn" on replay. The false-contrast metric is 0 live. |
| **EVD-2** | Fill the empty channels. Wire journeytest-core's `snapshots`, `console`, `network`, `uiChanges` and `videoClips`, or record for each why it is unavailable. | 2h | Each list is non-empty, or carries a stated reason. §30.9 can be rated met. |
| **EVD-3** | Pointer (#22, carried). On this run it was 10 of 10. In cycle 51, 4 events were unmeasured, all on the toggle `e17`/`e18`. Check it on `taoshq.com`. Test whether the scatter model does anything (0 misses in 17 clicks). | 2e; worksheet | ≥ 95% measured on both targets. The scatter's effect is stated. |
| **EVD-4** | Refusals. Once the noise floor exists, look at the "look after acting" refusals (5 of 13 in cycle 51). | Worksheet | Refusals are below the floor's minimum on `taoshq.com`. |
| **EVD-5** | D4 fields. Have the walk emit `tag`, `headingLevel`, `alt`, `labelFor` and `focusVisible`. RPT-4 declined four checks because these fields do not exist. | RPT-4's stated gap | The fields are present in K1. FND-8 consumes them. |
| **EVD-6** | C4 fields. Thread `fontPx`, `color` and `radius` from the perception candidate walk onto snapshot elements. RPT-5 had to sample pixels instead. | RPT-5's deviation | The redesign prompt receives measured styles, not only sampled pixels. |
| **EVD-7** | Cursor overlay. `effective: false` because 0.31.1 runs no init scripts. Re-check when the pin moves. Until then, the viewer draws the pointer from the timeline. | `cursorOverlay` in the snapshot | The recording shows a pointer. |
| **EVD-8** | Not from the original audit -- found this session, live, not in a fixture. Occlusion-aware perception: a persistent modal/overlay covers background elements the walk still reports as present, at their original document position. The perception service is then asked to verify ink for elements nothing painted there -- the modal did, on top -- and every region reads "no ink at all"; retrying does nothing, because the modal is not a transient state. | A live run against `https://open-design.ai/` (a "Download OpenDesign Desktop" modal): `run_diagnostics`, `"Part of this run was made without eyesight"`, `"88 of 88 regions... had no ink in them at all... still, after 3 attempts"`, steps 3-6, two scroll positions | An element covered by something outside its own subtree is excluded from the walk; an element whose own descendant, or itself, is the topmost thing at its centre is not. |
| | **Done.** `WALK` (`services/journey-worker/node/src/perception.js`) gains one more guard in `push()`, after the existing CSS-visibility check and before an element is kept: `document.elementFromPoint` at the element's own centre (clamped into the viewport, so an element straddling the edge -- already known to be at least partly on screen -- is never asked about a point outside the window, which returns `null` and would read as "nothing on top of it" for the wrong reason) -- the same per-point check `WHAT_IS_UNDER_THE_PIXELS` already makes at three fixed points to tell a blank capture from a blank page, applied per element during the walk itself. `top !== node && !node.contains(top)`: an element is its own answer, or its own descendant is (a `<p>`'s centre landing on an inline `<b>` inside it is not occlusion) -- only something genuinely outside the element's own subtree covers it. Occluded elements are dropped from the walk's own output, joining `visibility:hidden`/`display:none`/`opacity:0` as one more reason an element is not really there, rather than flagged and kept -- consistent with how those three already work, and avoiding a wider plumbing change to every downstream reader of `elements`. **Verified against a real browser, not by inspection.** `WALK` only ever runs inside one (agent-browser's `eval`), and this suite is deliberately dependency-free of both agent-browser and a browser engine (package.json's own "no npm ci" reasoning) -- so the actual shipped `WALK` source was extracted verbatim and executed in a real, pinned Chromium (`/opt/pw-browsers`, via a one-off Python/Playwright script, not a new project dependency) against four constructed pages: an ordinary unoccluded paragraph (kept); the exact production shape, a `position:fixed` modal over background text (the background paragraph excluded; the modal's own heading, body text and "Keep browsing" button all correctly kept); a container whose own centre point resolves to its nested `<button>` (the button kept, not excluded by its own parent); a wide paragraph with only its left edge covered by an unrelated badge, its centre still clear (kept). All four came back exactly as expected. Committed as five regex assertions against the real `WALK` source (`test/perception.test.js`, matching this file's own established pattern for testing browser-`eval` strings it cannot execute directly) rather than a new Playwright test dependency, which would be a materially larger, unrequested change to this package's CI footprint for one check. Full regression: 321 Node tests passing (320 + this 1), 545 Python tests passing / 2 skipped / 3 deselected (Node-only change; both suites checked per standing discipline -- the skip count moved from 3 to 2 between sessions for reasons unrelated to this change, not investigated further since nothing failed). **Then confirmed on the deployed Space, against the real defect, not only against constructed pages.** Redeployed to `Leon4gr45/aux-synthetic-ux-demo` (commit `784bb54`) and re-ran the same live journey -- freellmapi/auto, the bundled Friedrich Wolf example persona, `https://open-design.ai/` -- that originally surfaced this defect. The same "Download OpenDesign Desktop" modal appeared again (`critical_pain_points` still names "Close download prompt button (e1)" and "Keep browsing button (e4)"), so this is the same failure condition, not its absence. `run_diagnostics` came back `[]`: no "made without eyesight," no 88-region blackout. The one remaining "no ink" finding is a single `[info]`-severity, 89x33-region item with an honest alternate explanation offered ("likeliest explanation is a capture taken while the element was still animating in"), not a systemic diagnostic -- the shape a healthy report gives an isolated case, not a symptom of the fix under- or over-excluding. |

### L3 · Findings: producers and judgement (`FND`)

**Owns:** `services/report_service/findings/**` and `media.py` (after RUN-0), `services/eyeson-worker/**`, `services/knowledge-service/**`.
**Consumes:** K1. **Produces:** K2, K6. **Inner loop:** `replay_report.py last_runs/` plus `tests/replay/`.

| item | what | evidence | done when |
|---|---|---|---|
| **FND-1** | Two guards on the report side. (1) Never title a finding "Fails" below a ratio of 1.2 unless ink is verified. This protects the report even if EVD-1 regresses. (2) Group findings from one component (four language-switcher entries) into one finding with `instances[]`. | 2a | False contrast = 0 on replay. One component gives one finding. |
| | **Done.** `_unreadable_finding()` (`services/report_service/assembler.py`) gains a second early return, between the existing `nothingDrawn` branch and the `fails_wcag` branch: when `ratio < 1.2` (`_LOW_RATIO_UNVERIFIED_MAX`) and the element's own `ink` reading is below `0.005` (`_INK_VERIFIED_MIN` — not invented; it is `legibility()`'s own bar for counting a region as text, `perception_service/optics.py:306`), the finding is titled "Contrast measured, ink not confirmed" at `info` severity with no ratio claimed, instead of "Fails WCAG AA contrast" at `high`. Verified against the real trap: `nothingDrawn`'s own gate needs *both* internal and edge contrast under 0.02, and the live "Video" element that produced this bug has internal contrast 0.6941 (a real, non-flat background pattern) with ink 0.0015 — `nothingDrawn` correctly does not fire on it, and this guard is the reason a low ratio still does not become a claim. `_fold_unverified_contrast()` (new, paired with the existing `_fold_undrawn`, same `_UNDRAWN_WORTH_NAMING`-style threshold as its own `_UNVERIFIED_CONTRAST_WORTH_NAMING = 3`) groups more than 3 such findings into one, with each instance's name/box/ratio/ink in `instances[]` — on `last_runs/`, this turns the snapshot's four false "Fails" findings into one info-severity finding, `instances` length 4. **Found while writing the first version and fixed, not left for someone else to hit:** the grouped finding's summary, first drafted close to `_fold_undrawn`'s own wording, scored 0.20 on `_merge_similar_findings`' 0.18 prose-similarity gate and was silently folded *into* "elements were declared and not drawn," losing it entirely — caught by running the fix against `last_runs/`, not by inspection, since neither finding's own test exercises the two together. Rewritten to score 0.03. Fourteen tests exercise the boundary from both sides (`tests/contract/test_control_plane.py`): the live "Video" shape reclassified, ink exactly at the floor and ratio exactly at 1.2 both still filing as real defects, the fold at 4 instances and its own no-fold-below-3 case, no leaked `_unverifiedRatio`/`_unverifiedInk` temp fields, and (`tests/contract/test_replay_report.py`) that replaying `last_runs/` through today's code retires all four false titles and produces the one grouped finding — `assemble_report` is shared, live code, so this is not only a live-cycle fix but a correction to how the *existing* snapshot's evidence reads today. Full regression: 516 Python tests passing (same 3 baseline failures by name), 292 Node tests unaffected (Python-only change). |
| **FND-2** | Judge severity instead of assigning it (§53.2 #3, B7). Judge it from whether the finding blocked a task, the affect change at that step, how many personas hit it, and whether the control was on the task path. The executive summary's "one thing to change" is then the finding with the highest judged impact. | 2a: a "Video" label that nobody needed leads the report | The summary's lead finding sits on the task path. The severity derivation prints real inputs. |
| | **Done, scoped down from "judge every builder's severity" to what could be verified against real data and did not risk diluting six builders' own, already-calibrated rules.** The "Video" instance of this bug is FND-1's (already demoted to info); what was left, checked by reading every finding builder (`_pain_points_from_journeys`, `_pain_points_from_perception`, `_pain_points_from_expectations`, `_grouped_controls_with_differing_actions`, `_small_touch_targets`, all five carrying `runId`; only the vision critique's cross-persona root-cause synthesis does not), was that `_executive_summary`'s own "worst" selection was `blocking[0]` -- whichever high/critical finding happened to build first, which under replay is not even chronological (`step` does not survive the screenshot remap, SEC-5's own documented gap). New `_highest_impact()` ranks by `(_SEVERITY_RANK, affectedPersonas, taskBlocked)`, the exact tuple `_impact_analysis`'s own top-10 already uses plus one new tiebreaker, so the two views of "what matters" in one report can never disagree. New `_attach_task_blocked()` sets `finding["taskBlocked"]` from the *same* definition `_journey_outcome`'s own `taskSuccess` already uses (`verdict.status == "passed"`), read rather than recomputed; absent (not `False`) on a finding with no resolvable `runId`, matching this session's "absence of measurement" discipline. Severity *labels* are unchanged -- `_broken_promise_finding` already judged from a real frustration-cost basis (`cost`, `group["cost"] += max(0, frustration - previous)`, read from the affect trace at that exact step -- signal 2 of spec.md §53.2 #3's three) and persona reach (signal 3); adding an unverified escalation policy on top, with only one real (single-run, always-`taskBlocked=True`) data point to check it against, was judged riskier than it was worth. "On the task path" (element-level `goalAffinity`) is not attempted: it exists in perception data, not in the timeline `_pain_points_from_expectations` walks, and threading it through is a real, separate plumbing change. Verified against `last_runs/`: `_highest_impact` picks "Promised more than it did: Pricing" (unchanged from before, now for a stated, checkable reason, not by list-order accident) and a constructed two-run case (one passed, one failed, tied severity and reach) proves the ranking actually changes the outcome when it should. Four new tests (`tests/contract/test_control_plane.py`): `_attach_task_blocked`'s pass/fail/no-runId/unresolvable-runId cases, `_highest_impact`'s three-tier ranking, the two-run tie-break end to end through `assemble_report`, and `_broken_promise_finding`'s `taskBlocked` + existing `claimedImpact` read together. Full regression: 544 Python tests passing (540 + these 4), 320 Node tests unaffected (Python-only change). |
| **FND-3** | Per-finding `confidence` (B8, and A10's residue). Derive it from capture trust, persona count, `reproducedIn`, and whether the run completed. | 2f: 0/14 | 13/13 site findings carry it. |
| | **Done, and pulled forward from its own slot because SEC-3's ranking formula needs a real number to multiply by.** `_finding_confidence`/`_attach_confidence` (`services/report_service/assembler.py`) compute all four named inputs from fields already on every finding by this point in the pipeline, never asserted: capture trust (1.0 a real "as they saw it" capture, 0.7 a clean screenshot, 0.4 neither -- still real evidence, just not visual); persona agreement, `affectedPersonas` against *this cohort's own size* rather than an absolute count, so a single-persona cohort where that one persona hit it reads as full agreement, not weak evidence; `reproducedIn` (BE-5's own field, already set on every finding by `_merge_similar_findings`, which runs first); and whether the run completed -- read from `harnessError` (JRN-4/RUN-3), not from FND-2's `taskBlocked`, because those answer different questions: a persona can fail a real task on a run that otherwise finished cleanly, and that failure does not make the finding it produced any less trustworthy. Equally weighted, since spec.md ranks the four relative to each other in name only. Cross-persona vision-synthesis findings (no single `runId`) hold the fourth input neutral rather than penalised. Five new tests in `tests/contract/test_control_plane.py`, including the three-scenario direct check (`test_finding_confidence_uses_all_four_named_inputs`) hand-computed against the real formula, not just asserted against whatever the code returns. |
| **FND-4** | Complete alternatives (C5, C6, C7). Give every site finding at least one alternative, each with an effort class of copy, layout or behaviour, plus one sentence of trade-off. | 2f: 5/14, effort on 1 | Every fill rate for alternatives is 100%. |
| | **Done, hand-grounded where a finding builder already had the data to ground it, backed by a uniform safety net everywhere else.** `_committed_recommendation`'s existing alternative (`_broken_promise_finding`'s) gains `effort`/`tradeOff`: `copy` when the commit is to build the missing behaviour (the alternative is always the reword not taken), `behaviour` when the commit is to reword (the alternative is always the behaviour change not taken) -- verified against both branches directly, since `silent` is derived from the gap quote's own words (`_DID_NOTHING`), not a flag a test can just set. All five `_unreadable_finding` branches and `_never_looked_at_finding` gain a hand-written alternative grounded in that finding's own real data (WCAG AA's large-text exception as a second lever on the same guideline; an opt-in high-contrast mode instead of changing the default; a scan-triggered nudge instead of repositioning), matching FND-9's already-shipped standard for recommendations, extended here to alternatives. The two harness-status placeholders ("No pain points detected" / "Journey ended early") get a real alternative each rather than being left as an FND-4 gap because they read as "nothing to fix." **The safety net, for sources this codebase does not own the prose of:** `_ensure_alternatives` (called once, after the merge) fills any finding with no `alternatives` via `_fallback_alternative` -- a universal, honestly-framed option (ship a smaller mitigation now, treat the full fix as a follow-up) grounded in that finding's own title/recommendation, never a static template -- and coerces every alternative's `effort` to a valid value via `_coerce_effort`/`_sniff_effort` (content classification: label/reword/wording → copy; contrast/size/position/colour → layout; default behaviour, stated as a default rather than a guess abstained from) and fills any missing `tradeOff` via `_synthesize_trade_off`. **A real vocabulary collision found and resolved, not assumed compatible.** `services/eyeson-worker/node/src/visionCritique.js` already validates its own alternatives' `effort` against `low`/`medium`/`high` -- a magnitude scale, answering "how large," never `{copy,layout,behaviour}` -- FND-4's own taxonomy, answering "what kind." Read directly before assuming otherwise, not inferred from REPORT_CRITERIA.md's looser gloss ("effort (low/medium/high)"), which describes that same worker output pre-FND-4. `_coerce_effort` re-classifies it from the alternative's own `proposedChange` text rather than trusting the mismatched vocabulary through, and `_synthesize_trade_off` keeps the vision model's own magnitude estimate rather than silently discarding it, folded into the trade-off sentence it writes. `scripts/cycle/measure.py`'s `_core_ok` (section 5) now also requires `alternatives`, the same standing as the evidence and recommendation checks already there, per spec.md §30.5's own bullet list. Eight new tests in `tests/contract/test_control_plane.py`: the branch-dependent broken-promise check above, `_sniff_effort`'s content classification, `_coerce_effort`'s vision-vocabulary reclassification, `_fallback_alternative` grounded with and without a source recommendation, `_ensure_alternatives`'s own fill-every-gap invariant, and an end-to-end test mixing a hand-grounded source (`_broken_promise_finding`) with a fallback-only source (`_pain_points_from_journeys`' `uxFindings`) through the real `assemble_report` pipeline. **Proven to catch the defect, not just pass by construction:** both the direct `_ensure_alternatives` test and the end-to-end test fail against the pre-fix tree (reverted `assembler.py`/`measure.py`), the latter naming the exact finding left incomplete (`'Silent submit button' has no alternatives`). |
| **FND-5** | Reconcile praise and fault. A control cannot be both preserved and faulted unless the report says why ("works as a call to action; does not do what it says"). | 2g | Unreconciled contradictions = 0. |
| **FND-6** | Quote joins. Reject contentless affect lines as `personaEvidence`, and prefer the nearest moment that mentions the element. | 2f: *"You are calm."* × 2 | Contentless quotes = 0. |
| **FND-7** | Vision critique #39, carried. A claim about something the run never looked at must not pass the contradiction guard silently. | Worksheet §3 | A test proves the refusal. |
| **FND-8** | Deterministic sweep, the D4 remainder: heading order, alt text, form labels, focus visibility. It needs EVD-5. | RPT-4 | Each check runs on every capture. |
| **FND-9** | Recommendations written for the page, not from a template (§53.2 #4). This applies to the perception classes, for example *"Worth a look if it is important; not yet evidence of a problem."* | 2f | No recommendation would read the same on another page. The RPT-1 acceptance test is extended to these classes. |
| **FND-10** | D3, locale mismatch: the page language differs from what is selected by default. It needs PSN-3. The snapshot's own site has a language switcher. | Audit D3 | The finding class exists and is tested. |
| **FND-11** | D8, a wait longer than this person tolerates. It needs JRN-7. | Audit D8 | The finding class exists and is tested. |
| **FND-12** | Record the vision cache (K6) so that RUN-3 can replay without calling the model. | RUN-3 | Replay makes no network calls. |

### L4 · Report contract, §29–§31 (`SEC`)

**Owns:** `services/report_service/sections/**`, `services/report_service/assemble.py`, `docs/contracts/ux-report.md`.
**Consumes:** K1, K2. **Produces:** K3. **Inner loop:** replay plus `tests/replay/`.

| item | what | evidence | done when |
|---|---|---|---|
| **SEC-1** | Separate run diagnostics. A `budget` ending (JRN-4) and "users could not finish" go to `run_diagnostics` and the scorecard, and never into `critical_pain_points`. | 2b | Run diagnostics among findings = 0. |
| | **Done, and wider than first scoped.** Two new small helpers in `services/report_service/helpers.py` — `step_budget(num_tasks)` (journeytest.js's own formula, `min(40, max(12, tasks*8))`), `_budget_hit_run_ids(journeys, num_tasks)` (a run is budget-hit when `verdict.status == "inconclusive"` and its action count meets the budget), `_is_budget_limited_finding(finding, budget_hit_run_ids)` — imported into `assemble_report`'s existing `run_diagnostics` split (`services/report_service/assembler.py`) alongside `_is_run_diagnostic`, so a budget-hit finding is filtered out at the same point, the same way, rather than a second parallel mechanism. **`scripts/cycle/measure.py` now imports all three from `helpers.py`** instead of keeping its own copy (RUN-1 had duplicated them) — the scorer and the fix can no longer disagree about what counts as budget-limited. **Found while wiring this up, not scoped in the original item: the same harness limit is reported twice.** JourneyTest's own verdict carries `tasks-completed: not-met` (the `criteria` bucket, "Users could not finish the tasks they came to do") *and* a `blockers` bucket entry with `id: "persona-stopped"` ("The visitor did not get there") — same run, same cause, two buckets. The live snapshot's report only shows the first because `_merge_similar_findings` (unrelated, pre-existing code) had already folded the second into it (`mergedFrom: ["The visitor did not get there"]`) — before SEC-1, both were real findings and merged; after, one is filtered out before the merge runs, and the other was found standing alone in `critical_pain_points` on the first replay against `last_runs/`, not by inspection. Fixed by threading the blocker's own `id` onto the finding as `blockerId` (only on the `blockers` bucket; `_pain_points_from_journeys`, `services/report_service/assembler.py`) and widening `_is_budget_limited_finding` to match either shape, scoped to `not-met`/`persona-stopped` specifically — `criterionResult: "blocked"` (the run couldn't even assess the criterion) and a genuine `GIVE_UP` (which ends a run `"failed"`, not `"inconclusive"`) are both left as real findings, and a test pins each boundary. Twenty new tests (`tests/contract/test_control_plane.py`): both shapes routed to diagnostics together, the `blocked`-criterion and under-budget-but-inconclusive and genuine-give-up cases all still filing as real findings (the give-up case's own two titles still merge into one via the pre-existing, unrelated similarity logic — pinned as unaffected, not as a SEC-1 outcome), and `blockerId` never leaking onto a non-blocker finding. Two `tests/contract/test_replay_report.py` tests updated for the corrected replay output (assemble_report is shared code, so this fix also applies retroactively to `last_runs/`'s own evidence, same as FND-1). Full regression: 522 Python tests passing (same 3 baseline failures by name), 292 Node tests unaffected (Python-only change). |
| **SEC-2** | **The experience trajectory (§30.4), the one section that is missing.** For each run, emit a series of {step, videoTimeMs, frustration, confusion, trust, fatigue, effort, coping} from `persona.affect`, with each finding's step marked on it. Also fill `emotionalTrajectory` (§29). The data is already in every run: 10 points here. | REPORT_CRITERIA §4 | The section is present. PRS-1 renders it. |
| | **Done.** `ReportAssembler._experience_trajectory(journeys, findings, persona_names)` (new, `services/report_service/assembler.py`) reads every `persona.affect` event's own `data.state` directly — the behavior controller's own recorded numbers, never re-derived — into a per-run series: `step`, `elapsedMs`, `videoTimeMs`, `frustration`, `confusion`, `trust`, `fatigue`, `effort`, `cognitiveEffort`, `physicalEffort`, `consecutiveFailures`, `coping`, `abandoned`, `findingTitles`. Set on the report as top-level `experience_trajectory`, called right after `_order_by_step` so every finding's own `step` (SEC-5) is available for `findingTitles` — a point's `findingTitles` lists every finding whose `step` matches, the join a reader would otherwise do by hand between two lists. Verified end to end against the real, unmapped `last_runs/` journey (10 points, matching `docs/parallel-development-overview.md`'s own hand-written trajectory table exactly: frustration 0.13→1.00, confusion 0.21→1.00) and the finding cross-reference (step 1's point correctly lists all 5 findings whose screenshot resolved to step 1). **`effort`, one named stated interpretation, not spec.md's own field.** `state` tracks cognitive and physical effort separately (`behavior.js`); spec.md's §30.4 wording names one "effort" series. Reported as `max(cognitiveEffort, physicalEffort)`, both raw numbers kept alongside it so the collapse loses nothing. **`emotionalTrajectory` (§29's `UXRunAnalysis.emotionalTrajectory`), not separately added, stated rather than silently dropped.** §29's `UXRunAnalysis`/`uxAnalysis` wrapper (`behaviorSummary`/`emotionalTrajectory`/`painPoints`/`eyeson`/`alternatives`/`grounding`, nested under `RunResult`) does not exist anywhere in the shipped report schema — every real field is flat and top-level (`critical_pain_points`, `elements_to_preserve`, `impact_analysis`, ...), snake_case, and no consumer (report renderer, `measure.py`, any test) reads a nested `uxAnalysis` object. Adding a second, differently-shaped copy of the same trajectory under a wrapper nothing else in this tree uses would be inventing structure, not filling a gap; `experience_trajectory` follows the schema that actually ships. Twenty new tests: seven unit-level (`tests/contract/test_control_plane.py`) covering the direct read, the effort collapse (both present, one present, neither present), the finding cross-reference (matched and unmatched step), a run with no affect events correctly omitted, and the end-to-end field on a real finding; two `tests/contract/test_replay_report.py` tests pinning the exact numbers on `last_runs/` and the (SEC-5-consistent) empty `findingTitles` under replay's own path-remap limitation. Full regression: 534 Python tests passing (same 3 baseline failures by name), 292 Node tests unaffected (Python-only change). |
| **SEC-3** | Ranked alternatives (§30.7, C9). Aggregate across findings and rank by impact × personas × confidence ÷ effort. Print the rule. | REPORT_CRITERIA §7 | The section is present and ordered by the stated rule. |
| | **Done.** `_ranked_alternatives` (`services/report_service/assembler.py`) aggregates across every finding's `alternatives[]` -- not each finding's committed `recommendation`, which is this codebase's own name for the option *not* chosen (`_committed_recommendation`'s docstring) and the only one carrying a judged `effort` after FND-4 -- and ranks by impact x personas x confidence / effort. Impact is `_highest_impact`'s own severity judgement, rescaled to a strictly positive `_RANK_IMPACT_WEIGHT` (1-5): `_SEVERITY_RANK`'s existing -1 for `info` is correct for the max/tie-break comparison `_highest_impact` uses it for and would zero or invert a *multiplicative* score, which a rank is never asked to do, so this is a second, ranking-specific scale kept deliberately separate rather than repurposing the first one under it. Effort divides through `_RANK_EFFORT_WEIGHT` (copy=1, layout=2, behaviour=3), so a high-effort fix needs proportionally more impact, reach or confidence to outrank a cheap one. Wired into the report as `ranked_alternatives: {rule, items}` -- `rule` is the formula printed as a sentence, the literal ask, and each item carries the finding it came from plus its own score and inputs, so the order can be checked rather than trusted. `scripts/cycle/measure.py`'s own `report_contract_sections()` already keyed section 7 off `report.get("ranked_alternatives")` before this landed (read directly, confirming the field name rather than guessing it), so no scorer change was needed here -- only the field appearing flips it. **The golden invariant recomputed, not hand-edited.** `tests/replay/test_golden_invariants.py`'s `ASSERTED_CONTRACT` moves from `{5,2,2}` to `{6,1,2}` (section 7: partial -> met), read off a real re-run of `report_contract_sections()` against `replay_report.replay(last_runs)`, not asserted from the formula alone -- the full per-section dict was printed and checked before the pin was touched, confirming section 6 (eyeson UX review, absent under replay by design) is the only section the change could plausibly have disturbed and did not. Two new tests in `tests/contract/test_control_plane.py`: `_ranked_alternatives`'s own sort order and rule text, hand-computed against three findings spanning all three effort weights and an unclassified one falling back to the stated default; and the same end-to-end `assemble_report` test FND-4's row describes, which also asserts `ranked_alternatives`'s items are non-increasing and at least as many as the findings that produced them. Full regression: 553 Python tests passing (545 baseline + 8 new, across FND-3/FND-4/SEC-3), 3 pre-existing environmental failures unchanged (confirmed by running them against the unmodified tree first -- `Friedrich_Wolf.agent.json` and a model-providers check, neither touched by this work), 6 skipped (all environment-gated: dspy, HF OAuth, production stack, TinyTroupe acceptance -- none new), 321 Node tests unaffected (Python-only change). |
| **SEC-4** | Knowledge basis (§30.8). State the provider, whether it is configured, the corpus size, whether it was reachable this run, and how many references were used. | REPORT_CRITERIA §8 | A standalone status block. |
| **SEC-5** | Video timestamps (§30.5). Set `videoTimestampMs` and `step` from the capture event's own `videoTimeMs`. | 2f: 0/8 among site findings (9 findings carry `evidenceScreenshot`, one of them the misfiled diagnostic SEC-1 relocates), though the data is present | 8/8 filled. |
| | **Done, `videoTimestampMs` fully; `step` with a real, stated replay-only gap.** `ReportAssembler._screenshot_video_timestamps(journeys)` (new, `services/report_service/assembler.py`) builds `{runId: {screenshot path: videoTimeMs}}` from the two timeline event kinds that carry both: `browser.screenshot` (`data.path`) and `persona.perception` (`data.seenImage`, the persona-perceived variant — a different file). Verified against `last_runs/`: together they resolve all 6 kept screenshots (3 raw, 3 as-they-saw-it), no gaps. `_attach_video_timestamps` joins it onto every finding by `runId` + `evidenceScreenshot`/`screenshotRef`, called right after `_attach_verdict_screenshots` in `assemble_report` (needs the screenshot reference set first). First sighting wins on a re-read screenshot — the moment it was captured, not the last time a persona glanced at it again. `step` reuses `_finding_step_index()`, which already existed as a private sort key inside `_order_by_step`; that method now also assigns `finding["step"]` as a real field while it computes the same number, rather than computing it twice. Verified end to end (`ReportAssembler.assemble_report` on the real, unmapped `last_runs/` journey, not through replay — see below): `step == 1`, `videoTimestampMs == 10355` on a real finding. **On `last_runs/` via replay specifically, `videoTimestampMs` reaches 9/9 findings with a screenshot; `step` reaches 0/9 — a real, replay-only gap, found and documented while verifying, not silently accepted.** `build_screenshot_remap()` (RUN-3) renames every kept file to `<kind>__<artifact_id>.<ext>` (`last_runs/AGENTS.md`'s own convention), which destroys the leading step number `_finding_step_index` reads from the filename itself; `videoTimestampMs` survives because both sides of its lookup (the event's path, the finding's reference) get renamed *consistently*, so string equality still holds — a difference in *kind*, not degree, documented as category 6 in `replay_report.py`'s own docstring. Confirmed by running `assemble_report` directly on the original, unmapped journey (no local screenshot files there, so no crop — but the correct `step`). Fourteen new tests: four unit-level (`tests/contract/test_control_plane.py`) covering the join, the re-read-keeps-first-sighting rule, run-scoped matching (the same path on two different runs must never cross-match), and the end-to-end field on a real finding; one `tests/contract/test_replay_report.py` test pinning the replay-only gap explicitly rather than leaving it to be noticed by accident. Full regression: 527 Python tests passing (same 3 baseline failures by name), 292 Node tests unaffected (Python-only change). |
| **SEC-6** | Evidence language per claim (§31). Every statement carries `evidenceKind`, serialized and visible. | REPORT_CRITERIA §31 caveat | Four-way tagging on every claim. |
| **SEC-7** | Full evidence index (§30.9). An artifact manifest with resolved and unresolved counts (§53.2 #2). | 2h | Present. Unresolved = 0 or named. |
| **SEC-8** | Named journey-outcome counts (§30.3): errors, retries, backtracks, effort, drawn from coping decisions. | REPORT_CRITERIA §3 | Named fields, not implicit ones. |
| **SEC-9** | Executive summary (§30.1). State experience quality and completion or abandonment explicitly. The lead finding comes from FND-2. | 2a | Every §30.1 bullet is present. |
| | **Done.** All five §30.1 bullets are now explicit sentences in `_executive_summary`, each read from structured data already elsewhere in the report rather than re-derived: strongest pain point (FND-2's `_highest_impact`, unchanged placement) is immediately followed by strongest recommendation, read off that same finding's own `recommendation` field. Task outcome and completion/abandonment are one bullet -- "N of M persona(s) completed the task[; K walked away rather than finish it]" -- computed from `journey.verdict.status == "passed"` (`_journey_outcome`'s own `taskSuccess` definition) and, for the abandonment clause specifically, `experience_trajectory`'s last point's `abandoned` flag (JRN-1's own coping-model decision) -- deliberately *not* "did not pass", because a run that ran out of its step budget while still trying is a harness limit (SEC-1's own distinction) and conflating the two would restate, in one report, a defect SEC-1 exists to separate out elsewhere in it. Experience quality is the worst final frustration any persona actually reached (not an average, which would let one badly-hurt persona hide behind others), banded in the same plain words `affectInWords()` (personaActor.js) already uses for the persona's own prompt. `experience_trajectory` (SEC-2) is now computed once in `assemble_report` and passed into `_executive_summary` rather than built twice. Verified against `last_runs/`: `"0 of 1 persona completed the task. At its worst, the experience left a persona fed up (frustration 1.00 of 1.00)."` -- both numbers match the real recorded trajectory exactly (frustration 1.00 at the run's last step, confirmed independently during JRN-1's own work this session), and the abandonment clause correctly stays silent, because this real run's own `state.abandoned` was `false` -- it ran out of budget still trying, never sampled "abandon" (matching JRN-1's own finding that p(abandon) peaked at 0.033 pre-fix). `scripts/cycle/measure.py`'s `report_contract_sections()` upgraded from "met if non-empty" to checking all five bullets by the same fixed markers `_executive_summary` itself emits (legitimate here, unlike pattern-matching a model's free-form prose, because this pipeline controls its own wording) -- "No usability issues were identified" satisfies the pain-point and recommendation bullets vacuously, since a clean run has nothing to name. **A pinned number moved, correctly, not silently:** `tests/contract/test_measure.py::test_report_contract_is_computed_not_hand_rated` measures the *static* `last_runs/artifacts/ux_report__*.json` (generated before this landed), whose executive summary genuinely lacks all three new bullets -- updated from `met`/`(4,4,1)` to the honest `partial`/`(3,5,1)`, with a comment pointing at `tests/replay/test_golden_invariants.py` for the "met, on today's code" side of the same proof; that golden test's own pinned totals (met=5/partial=2/missing=2) needed no change, since section 1 was already counted "met" there under the old loose check and stays "met" under the new stricter one. Full regression: 544 Python tests passing (no new test count change from FND-2's four -- this item added sentences and a stricter scorer check, not new test functions of its own, verified instead through the existing FND-2/SEC-2/golden-invariant suites plus the one corrected pin above), 320 Node tests unaffected (Python-only change). |
| **SEC-10** | Thread persona-compile model usage into `model_usage`. This is BE-3's stated gap. | BE-3 | The generation cost appears in the report. |

### L5 · Presentation and craft (`PRS`)

**Owns:** `services/report_service/render/**`, `tests/contract/test_slide_deck_fits.py`, and the report-viewer parts of `apps/gradio/`.
**Consumes:** K3. **Inner loop:** replay, then render, then a Chromium fit test.

| item | what | criteria |
|---|---|---|
| **PRS-1** | A trajectory chart on the deck and the presentation. Finding markers use the same numbers as the evidence. | §30.4 |
| **PRS-2** | Portable export. A print stylesheet that becomes a PDF, with a page break per slide; the live redesign falls back to its screenshot. This is at the top of the previous plan's deferred list. | E12 |
| **PRS-3** | A "who we sent" slide, contrasting personas on the traits that mattered. | G1, B5 |
| **PRS-4** | Stamp each evidence figure with its step and video time, linked to the recording at that moment. | A4 |
| **PRS-5** | The cosmetic batch: sub-numbering suppressed below two findings, method and version as author with the job id, one display face and one body face, one hue per flow. | E2, E4, E9, E10 |
| **PRS-6** | A one-page summary for whoever commissioned the run. | F4 |
| **PRS-7** | Switching between User Journey and UX Feedback keeps the selected step (§48.13). Verify it in the Gradio viewer. | §28, §48 |

### L6 · Scale, repeats and the closed loop (`SCL`)

**Owns:** `apps/api/executor.py` (the run half, after RUN-0) and job types.
**Produces:** K5.

| item | what | criteria | done when |
|---|---|---|---|
| **SCL-1** | Repeat-seed dispatch, BE-5's residue. Expand to one entry per run (`persona_id#seed`). Re-key every structure that assumes one journey per persona (`thoughts_by_persona`, `mental_models_by_persona`, the scorecard). | A8, G6, H5 | A 3×2 cohort overwrites no data (tested), and `reproducedIn` ≥ 2 occurs. |
| **SCL-2** | Make "reproduced" a class of its own: findings seen in at least 2 of 2 runs carry more weight in FND-3. | G6, B8 | The class is visible in the report. |
| **SCL-3** | A `retest` job type (C8, §34, RPT-3's remainder). Re-run the same persona, seed and task against the fixed or same URL. Link the result with `AlternativeExperimentLink` and report whether the fix held. | C8, §34 | One retest reports held or not held. |
| **SCL-4** | Validate a prototype. Re-run the personas against the redesign HTML (`ui.prototype`). | §34 | The first validated alternative, with its lineage. |
| **SCL-5** | Cohorts of 5 or more, and aggregation across sites, within the provider concurrency budget. | H3, §11 | A 5-persona cohort runs within the time bound in §5. |

### L7 · Reach: signed-in, developer mode, role hats (`HAT`)

**Owns:** `apps/webui/**`, `apps/api/{hats,credentials}.py`, `apps/gradio/credentials_panel.py`, and `services/journey-worker/node/src/{developerTool,loginCapture,takeover,safety}.js`. The front-tab links in `app.py` are an ordinary merge with L9.

| item | what | done when |
|---|---|---|
| **HAT-1** | The first signed-in run end to end, on RUN-7's operator-controlled site. `AGENTS.md` says this has never been exercised live. | CAP-4's done-when holds on real output: no account identifier appears in text or evidence. |
| **HAT-2** | The first developer-mode cycle. The integrator hat runs against `open-design.ai`, which offers a desktop download. The persona clicked download three times expecting one, and FETCH plus INSPECT can check whether a download arrives. | A finding with the command transcript attached. |
| **HAT-3** | A capability manifest per finding: which hat and faculties produced it (CAP-2's remainder). | Present on every finding. |
| **HAT-4** | Hat CRUD in `/webui`, one button per preset hat, and wire the `#developer` fragment (CAP-3's remainder). | A hat created in the UI mounts its tool in a run. |
| **HAT-5** | Click through the takeover controls in a real browser. Forward pointer movement only after a challenge is actually rejected and the jump is identified as the cause. | Recorded in `AGENTS.md`. |

### L8 · Persona fidelity (`PSN`)

**Owns:** `services/persona_service/**`, `scripts/{actor_program,build_actor_corpus,compile_actor,generate_persona_pool_batch}.py`, and persona fixtures.

| item | what | done when |
|---|---|---|
| **PSN-1** | Run the GEPA compile of the actor program on a corpus (§53.2 #1). RUN-2 makes collecting 20 visits across 5 personas a matter of a command. | Before and after figures for the gate's regeneration rate. |
| **PSN-2** | Record Stage 2 acceptance formally. The snapshot shows live TinyTroupe generation (`tinytroupe@a6244b3`). | `docs/stage-2-audit.md` closed. |
| **PSN-3** | A persona locale attribute (D3). | It reaches K1 and FND-10. |
| **PSN-4** | The three pinned benchmark personas for RUN-7, deliberately spread in patience, persistence and acuity, so that trait linkage (B5) has something to contrast. | Pinned artifacts committed as fixtures. |
| **PSN-5** | The evaluator and compliance-reader stances as persona profiles. CAP-6 routed them here. | Two profiles, with a cycle each. |
| **PSN-6** | The DSPy parity report (100 human-reviewed candidates). Stays gated as before. | Approved or rejected on record. |

### L9 · Platform, reliability and cost (`OPS`)

**Owns:** `spaces/**`, `Dockerfile`, `docker-compose.yml`, `infrastructure/**`, `scripts/deploy_hf_space.py`, `apps/api/model_*.py`, and the readiness and startup parts of `app.py`.

| item | what | done when |
|---|---|---|
| **OPS-1** | Persistent storage: a `/data` mount, or pushing each run's artifacts to an HF dataset. Without it, the scoreboard's history does not survive a restart. | 2j's warning is gone. |
| **OPS-2** | Show the provider fallback live (H4). Force the primary provider to fail and read `served_by.movedFromPrimary`. | The report states which provider served the run. |
| **OPS-3** | Speed. Model choice per role (reflection and adherence) through `/webui`. Cohort concurrency tuned against `MAX_CONCURRENT_MODEL_CALLS`. | The cohort wall bound in §5 is met. |
| **OPS-4** | Stage 1 production-stack acceptance in a Docker runner, and HF workspace acceptance. These are carried from `AGENTS.md`. | Both recorded. |
| **OPS-5** | A cost figure per review: tokens × price per role (H2 made visible). | It appears on the method slide. |
| **OPS-6** | Clear the root clutter (`verify_*.py`, `test_*.py` at the root, Jules helpers). | The root holds only entry points. |

## 7. Order and concurrency

```
Wave 0, day one ─ RUN-0 alone in services/report_service and executor.py. Everything else below runs beside it:
                  RUN-1  RUN-7  RUN-8
                  JRN-1  JRN-2  JRN-3  JRN-4  JRN-6
                  EVD-1  EVD-2  EVD-3
                  HAT-1 (site setup)  PSN-4  OPS-1  OPS-2
Wave 1 ─ after RUN-0:  RUN-3  RUN-4  RUN-5   FND-1…6, 9, 12   SEC-1…10   PRS-2…7   SCL-1
Wave 2 ─ after RUN-2:  RUN-6 (noise floor)  JRN-5  EVD-4  HAT-2  PSN-1
Gated items:  FND-8 ← EVD-5   FND-10 ← PSN-3   FND-11 ← JRN-7   PRS-1 ← SEC-2
              SCL-2 ← SCL-1   SCL-3, SCL-4 ← SCL-1   FND-2 → SEC-9
```

Contract PRs for K1 to K6 are the only things that queue across lanes. They are
small and merge first.

**The cadence.**

| loop | trigger | time | what runs |
|---|---|---|---|
| inner | every save | seconds | lane unit tests, and a replay of `last_runs/` |
| PR | every push | minutes | full Python and Node suites, plus `tests/replay/` golden invariants (RUN-8) |
| outer | a merge wave, or on demand | 6–8 min | `run_cycle.py` over the benchmark set, then a scoreboard row |
| floor | weekly, or after a large merge | about 25 min | three same-commit cycles, then the noise floor re-checked |
| snapshot | after an outer loop that changed a metric beyond the floor | minutes | `refresh_last_runs.py`, and `REPORT_CRITERIA.md` re-rated from `measure.py` |

**The ten items with the most impact per effort, to start first:**

1. RUN-0, RUN-1 and RUN-3: every other lane's speed depends on them.
2. EVD-1 and FND-1: the report's lead finding is false.
3. SEC-1: a harness limit is reported as a usability fault.
4. JRN-1: abandoning is unreachable because of one overwritten line.
5. JRN-2 and JRN-3: loops, and a gate that does not gate, which costs 47% of model time.
6. SEC-2: the one missing §30 section, whose data is already recorded.
7. FND-2 and SEC-9: judged severity, so the summary leads with the right finding.
8. SEC-5: video timestamps, a join with data already present.
9. RUN-6: the noise floor, without which none of the above can be called better.
10. FND-4 and SEC-3: alternatives complete and ranked.

## 8. Every audit criterion, by lane

The audit's 68 criteria are shown with their standing in the previous plan's
appendix, updated against this snapshot. **held** means already strong, **closed**
means shipped, and **live-regressed** means shipped and contradicted by the
snapshot.

| | A · Evidence | | B · Root cause | | C · Recommendations | | D · Coverage |
|---|---|---|---|---|---|---|---|
| A1 | held · RUN-5 guards it | B1 | closed | C1 | closed (RPT-1) · FND-9 for the perception classes | D1 | JRN-8 |
| A2 | closed (scorecard `matched`) | B2 | closed (RPT-2) | C2 | closed (RPT-1) | D2 | HAT-1 |
| A3 | closed | B3 | closed (RPT-2) | C3 | closed (RPT-5) | D3 | PSN-3 → FND-10 |
| A4 | PRS-4 | B4 | closed (RPT-2) | C4 | partial · EVD-6 | D4 | partial · EVD-5 → FND-8; **live-regressed** 2a → EVD-1, FND-1 |
| A5 | closed · FND-7 | B5 | closed · PRS-3 | C5 | partial · FND-4 | D5 | held |
| A6 | closed · SEC-1 | B6 | partial: names the wording only · FND-9 | C6 | FND-4 | D6 | closed (RPT-4) |
| A7 | closed (RPT-4) | B7 | partial · FND-2 | C7 | FND-4 | D7 | closed (RPT-4) |
| A8 | SCL-1 | B8 | FND-3 | C8 | partial · SCL-3 | D8 | JRN-7 → FND-11 |
| A9 | closed (BE-3) | | | C9 | SEC-3 | D9 | partial · FND-5 |
| A10 | held · FND-3 | | | | | D10 | JRN-8 |

| | E · Craft | | F · Narrative | | G · Process | | H · Operational |
|---|---|---|---|---|---|---|---|
| E1 | held | F1 | closed · SEC-9 | G1 | PRS-3 | H1 | held |
| E2 | PRS-5 | F2 | closed | G2 | deferred (constrain task generation) | H2 | closed · OPS-5 |
| E3 | held | F3 | held | G3 | **live-regressed** 2b → SEC-1 | H3 | partial · SCL-5 |
| E4 | PRS-5 | F4 | PRS-6 | G4 | closed | H4 | closed (BE-1) · OPS-2 |
| E5 | closed | F5 | closed · FND-6 | G5 | held | H5 | SCL-1, FND-4 |
| E6 | closed | F6 | closed | G6 | SCL-1, SCL-2 | | |
| E7 | closed (RPT-5) | F7 | held | | | | |
| E8 | closed (RPT-2) | F8 | closed (RPT-6) | | | | |
| E9 | PRS-5 | | | | | | |
| E10 | PRS-5 | | | | | | |
| E11 | closed (RPT-6) | | | | | | |
| E12 | PRS-2 | | | | | | |

The report contract in §30 is covered by SEC-1 to SEC-9 and PRS-1. The §48
definition of v1 is covered as follows: 13 by PRS-7, 16 by SEC-4, 17 by PRS-2 with
SEC-7, and 18 by SCL-5. The rest was already met when `AGENTS.md` was last updated.

## 9. A lane brief, for handing a lane to an agent

Copy this, fill in the lane, and send it as the first message of a fresh session:

> You own lane **L_n** of `docs/parallel-development-spec.md`. Read §3 (the rules),
> §4 (the contracts your lane consumes and produces), §5 (your metrics) and your
> lane's section. Then read `docs/next-cycle-handover.md`'s non-negotiables and
> baseline procedure. Edit only the paths your lane owns. If you need a
> contract field, open a separate contract PR first. Iterate against
> `replay_report.py last_runs/` and your lane's tests, not the live Space. For each
> item: verify its evidence against the tree, build it, prove any refusal with a
> test, and record what you did not do. Run `measure.py` on the replay and on the
> next live cycle, and state the metric before and after, within the noise floor.
> Branch `lane/L_n/<item>`, one PR per item, and mark the item's status in this
> document in the same PR.

## 10. What done looks like

- The scoreboard's targets in §5 hold across three same-commit cohorts on every
  benchmark target, measured rather than asserted.
- §30 is 9 of 9 met by `measure.py`'s own computation. §31's four kinds of claim
  are tagged on every line.
- No report leads with a finding that was measured from pixels that are not the
  element, and none files the harness's limits as the site's faults.
- A persona who is fed up leaves, and that departure reaches the reader as a
  finding.
- A fix predicted by a finding has been re-run, and the report says whether the
  fix held (SCL-3). No human review can close that loop.
- A cycle is one command, and a report change can be checked offline in seconds.
