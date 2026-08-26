# Stage 5 — evidence bus and Eyeson screenshot streaming audit

Date: 2026-08-26

## Implemented

- The Journey worker creates versioned `JourneyStepEvidence` records for every
  selected screenshot. Screenshot and snapshot payloads cross the service boundary
  only as persisted artifact references.
- Each record synchronizes its run, user, iteration, step, timestamp, action, exact
  stable element map, experience event, before/after behavior state, and coping intent.
- The evidence coordinator starts Eyeson requests as screenshots are selected and
  waits for outstanding analysis only during run finalization. Deep analysis therefore
  does not block later journey steps.
- `ux.analysis.requested`, `ux.analysis.completed`, and `ux.analysis.failed` events
  preserve evidence ID, step ID, and timestamp for live UI synchronization.
- A separately deployable Eyeson worker now exposes `POST /v1/evidence-analyses` in
  addition to the preserved legacy URL-oriented engine. Its response preserves the
  input evidence coordinates and attaches findings to stable element and screenshot
  artifact IDs.
- The same coordinator handles fixture evidence and evidence emitted by the pinned
  JourneyTest adapter. When no Eyeson endpoint is configured, evidence remains
  explicitly `pending` rather than blocking or inventing a failure.

## Acceptance evidence

Node tests prove that the screenshot artifact reference, complete element map, and
behavior transition received by Eyeson exactly match the selected journey step. They
also prove that returned findings reattach to that step and its original timestamp.

## Remaining visual-analysis boundary

The evidence bus and asynchronous service contract are complete. The Eyeson worker's
current finding confirms synchronized evidence ingestion; deep visual critique is a
`PLACEHOLDER` pending migration of the pinned Eyeson implementation into this native
worker. Pain episode aggregation and overlay generation belong to Stage 6.
