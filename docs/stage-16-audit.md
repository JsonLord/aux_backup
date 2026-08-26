# Continuation Stage 16 — analysis scheduling audit

Date: 2026-08-26

This continuation slice implements `spec.md` section 33. Screen-budget selection uses
the contractual priority order—frustration spike, explicit error, abandonment, route
change, bookmark, representative state—with stable timeline ordering for equal/selected
items.

The in-memory `AnalysisQueue` enforces configurable concurrency, tracks jobs by run,
and supports deterministic flush before report finalization. `POST
/v1/evidence-batches` returns selected evidence IDs and completed analyses; production
Redis/BullMQ remains an adapter option rather than a second in-process fallback.
