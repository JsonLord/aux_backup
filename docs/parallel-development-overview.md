# Ten lanes, one scorer

*A one-page overview of `docs/parallel-development-spec.md`. The spec is the build
document: one row per item, each with its evidence and done-when. This page is the
board.*

**Tree** `915173a` · **Seeded by** `last_runs/` (open-design.ai, 1 persona,
2026-09-22) · **Companion** the audit *Observed vs Explained* (68 criteria)

The remaining work comes from the audit, the report contract, the hats and the run
loop. It is split into ten lanes, so that ten agents can build at once without
touching each other's files. A single measurement of real runs grades every lane.
No lane grades itself.

## What the last run changed

Cycle 51 was the first with a *passed* verdict. Since then, the previous plan's
report, backend and hats items have nearly all landed. The run in `last_runs/` is
the first live look at the result. It confirms one thing the plan could only
assert: the scan now remembers what it has already seen.

It contradicts three others. The finding the report leads with is measured from
blank page. A persona at full frustration cannot leave, because one line overwrites
another. The gate meant to keep the persona in character lets through the actions
it rejects, and it takes half the model time.

None of this was visible without reading the run, and every cycle is still read by
hand. **That is why lane zero is the run factory.** It commits the scripts, adds an
offline replay, and records a noise floor. Every other lane gets faster with it.

## Read off the run

Every figure comes from `last_runs/artifacts/*.json`, or from a crop that was
opened and looked at. It is one run on a new site with no noise floor, so these are
defects to fix. They are not trends.

| figure | what it is | lane |
|---|---|---|
| **1.03–1.13:1** | The ratios of all four "Fails WCAG AA" findings. The two crops opened, "Video" and "Italiano", are blank page. The summary's "one thing to change" is one of them. | EVD-1, FND-1 |
| **0.033 → 0.615** | The highest probability of abandoning, reached at frustration 1.00. The tolerance check at `behavior.js:160` is overwritten at `:163`. Closed in code (the right-hand figure is this same real state, re-scored against the fix); not yet confirmed live. | JRN-1 |
| **2 of 3 → 0** | Actions the adherence gate failed (scores 3, 4 and 0) confirmed to have run anyway, via a matching pointer event (the 3rd has no pointer event either way). The gate also judged `e367` "unrelated" when it was the Pricing link. Both closed in code: a rejected action can no longer reach `perform()` at all, and the judge now reads "the 'Pricing' link", never a bare ref; not yet confirmed live. The cost half of JRN-3 (47%, below) is untouched. | JRN-3 |
| **7 clicks → recognised by action 7** | Alternating between Pricing and "Start free for 30 days". Pricing was clicked under three refs, so no per-ref counter saw a repeat. Closed in code, checked against this exact sequence (`loopDetector.detectLoop` fires on the second Pricing→Start-free round trip); not yet confirmed live. | JRN-2 |
| **1** | The run hit its step budget, and that was filed as a high-severity usability finding. `run_diagnostics` is empty. | SEC-1, JRN-4 |
| **47%** | The adherence judge's share of the run's 176 s of model time. It is the largest single lever on run speed. | JRN-3, OPS-3 |
| **0 / 8** | Findings about the site with a video timestamp, though every timeline event carries `videoTimeMs` (9 findings carry `evidenceScreenshot`, one of them the misfiled run-limit finding SEC-1 relocates). | SEC-5 |
| **5 empty** | Evidence channels: snapshots, console, network, UI changes and video clips. `REPORT_CRITERIA.md` rates §30.9 higher than this supports. | EVD-2 |
| **47 → 0** ✓ | Elements not yet looked at, over the run. The scan now remembers, confirmed live: 12 of 12 captures trusted, 10 of 10 pointer boxes measured. | CAP-0, held |

## The persona who could not leave

§30.4 asks for an experience trajectory, and none is assembled. Every
`persona.affect` event already carries the full state. This is that trajectory for
the snapshot run (Alex Chen, open-design.ai). It is the evidence for JRN-1 and the
data SEC-2 turns into a report section.

| step | frustration | confusion | trust | p(abandon) | coping chosen | failures in a row |
|---:|---:|---:|---:|---:|---|---:|
| 1 | 0.13 | 0.21 | 0.98 | 0.004 | retry | 1 |
| 2 | 0.19 | 0.31 | 0.95 | 0.005 | retry | 2 |
| 3 | 0.33 | 0.53 | 0.94 | 0.006 | explore | 3 |
| 4 | 0.19 | 0.41 | 0.98 | 0.004 | explore | 0 |
| 5 | 0.33 | 0.64 | 0.96 | 0.007 | backtrack | 1 |
| 6 | 0.47 | 0.87 | 0.94 | 0.008 | backtrack | 2 |
| 7 | 0.55 | **1.00** | 0.91 | 0.009 | backtrack | 3 |
| 8 | 0.73 | 1.00 | 0.88 | 0.016 | reread | 4 |
| 9 | **0.89** | 1.00 | 0.86 | 0.025 | reread | 5 |
| 10 | **1.00** | 1.00 | 0.81 | **0.033** | explore | 6 |

