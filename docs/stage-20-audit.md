# Continuation Stage 20 — privacy and retention audit

Date: 2026-08-26

Evidence ingestion recursively removes password, token, authorization, cookie,
secret, payment-card, CVV, and SSN-shaped fields before analysis or tracing. Journey
action evidence uses the same deny-by-key behavior.

The retention policy exposes 30-day raw evidence, 180-day structured artifacts,
indefinite pinned artifacts, and a local-only mode that disables uploads. Durable
enforcement remains owned by the existing control-plane artifact adapters and sweeper;
the worker emits policy rather than bypassing that boundary.
