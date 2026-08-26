"use strict";
const { createHash } = require("node:crypto");

const average = (values) => values.length ? Number((values.reduce((a, b) => a + b, 0) / values.length).toFixed(6)) : 0;
function correlation(pairs) {
  if (pairs.length < 2) return 0;
  const meanX = average(pairs.map(([x]) => x));
  const meanY = average(pairs.map(([, y]) => y));
  const numerator = pairs.reduce((sum, [x, y]) => sum + (x - meanX) * (y - meanY), 0);
  const denominator = Math.sqrt(pairs.reduce((sum, [x]) => sum + (x - meanX) ** 2, 0)
    * pairs.reduce((sum, [, y]) => sum + (y - meanY) ** 2, 0));
  return denominator ? Number((numerator / denominator).toFixed(6)) : 0;
}

function rootCauseSignature(painPoint) {
  const route = painPoint.route || "unknown-route";
  const elements = painPoint.elements.map((item) => item.elementId).sort().join(",");
  return `${route}|${elements}|${painPoint.diagnosis.category}|${painPoint.diagnosis.mechanism}`.toLowerCase();
}

function aggregateCohort(runs) {
  const groups = new Map();
  for (const run of runs) {
    for (const painPoint of run.uxAnalysis?.painPoints || run.painPoints || []) {
      const signature = rootCauseSignature(painPoint);
      const group = groups.get(signature) || { id: `root_${createHash("sha256").update(signature).digest("hex").slice(0, 16)}`,
        signature, category: painPoint.diagnosis.category, mechanism: painPoint.diagnosis.mechanism,
        elementIds: painPoint.elements.map((item) => item.elementId).sort(), painPointIds: [], users: new Set(),
        iterations: new Set(), impacts: [], abandonments: 0, alternatives: new Map(), profiles: [] };
      group.painPointIds.push(painPoint.id);
      group.users.add(run.profileId || run.userId);
      group.iterations.add(run.iterationId || "iteration-1");
      group.impacts.push(painPoint.behavioralImpact);
      group.abandonments += run.verdict === "abandoned" ? 1 : 0;
      const impactScore = Math.max(0, painPoint.behavioralImpact.frustrationDelta)
        + Math.max(0, painPoint.behavioralImpact.confusionDelta) + Math.max(0, -painPoint.behavioralImpact.trustDelta);
      group.profiles.push({ traits: run.simulationProfile?.behavior || {}, impact: impactScore });
      for (const alternative of painPoint.alternatives || []) group.alternatives.set(alternative.id, alternative);
      groups.set(signature, group);
    }
  }
  return [...groups.values()].map((group) => ({ id: group.id, signature: group.signature,
    category: group.category, mechanism: group.mechanism, elementIds: group.elementIds,
    painPointIds: group.painPointIds, affectedUsers: [...group.users].filter(Boolean),
    affectedIterations: [...group.iterations], averageStateImpact: {
      frustration: average(group.impacts.map((item) => item.frustrationDelta)),
      confusion: average(group.impacts.map((item) => item.confusionDelta)),
      trust: average(group.impacts.map((item) => item.trustDelta)) }, abandonmentCount: group.abandonments,
    personaSusceptibility: Object.fromEntries(["patience", "persistence", "digitalConfidence", "verificationTendency"]
      .map((trait) => [trait, correlation(group.profiles.map((profile) => [Number(profile.traits[trait]), profile.impact])
        .filter(([value]) => Number.isFinite(value)))])),
    alternatives: [...group.alternatives.values()].sort((a, b) => b.confidence - a.confidence) }));
}

module.exports = { aggregateCohort, rootCauseSignature };
