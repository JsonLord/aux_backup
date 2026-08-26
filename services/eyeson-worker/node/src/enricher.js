"use strict";

function enrichRun(run) {
  const evidence = (run.steps || []).flatMap((step) => step.evidence || []);
  const painPoints = evidence.flatMap((item) => item.eyeson?.painPoints || []);
  const trajectory = (run.steps || []).map((step, index) => ({ step: index + 1, stepId: step.stepId,
    timestampMs: step.evidence?.[0]?.timestampMs ?? index, ...(step.state || {}) }));
  const alternatives = painPoints.flatMap((painPoint) => painPoint.alternatives || []);
  return { ...run, uxAnalysis: { schemaVersion: "1.0", behaviorSummary: {
    steps: (run.steps || []).length, retries: painPoints.reduce((sum, point) => sum + point.behavioralImpact.retries, 0),
    backtracks: painPoints.reduce((sum, point) => sum + point.behavioralImpact.backtracks, 0),
    abandoned: run.verdict === "abandoned" }, emotionalTrajectory: trajectory, painPoints,
    eyeson: { status: evidence.some((item) => item.eyeson?.status === "failed") ? "partial"
      : evidence.some((item) => item.eyeson?.status !== "completed") ? "pending" : "completed",
      analyzedEvidence: evidence.filter((item) => item.eyeson?.status === "completed").length,
      totalEvidence: evidence.length }, alternatives, grounding: {
      status: painPoints.some((point) => point.grounding?.status === "completed") ? "completed" : "not_configured",
      references: [...new Map(painPoints.flatMap((point) => point.grounding?.references || []).map((ref) => [ref.id, ref])).values()] } } };
}

function renderMarkdown(run) {
  const enriched = run.uxAnalysis ? run : enrichRun(run);
  const analysis = enriched.uxAnalysis;
  const strongest = analysis.painPoints[0];
  return `# UX simulation report

## Executive summary

- Journey verdict: **${enriched.verdict || "unknown"}**
- Analyzed evidence: ${analysis.eyeson.analyzedEvidence}/${analysis.eyeson.totalEvidence}
- Strongest pain point: ${strongest?.title || "None observed"}
- Grounding: ${analysis.grounding.status}

## Synthetic user

- Profile: ${enriched.profileId || enriched.userId || "unknown"}
- Behavior seed: ${enriched.simulationProfile?.behavior?.seed ?? "unknown"}

## Journey outcome

- Steps: ${analysis.behaviorSummary.steps}
- Retries: ${analysis.behaviorSummary.retries}
- Backtracks: ${analysis.behaviorSummary.backtracks}
- Abandoned: ${analysis.behaviorSummary.abandoned}

## Critical pain points

${analysis.painPoints.map((point) => `### ${point.title}

**Observed:** ${point.diagnosis.observedEvidence.join("; ")}

**Behavioral effect:** ${point.diagnosis.behavioralEvidence.join("; ")}

**Inferred:** ${point.diagnosis.rootCause} Confidence: ${point.diagnosis.confidence}.

**Grounded:** ${point.grounding.status === "completed" ? point.grounding.references.map((ref) => `${ref.source} — ${ref.title}`).join("; ") : "Not configured"}

**Proposed:** ${(point.alternatives || []).map((alternative) => alternative.proposedChange).join("; ") || "No alternative generated"}
`).join("\n")}
## Full evidence

${analysis.emotionalTrajectory.map((state) => `- ${state.stepId}: frustration ${state.frustration ?? 0}, confusion ${state.confusion ?? 0}, trust ${state.trust ?? 0}`).join("\n")}
`;
}

module.exports = { enrichRun, renderMarkdown };