The abandon tolerance for this profile is **0.78**
(`repeatFailureTolerance 0.5 + 0.35 × persistence 0.8`). It is crossed at step 9,
with five failures in a row. `behavior.js:160` sets `copingMode = "abandoning"`,
and `:163` replaces it with `"cautious"` in the same call. The run then ends
"inconclusive" at its 12-step budget. p(abandon) is the coping policy's own
recorded distribution, not a re-derived figure.

**JRN-1 closes this the only way it can be closed without a live rerun:** the
tolerance check now feeds the coping score it was always meant to change instead
of a label the next line discarded, and moving it is enough — nothing about *how*
these ten states were reached needed to change, so re-scoring the same real
states above with the fixed policy is a faithful check of the fix, not a
simulation of one. Steps 1–8 are unchanged to four decimal places. At step 9,
p(abandon) goes 0.025 → 0.332 and the leader flips from `reread`; at step 10,
0.033 → **0.615**, abandon the clear leader rather than the 9th of 9 options.
Whether a live persona at this same profile now actually leaves, rather than
running out its step budget "inconclusive," is exactly what RUN-2 would show and
has not been asked to yet.

## The lanes

Each lane owns its own paths, so after the one mechanical split (RUN-0) no two
lanes edit the same file. Each consumes and produces named contracts, iterates
offline against a replay of the last run in seconds, and is judged by rows of the
shared scoreboard.

The rules, in brief:

- **Contracts change first.** A contract only ever gains fields, in its own PR,
  merged before either side uses the new field.
- **Fixtures before live.** Iterate on the replay of `last_runs/`. Use the Space
  for acceptance only.
- **One scorer.** `measure.py` reads the fields where the report speaks. It never
  greps.
- **The floor gates "better".** Nothing is called an improvement on one run.

| lane | wave | owns | start with | moves |
|---|---|---|---|---|
| **L0 · RUN**, run factory and scoreboard | 0 | `scripts/cycle/`, `tests/replay/`, `docs/contracts/`, `last_runs/` | **RUN-0**: the seams, alone and mechanical. `assemble_report()` comes out of the executor, and `assembler.py` is split into findings, sections, render and media. **RUN-1**: commit `measure.py`, which must reproduce the baseline. **RUN-3**: offline replay in under 30 s. | A cycle is one command. A report change is checked offline in seconds. |
| **L1 · JRN**, journeys that finish | 0 | journey-worker `behavior`, `personaDirector`, `personaActor`, `adherence`, `journeytest` | **JRN-1**: make abandoning reachable once tolerance is crossed. **JRN-2**: break loops, recognising a control by its label across refs, and A↔B alternation. **JRN-3**: make the gate a gate, give the judge the label rather than the ref, and cut its cost. | Budget-hit share 1/1 → ≤ 1/3. Loops 1 → 0. Fed-up runs still browsing 1 → 0. |
| **L2 · EVD**, perception and evidence capture | 0 | `perception_service/`, `perception`, `revealKeeper`, `cursorKeeper`, `viewportStream` | **EVD-1**: detect no ink on a patterned background, with the two blank crops as fixtures. **EVD-2**: fill snapshots, console, network, UI changes and clips, or state why each is missing. **EVD-3**: check pointer boxes on the taoshq billing toggle. | False contrast 4 → 0. §30.9 rated met, on evidence. |
| **L3 · FND**, findings and judgement | 1 | `report_service/findings/`, `media.py`, `eyeson-worker/`, `knowledge-service/` | **FND-1**: a report-side ink guard, plus one finding per component. **FND-2**: judge severity from the task path, the change in affect, and reach. **FND-4**: complete alternatives, each with an effort class and a trade-off. | Alternatives with effort 1/13 → 13/13. Confidence 0 → 13/13. Contradictions 1 → 0. |
| **L4 · SEC**, the report contract (§29–§31) | 1 | `report_service/sections/`, `assemble.py`, `docs/contracts/ux-report.md` | **SEC-1**: move budget endings to `run_diagnostics`. **SEC-2**: the experience trajectory above, as a report section. **SEC-5**: video timestamps from each capture's own `videoTimeMs`. | §30 met / partial / missing 4/4/1 (measure.py) → 9/0/0, computed by the scorer. |
| **L5 · PRS**, presentation and craft | 1 | `report_service/render/`, deck fit tests, the Gradio report viewer | **PRS-1**: the trajectory chart, once SEC-2 lands. **PRS-2**: PDF export, a page break per slide. **PRS-4**: a step and video-time stamp on each evidence figure. | E12, A4, G1 and F4 closed. §48.13 verified. |
| **L6 · SCL**, scale and the closed loop | 1 | the run half of `executor.py`, job types | **SCL-1**: repeat seeds dispatched as `persona_id#seed`. **SCL-3**: a retest job that reports whether the fix held. | `reproducedIn` ≥ 2 on ≥ 1/3 of findings. The first validated fix. |
| **L7 · HAT**, reach: sign-in and hats | 0 and 2 | `webui/`, `hats.py`, `credentials.py`, `developerTool`, `loginCapture` | **HAT-1**: the first signed-in run, on a site the operator controls. **HAT-2**: developer mode on open-design.ai's download. | No account identifier in any artifact. A finding with its command transcript attached. |
| **L8 · PSN**, persona fidelity | 0 | `persona_service/`, the actor corpus and compile scripts | **PSN-4**: three pinned benchmark personas, spread in patience, persistence and acuity. **PSN-1**: compile the actor program on a real corpus. | Gate regeneration rate, before and after. |
| **L9 · OPS**, platform, reliability and cost | 0 | `spaces/`, `Dockerfile`, the deploy script, `model_*.py`, readiness | **OPS-1**: storage that survives a restart. **OPS-2**: provider fallback shown live. **OPS-3**: cohort wall time ≤ 8 min. | Cohort wall time, cost per review, and a scoreboard history that persists. |

