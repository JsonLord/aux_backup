# Handover brief for the implementation model

Copy everything below the line as the prompt. It is written to be read cold.

---

You are implementing the next cycle of this repository. The plan already exists and
was written against the code rather than from memory; your job is to build it, not
to re-plan it.

## Where the documentation is

Read these before you write anything, in this order:

| File | What it is |
| --- | --- |
| `docs/next-cycle-plan.md` | **Start here.** All three tracks, every item, the dependency graph, the file-ownership table, the risks, and an appendix accounting for all 68 criteria of the audit that started this. |
| `docs/next-cycle-tracks-b-c.md` | The build spec for the backend and hats tracks: seams, contracts, tests and done-when, item by item. |
| `docs/next-cycle-be-1.md` | BE-1 in full, including a record of what was built differently from plan and why. Read it as an example of the level of detail expected of you. |
| `docs/next-cycle-worksheet.md` | The measured record — cycles 44–51, the treadmill diagnosis, the hats design rationale, and the ground rules this project has paid for. Not yours to edit. |
| `AGENTS.md` | Repository conventions. Service isolation ("communicate only through versioned HTTP contracts, job IDs, and persisted artifact references") is load-bearing and has already shaped two items. |

**Naming.** Plan items are `RPT-n` (report), `BE-n` (backend), `CAP-n`
(capabilities/hats). A bare letter-digit code like `B2` or `E7` always means a
criterion of the audit, never a plan item. `Hat 1`–`Hat 4` are the worksheet's hats.

## What is already built

`BE-1` (model routing through the workspace's providers, across four processes),
`BE-2` (the report assembler extracted into `services/report_service/`), and `CAP-1`
(the `/webui` configuration surface). Their headings say **done** and the commits
explain what each changed beyond its plan.

Everything else is open: `RPT-1` through `RPT-6`, `BE-3`, `BE-4`, `BE-5`, `CAP-0`,
`CAP-2` through `CAP-6`.

## Before you change one line: get a baseline

A mechanical change is only safe against a known-good starting point, and this repo
has three test failures that are *not* yours.

```bash
uv venv --python 3.12 /tmp/be-venv
uv pip install --python /tmp/be-venv/bin/python \
  pytest pytest-asyncio pytest-cov fastapi pydantic cryptography Pillow requests httpx \
  numpy scipy huggingface-hub "gradio[oauth]==5.15.0" openai chevron textdistance \
  beautifulsoup4 lxml lxml_html_clean

/tmp/be-venv/bin/python -m pytest tests/ -q -p no:cacheprovider \
  --ignore=tests/e2e --ignore=tests/load --ignore=tests/integration -rf \
  | tee /tmp/baseline-raw.txt
grep -E "^(FAILED|ERROR)" /tmp/baseline-raw.txt | sed 's/ - .*//' | sort > /tmp/baseline.txt

cd services/journey-worker/node && node --test test/*.test.js    # no node_modules needed
```

At the commit this brief was written, that is **424 passed, 3 failed** (Python) and
**264 passed** (node). The three failures all need `dspy`, which `AGENTS.md`
deliberately leaves uninstalled:

```
test_model_providers.py::test_the_service_resolves_providers_in_exactly_one_place
test_persona_studio.py::test_load_example_persona_into_studio_appends_and_selects_new_entry
test_persona_studio.py::test_load_example_persona_into_studio_surfaces_compile_failure
```

**After every item, diff the failure list against that baseline rather than reading
the count.** `diff /tmp/baseline.txt /tmp/after.txt` empty means no regression. A
count that matches can still hide one test breaking while another is added.

## How to work through it

**Work several items at once where the file-ownership table says you may.** It is in
`docs/next-cycle-plan.md` under "How the three tracks run in parallel", together with
the dependency graph. Honour both: some things genuinely serialize.

- `CAP-2` → `CAP-5` → `CAP-6` is a chain; the developer-mode tool needs a registry to
  be mounted from.
- `CAP-0` gates **part of** two report items, not all of them: `RPT-2` can name the
  convention, the property and the mental model immediately, and only its *mechanism*
  claim waits; `RPT-4` can do everything except promote a corroborated read gap.
  Start both, finish them after `CAP-0`.
- `BE-4` is a measurement, not code, and the plan says nothing else may be *called*
  an improvement before it exists. Run it early, not last.
- `RPT-1`, `RPT-5`, `RPT-6`, `BE-3`, `CAP-0`, `CAP-3`, `CAP-4` have nothing in front
  of them.

**Test at every point where being wrong would be expensive**, not on a fixed cadence.
That means: after any change to a shared seam, before and after any mechanical move,
and immediately after anything that touches credentials, redaction or a refusal path.
Run the narrow test first for the fast answer, the full suite before you commit.

## Non-negotiables

These were each learned from a defect in this repository. Breaking one is a
regression even when the tests pass.

1. **Faculties are added, never replaced.** `browsingFaculty()` stays under its own
   name; a hat records only what it `adds`. Browsing works and every job so far needs
   it. There is deliberately no field in which a hat could express a removal.
2. **A worker is handed a model chain only when that chain changes something.** The
   journey worker has its own settings — `JOURNEY_REFLECT_MODEL` is `alias-fast` on
   purpose, because reflection runs every step. Overwriting those with the
   general-purpose chain is a silent regression. But a *refused* caller must still be
   sent an explicitly empty chain, or the worker falls back to the very credentials
   it may not spend.
3. **Never log, record or echo a request that carries a key.** Report a provider as
   scheme and host only — a base URL can carry a key in a query string, so the path
   goes too. `redactSensitive()` (`services/journey-worker/node/src/safety.js`) is
   what anything written about a step passes through.
4. **A capability that is mounted and then guarded is one bug from ungated.** Mount
   it only when the run asked for it.
5. **Every safety rail gets a test that proves the *refusal*, not the happy path.**
   This record has three separate cases of a guard that passed by producing less.
6. **Services do not share a database.** The control plane resolves; workers receive
   over their HTTP contract.

## What is expected of you in the write-up

- **Verify against the tree, not against the plan.** The plan was accurate when
  written; parts of it have since been overtaken by its own items. Every line
  reference in it was checked once — check the ones you rely on again.
- **When the code contradicts the plan, the code wins and you say so.** Each of the
  three finished items deviated from its plan for a reason found while building, and
  each records the deviation in the document and the commit message. Do the same. A
  plan that quietly stops matching the code is worse than no plan.
- **State what you did not do.** Two scope boundaries are already recorded in
  `docs/next-cycle-be-1.md` — TinyTroupe's generation path and the Persona Studio
  callbacks — because they are real gaps, not oversights. Name yours the same way.
- Commit per item with a message that says what changed and why, and keep the plan's
  status markers in step with the code.

## What "done" looks like

Each item carries its own done-when. The cycle's, from the plan:

- No recommendation in a generated deck would read identically on a different page,
  and `alternatives` carries the committed-against option rather than being faked at
  render time.
- A panel that cannot be filled honestly renders nothing.
- `notLookedAt` falls across a run instead of holding at 13–14, and two of three runs
  reach a verdict other than inconclusive.
- A hat created in `/webui` mounts an additional faculty, and the persona's action
  vocabulary grows accordingly with no change to the director.
- A signed-in run produces no artifact containing unredacted account data.
- A noise floor is recorded in `spec.md`, so the next cycle can be called better or
  worse with a reason.
