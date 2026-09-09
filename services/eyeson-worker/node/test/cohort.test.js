"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { aggregateCohort } = require("../src/aggregate");
const { applyGrounding, CuratedUXKnowledgeProvider } = require("../src/knowledge");
const { enrichRun, renderMarkdown } = require("../src/enricher");
const { renderReport } = require("../src/report");

function pain(id, user, frustrationDelta = .4) {
  return { id, runId: `run-${user}`, userId: user, route: "/checkout", stepIds: [`step-${user}`], title: "validation failure",
    summary: "Submission was blocked.", screenshotRef: `screen-${user}`, videoTimestampMs: 10,
    behavioralImpact: { frustrationDelta, confusionDelta: .2, trustDelta: -.1, cognitiveEffortDelta: .2,
      physicalEffortDelta: 0, elapsedCostMs: 400, retries: 1, backtracks: 0 },
    elements: [{ elementId: "submit", role: "trigger", contribution: 1, confidence: 1 }],
    diagnosis: { category: "validation_failure", mechanism: "The interface prevented visible task progress.",
      rootCause: "Validation interrupted submission.", observedEvidence: ["error text appeared"],
      behavioralEvidence: ["frustration +0.4"], confidence: .9 }, grounding: { status: "not_configured", references: [] },
    alternatives: [{ id: "alt", confidence: .8, proposedChange: "Show an example.", addressesPainPointIds: [id] }], overlays: [] };
}

test("cohort aggregation clusters root causes across users and iterations", () => {
  const runs = ["ada", "lin"].map((user, index) => ({ runId: `run-${user}`, profileId: user,
    iterationId: `iteration-${index + 1}`, verdict: index ? "abandoned" : "passed",
    simulationProfile: { behavior: { patience: index ? .2 : .8, persistence: .5 } },
    painPoints: [pain(`pain-${user}`, user, index ? .7 : .4)] }));
  const aggregate = aggregateCohort(runs);
  assert.equal(aggregate.length, 1);
  assert.deepEqual(aggregate[0].affectedUsers, ["ada", "lin"]);
  assert.equal(aggregate[0].affectedIterations.length, 2);
  assert.equal(aggregate[0].abandonmentCount, 1);
  assert.equal(aggregate[0].averageStateImpact.frustration, .55);
  assert.equal(aggregate[0].personaSusceptibility.patience, -1);
});

test("curated grounding identifies sources and separates claim language", async () => {
  const grounded = await applyGrounding(pain("pain-1", "ada"), new CuratedUXKnowledgeProvider());
  assert.equal(grounded.grounding.status, "completed");
  assert.equal(grounded.grounding.references[0].source, "W3C Web Accessibility Initiative");
  assert.match(grounded.grounding.references[0].sourceUrl, /^https:/);
  assert.deepEqual(grounded.claimLanguage.observed, ["error text appeared"]);
  assert.ok(grounded.claimLanguage.grounded[0].includes("W3C"));
  assert.deepEqual(grounded.alternatives[0].grounding, grounded.grounding.references);
});

test("run enrichment preserves verdict and emits optional UX analysis and evidence-language report", () => {
  const point = pain("pain-1", "ada");
  const run = { runId: "run-ada", profileId: "ada", verdict: "failed", steps: [{ stepId: "step-ada",
    state: { frustration: .4 }, evidence: [{ timestampMs: 10, eyeson: { status: "completed", painPoints: [point] } }] }] };
  const enriched = enrichRun(run);
  assert.equal(enriched.verdict, "failed");
  assert.equal(enriched.uxAnalysis.painPoints[0].id, point.id);
  const markdown = renderMarkdown(enriched);
  for (const label of ["Observed:", "Behavioral effect:", "Inferred:", "Grounded:", "Proposed:"]) assert.ok(markdown.includes(label));
  const html = renderReport(enriched, [enriched]);
  assert.match(html, /Individual user/);
  assert.match(html, /Aggregate root causes/);
  assert.match(html, /Isolated issue/);
  assert.match(html, /params\.set\('view'/);
});