## The scoreboard

`measure.py` computes it on every replay and every live cycle. The baseline is the
snapshot run. It is a single run with no noise floor, so "failing" means something
to fix, not a measured rate.

| metric | baseline | target | now | lane |
|---|---|---|---|---|
| Verdicts: passed / failed / inconclusive | 0 / 0 / 1 | ≥ 2 of 3 decided, per target | failing | L1 |
| Budget-hit share | 1 / 1 | ≤ 1/3 | failing | L1 |
| Runs ending at frustration ≥ 0.9 still browsing | 1 | 0 | failing | L1 |
| Loops (a label clicked ≥ 3 times, or A↔B ≥ 2) | 1 | 0 | failing | L1 |
| Actions executed below the adherence threshold | 2 (pointer-confirmed) | 0 | failing | L1 |
| Captures / refused | 12 / 0 | within the floor | unmeasured | L2 |
| Pointer boxes measured | 10 / 10 | ≥ 95% | meets | L2 |
| Findings about the site / positives | 13 / 1 | ≥ 10 / ≥ 2 | partial | L3 |
| Run diagnostics filed as findings | 1 | 0 | failing | L4 |
| "Fails" at a ratio below 1.2 with no verified ink | 4 | 0 | failing | L2, L3 |
| Same control both preserved and faulted | 1 | 0 unreconciled | failing | L3 |
| Alternatives with an effort class | 1 / 13 | 13 / 13 | failing | L3 |
| Per-finding confidence | 0 / 13 | 13 / 13 | failing | L3 |
| Video timestamp, where a screenshot exists | 0 / 8 | 8 / 8 | failing | L4 |
| §30 sections met / partial / missing | 4 / 4 / 1 | 9 / 0 / 0 | partial | L4 |
| Adherence share of model time | 47% | ≤ 25% | failing | L1, L9 |
| Cohort wall time, 3 personas × 2 targets | not measured | ≤ 8 min | unmeasured | L0, L9 |
| Findings reproduced in ≥ 2 runs | not measured | ≥ 1/3 | unmeasured | L6 |
| Noise floor recorded | no | yes, in `spec.md` | failing | L0 |

## Order and cadence

Only RUN-0 runs alone, because it moves the report package that three lanes will
then own. Every other wave-zero item touches different files and starts on day one.

- **Wave 0, day one:** **RUN-0 alone**. Beside it: RUN-1, RUN-7, RUN-8, JRN-1,
  JRN-2, JRN-3, JRN-4, JRN-6, EVD-1, EVD-2, EVD-3, HAT-1, PSN-4, OPS-1, OPS-2.
- **Wave 1, after RUN-0** (the report package opens): RUN-3, RUN-4, RUN-5,
  FND-1…6, FND-9, FND-12, SEC-1…10, PRS-2…7, SCL-1.
- **Wave 2, after RUN-2** (anything that needs live cycles): RUN-6 (the noise
  floor), JRN-5, EVD-4, HAT-2, PSN-1.
- **Gated on one input each:** FND-8 ← EVD-5 · FND-10 ← PSN-3 · FND-11 ← JRN-7 ·
  PRS-1 ← SEC-2 · SCL-2/3/4 ← SCL-1.

