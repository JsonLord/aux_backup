# Stage 12 — knowledge grounding implementation audit

Date: 2026-08-26

`CuratedUXKnowledgeProvider` supplies bounded W3C WCAG and Nielsen heuristic records
for supported diagnosis categories. Results include source identity, title, framework,
principle, content, URL, and relevance. Unsupported categories return no references.

Grounding runs after evidence-based diagnosis and is copied onto linked alternatives.
The output explicitly separates observed, inferred, grounded, and proposed claims;
the null provider remains available for offline/not-configured deployments.
