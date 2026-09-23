# last_runs/

Evidence from the most recent real, live run against the deployed Space
(`Leon4gr45/aux-synthetic-ux-demo`). This directory is a **snapshot, not an
archive** -- it holds exactly one run's worth of evidence at a time, replaced
in full every time a new verification run is captured. Its purpose is to give
a reader (human or agent) something to point at when checking "does this
actually work," without having to re-run a live journey or dig through HF
Space logs first.

## Why a snapshot and not a history

Every artifact here is real bytes from a real run: screenshots, a video, the
assembled `ux.report`/presentation/slides, the raw `journey.log` timeline,
and the deploy/job logs that produced them. That is worth exactly one copy in
git. AGENTS.md (repo root) already carries the scar from this mistake once --
`node_modules/` reaching 196 MB before anyone noticed. A `last_runs/` that
accumulates one run's ~9 MB of binaries per verification would repeat it on a
longer fuse. Keep one run. Overwrite it.

## What's in here

```
last_runs/
  AGENTS.md                    -- this file
  REPORT_CRITERIA.md           -- spec.md section 30's report contract,
                                   checked against the run captured below
  artifacts/
    ux_report__<id>.json       -- the assembled ux.report (the thing
                                   REPORT_CRITERIA.md is rated against)
    ux_presentation__<id>.html -- the rendered narrative deck
    ux_slides__<id>.html       -- the rendered slide deck
    journey_log__<id>.json     -- raw journey.log: the full per-run timeline
                                   (persona.expectation/reflection/affect,
                                   browser.screenshot, model calls, etc.)
    persona_profile__<id>.json -- the synthetic user this run used
    browser_screenshot__<id>.png (x N) -- real captures from the run
    browser_video__<id>.webm   -- the run's screen recording
  logs/
    workflow_response.json     -- the /api/v1/workflows/usability response
                                   (session, job, artifact list) -- personas
                                   stripped (duplicated in artifacts/)
    job_final.json             -- GET /api/v1/jobs/<id> after completion
    readiness.json             -- GET /api/readiness at deploy time
    deploy_build_runtime.log   -- the HF Space build + startup log for the
                                   deploy this run was verified against
```

## How to refresh this folder after a new verification run

There is no script for this yet -- it has been done by hand, from an agent
session with `HF_TOKEN` and a workspace ID, each time so far. The steps, so
the next run (agent or human) can reproduce them exactly:

1. Deploy or confirm the target Space is current:
   `python scripts/deploy_hf_space.py Leon4gr45/aux-synthetic-ux-demo --folder spaces/aux-live --full-repo --timeout 1800`
   Save its build+runtime log as `logs/deploy_build_runtime.log`.
2. Confirm `GET /api/readiness` and save it as `logs/readiness.json`.
3. Run a real workflow (`POST /api/v1/workflows/usability`, a real target URL,
   `persona_count: 1` is enough to verify the pipeline without burning a lot
   of model budget) and save the response as `logs/workflow_response.json`
   (strip the `personas` array -- it is saved per-artifact instead).
4. Poll `GET /api/v1/jobs/<job_id>` until `succeeded`/`failed`; save the final
   state as `logs/job_final.json`.
5. List the session's artifacts (`GET /api/v1/sessions/<id>/artifacts`),
   download every one (`GET /api/v1/artifacts/<id>/download`), and place them
   under `artifacts/` named `<kind_with_underscores>__<artifact_id>.<ext>`.
6. **Delete everything this folder held from the previous run first** (or
   overwrite in place -- either way, `git status` after should show the old
   run's files as deleted/replaced, never both old and new coexisting).
7. Update `REPORT_CRITERIA.md`'s fulfillment ratings against the new
   `ux_report__*.json` -- the criteria (spec.md section 30) do not change, but
   how well a given run's report fulfills them can, and should be re-checked
   rather than assumed unchanged.
8. Commit with a message naming what changed since the last snapshot (a new
   fix being verified, a regression found, or "no material change, refreshed
   for recency").

## What this folder is not

- Not a place to keep a run whose sole purpose was debugging (a scratch
  investigation belongs in a session's own scratchpad, never committed).
- Not a substitute for the test suites (`pytest tests/`, the per-service
  `npm test`) -- those are what CI-equivalent correctness rests on. This
  folder is evidence that the *deployed, live* system produces what the
  suites already predict it should, nothing more.
- Not a growing log -- if a question is "what changed between run N and run
  N+1," that belongs in a commit message or `docs/next-cycle-plan.md`'s
  narrative, not in keeping both runs' artifacts side by side here.
