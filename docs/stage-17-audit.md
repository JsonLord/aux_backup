# Continuation Stage 17 — alternative retest lineage audit

Date: 2026-08-26

This slice implements the lineage model from `spec.md` section 34. Each versioned link
stores source run, pain point, alternative, and deduplicated validation-run IDs.
Alternatives begin as `not_validated` and change to `rerun_recorded` only when an actual
validation run ID is attached.

The worker is stateless: callers persist the returned versioned lineage as a control-
plane artifact and send that reference/content back when adding validation runs. The
lineage API does not claim that expected impact was validated; comparative
behavior scoring remains dependent on a real browser rerun or human study.
