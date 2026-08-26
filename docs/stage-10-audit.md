# Stage 10 — physical and perceptual profile audit

Date: 2026-08-26

The Journey worker now has deterministic native functions for color-vision matrices,
contrast and acuity transform manifests, reading dwell time, working-memory filtering,
and seeded motor-pointer variation. Selected screenshot evidence retains both the
original artifact reference and a distinct perceived-artifact manifest referencing
that source.

Tests establish seed/profile reproducibility and verify that each effect changes
executable timing, retained context, target coordinates, or perceived-artifact
metadata. A renderer now materializes the configured matrix, contrast, and blur as an
SVG through an injected artifact-writer boundary while retaining the source artifact
ID. The browser adapter still supplies the authorized original artifact URL; no
demographic field automatically changes functional abilities.
