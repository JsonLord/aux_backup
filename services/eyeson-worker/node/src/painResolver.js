"use strict";
const { createHash } = require("node:crypto");

const clamp = (value) => Math.max(0, Math.min(1, value));
const delta = (after, before, key) => Number(((after?.[key] || 0) - (before?.[key] || 0)).toFixed(6));

function attributionElements(evidence) {
  const actedId = evidence.action?.elementId;
  const changed = new Set(evidence.uiChangeElementIds || []);
  return evidence.elementMap.elements.filter((item) => item.id === actedId || changed.has(item.id))
    .map((item) => ({ elementId: item.id, box: item.box || item.bounds,
      role: item.id === actedId ? "trigger" : "feedback", contribution: item.id === actedId ? 1 : .7,
      confidence: item.id === actedId ? 1 : .8 }));
}

function resolvePainEpisodes(evidenceItems) {
  const episodes = [];
  for (const evidence of evidenceItems) {
    const before = evidence.behavior.before;
    const after = evidence.behavior.after;
    const event = evidence.behavior.events?.[0] || {};
    const frustrationDelta = delta(after, before, "frustration");
    const confusionDelta = delta(after, before, "confusion");
    const trustDelta = delta(after, before, "trust");
    if (!event.goalBlocked && frustrationDelta <= .05 && confusionDelta <= .05) continue;
    const elements = attributionElements(evidence);
    const impact = clamp(Math.max(0, frustrationDelta) + Math.max(0, confusionDelta) + Math.max(0, -trustDelta));
    const signature = `${evidence.runId}:${event.repeatKey || event.type}:${elements.map((item) => item.elementId).join(",")}`;
    const id = `pain_${createHash("sha256").update(signature).digest("hex").slice(0, 20)}`;
    const category = event.type || "interaction_friction";
    const painPoint = { id, runId: evidence.runId, userId: evidence.userId, stepIds: [evidence.stepId],
      title: category.replaceAll("_", " "), summary: `Observed ${category} blocked or increased effort on this step.`,
      severity: impact >= .65 ? "critical" : impact >= .4 ? "high" : impact >= .2 ? "medium" : "low",
      confidence: event.classifierConfidence ?? .8, screenshotRef: evidence.screenshot.artifactId,
      videoTimestampMs: evidence.timestampMs, behavioralImpact: { frustrationDelta, confusionDelta, trustDelta,
        cognitiveEffortDelta: delta(after, before, "cognitiveEffort"), physicalEffortDelta: delta(after, before, "physicalEffort"),
        elapsedCostMs: Math.max(0, (after.elapsedMs || 0) - (before.elapsedMs || 0)),
        retries: after.consecutiveFailures > 1 ? 1 : 0, backtracks: evidence.behavior.coping?.type === "backtrack" ? 1 : 0 },
      elements, diagnosis: { rootCause: `The ${category} event interrupted the intended action.`,
        mechanism: event.goalBlocked ? "The interface prevented visible task progress." : "The interaction increased user effort.",
        category, observedEvidence: [`${event.type} recorded at ${evidence.timestampMs}ms`,
          `Screenshot artifact ${evidence.screenshot.artifactId}`],
        behavioralEvidence: [`frustration ${frustrationDelta >= 0 ? "+" : ""}${frustrationDelta}`,
          `confusion ${confusionDelta >= 0 ? "+" : ""}${confusionDelta}`, `trust ${trustDelta >= 0 ? "+" : ""}${trustDelta}`],
        personaInteraction: "Behavioral amplification is inferred only from the persisted profile and transition.",
        confidence: event.classifierConfidence ?? .8 },
      grounding: { status: "not_configured", references: [] }, alternatives: [],
      overlays: elements.map((item) => ({ elementId: item.elementId, box: item.box,
        modes: { frustration: Math.max(0, frustrationDelta) * item.contribution,
          confusion: Math.max(0, confusionDelta) * item.contribution,
          repeatedAction: after.consecutiveFailures > 1 ? item.contribution : 0 },
        metricVersion: "element-friction-v1" })) };
    const existing = episodes.find((item) => item.id === id);
    if (existing) existing.stepIds.push(evidence.stepId);
    else episodes.push(painPoint);
  }
  return episodes;
}

module.exports = { resolvePainEpisodes, attributionElements };