| loop | trigger | time | what runs |
|---|---|---|---|
| Inner | every save | seconds | lane tests, plus a replay of `last_runs/` |
| PR | every push | minutes | the Python and Node suites, plus the golden replay invariants |
| Outer | a merge wave or on demand | 6–8 min | `run_cycle.py` over the benchmark set, then a scoreboard row |
| Floor | weekly or after a large merge | ~25 min | three same-commit cycles, then the noise floor re-checked |
| Snapshot | a metric moved beyond the floor | minutes | `refresh_last_runs.py`, with the report criteria re-rated by the scorer |

### The first ten, by impact per unit of effort

1. **RUN-0, RUN-1, RUN-3**: the seams, the scorer, offline replay. Every other
   lane's speed depends on them.
2. **EVD-1, FND-1**: the report's lead finding is measured from blank page.
3. **SEC-1**: a harness limit is filed as a fault of the site.
4. **JRN-1**: leaving is unreachable because one line overwrites another.
5. **JRN-2, JRN-3**: loops, and a gate that does not gate, which costs 47% of
   model time.
6. **SEC-2**: the one missing §30 section, whose data already exists.
7. **FND-2, SEC-9**: judge severity, so the summary leads with a finding on the
   task path.
8. **SEC-5**: video timestamps, a join with data already in hand.
9. **RUN-6**: the noise floor. Without it, none of the above can be called better.
10. **FND-4, SEC-3**: alternatives complete, then ranked by a stated rule.

## Contracts

These are the only things that queue between lanes. Each has a short document in
`docs/contracts/` and a fixture derived from the snapshot. A field is never renamed
or removed while anything reads it.

| id | contract | producer → consumers | additions this cycle |
|---|---|---|---|
| K1 | journey timeline | L1, L2 → L3, L4, L0 | ending reason; loop and wait events; heading level, alt text, label and focus state on walked elements; measured styles |
| K2 | finding | L3 → L4, L5, L0 | confidence; evidence kind per claim; video timestamp and step; effort and trade-off on alternatives; grouped instances |
| K3 | ux.report | L4 → L5, L0 | experience trajectory; ranked alternatives; knowledge basis; evidence index; named outcome counts |
| K4 | scoreboard | L0 → all | the metric catalogue above |
| K5 | run request | L6, L7, L9 → L1 | a seed per run and synthetic run ids; `retestOf` |
| K6 | vision cache | L3 → L0 | recorded critique responses, so replay makes no model calls |

## Every audit criterion, by lane

All 68 criteria of *Observed vs Explained* are shown with their standing after the
previous plan, checked against the snapshot. The item named after the arrow owns
what is left. Two criteria that were closed have **regressed live**.

**Held 9 · closed 29 · partial 7 · open 20 · regressed live 2 · deferred 1**

| group | held | closed | partial | open | regressed live / deferred |
|---|---|---|---|---|---|
| A · Evidence | A1 → RUN-5, A10 → FND-3 | A2, A3, A5 → FND-7, A6 → SEC-1, A7, A9 | | A4 → PRS-4, A8 → SCL-1 | |
| B · Root cause | | B1, B2, B3, B4, B5 → PRS-3 | B6 → FND-9, B7 → FND-2 | B8 → FND-3 | |
| C · Recommendations | | C1 → FND-9, C2, C3 | C4 → EVD-6, C5 → FND-4, C8 → SCL-3 | C6 → FND-4, C7 → FND-4, C9 → SEC-3 | |
| D · Coverage | D5 | D6, D7 | D9 → FND-5 | D1 → JRN-8, D2 → HAT-1, D3 → FND-10, D8 → JRN-7, D10 → JRN-8 | **D4** → EVD-1 (regressed) |
| E · Craft | E1, E3 | E5, E6, E7, E8, E11 | | E2, E4, E9, E10 → PRS-5; E12 → PRS-2 | |
| F · Narrative | F3, F7 | F1 → SEC-9, F2, F5 → FND-6, F6, F8 | | F4 → PRS-6 | |
| G · Process | G5 | G4 | | G1 → PRS-3, G6 → SCL-1 | **G3** → SEC-1 (regressed); G2 deferred |
| H · Operational | H1 | H2 → OPS-5, H4 → OPS-2 | H3 → SCL-5 | H5 → SCL-1 | |

---

Sources: `docs/parallel-development-spec.md` · `last_runs/`
(`job_90142999fc7640a0924ebef82c2be471`: 243 s, 55 model calls, 53,278 tokens) ·
`docs/next-cycle-worksheet.md` (cycles 44–51) · `spec.md` §29–§31, §48, §53, §55.
