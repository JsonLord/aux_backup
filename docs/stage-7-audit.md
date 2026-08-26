# Stage 7 — two-mode report audit

Date: 2026-08-26

The native report renderer provides User Journey and UX Feedback modes plus an
original/perceived screenshot toggle. Mode changes update only `mode` in query state;
run, user, and step selections are initialized once and retained. Journey mode renders
the selected state, while UX mode renders pain cards and overlay anchors.

The legacy Gradio register remains preserved. This standalone renderer is exposed by
the Eyeson worker's versioned `POST /v1/reports` boundary for incremental integration.
