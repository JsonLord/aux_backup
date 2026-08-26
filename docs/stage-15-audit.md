# Continuation Stage 15 — deterministic evidence replay audit

Date: 2026-08-26

The migration plan in `spec.md` defines no formal Phase 15. This continuation slice
implements the deterministic replay requirement from section 38.

`POST /v1/replays` re-runs the native state reducer and seeded coping policy against
stored normalized experience events without launching or revisiting a browser. The
result retains source run/profile identifiers and reducer/policy versions for audit.
Eyeson reanalysis can then consume the persisted step evidence through its existing
versioned HTTP API.

Replay input now rejects evidence entries without a normalized experience-event type,
preventing malformed stored records from silently producing invalid transitions.
