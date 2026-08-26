"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { analyzeEvidence } = require("../src/index");
const { NullUXKnowledgeProvider, groundPainPoint } = require("../src/knowledge");
const { renderReport } = require("../src/report");

test("analysis preserves step, timestamp, screenshot, and stable element attribution", () => {
  const evidence = { schemaVersion: "1.0", id: "ev1", runId: "run1", stepId: "step1", timestampMs: 4100,
    screenshot: { artifactId: "art_screen", kind: "evidence.screenshot" },
    elementMap: { elements: [{ id: "submit", role: "button" }] },
    behavior: { before: { frustration: .1 }, after: { frustration: .4 } } };
  const result = analyzeEvidence(evidence);
  assert.equal(result.stepId, evidence.stepId);
  assert.equal(result.timestampMs, evidence.timestampMs);
  assert.deepEqual(result.screenshot, evidence.screenshot);
  assert.deepEqual(result.findings[0].elementIds, ["submit"]);
  assert.deepEqual(result.findings[0].evidenceRefs, ["art_screen"]);
});

test("fixture error highlights the acted element with traceable behavioral impact and alternatives", () => {
  const before = { frustration: .1, confusion: .1, trust: .9, cognitiveEffort: .1,
    physicalEffort: 0, elapsedMs: 100, consecutiveFailures: 0 };
  const after = { frustration: .5, confusion: .3, trust: .7, cognitiveEffort: .3,
    physicalEffort: 0, elapsedMs: 500, consecutiveFailures: 1 };
  const evidence = { schemaVersion: "1.0", id: "ev_error", runId: "run1", userId: "user1",
    stepId: "step_error", timestampMs: 9200, action: { type: "click", elementId: "submit" },
    screenshot: { artifactId: "art_error", kind: "evidence.screenshot" },
    elementMap: { elements: [{ id: "submit", role: "button", box: { x: 10, y: 20, width: 100, height: 40 } }] },
    behavior: { before, after, events: [{ type: "validation_failure", repeatKey: "checkout-submit",
      goalBlocked: true, classifierConfidence: .95 }], coping: { type: "retry" } } };
  const result = analyzeEvidence(evidence, { generateVisualSolutions: true });
  const pain = result.painPoints[0];
  assert.equal(pain.screenshotRef, "art_error");
  assert.deepEqual(pain.stepIds, ["step_error"]);
  assert.equal(pain.elements[0].elementId, "submit");
  assert.deepEqual(pain.overlays[0].box, evidence.elementMap.elements[0].box);
  assert.equal(pain.behavioralImpact.frustrationDelta, .4);
  assert.ok(pain.alternatives.length >= 1);
  assert.ok(pain.alternatives.every((item) => item.addressesPainPointIds.includes(pain.id)));
  assert.equal(pain.alternatives[0].visualAlternative.originalScreenshotRef, "art_error");
});

test("null knowledge provider reports not configured without failing", async () => {
  const result = await groundPainPoint({ diagnosis: { category: "feedback" }, elements: [] },
    new NullUXKnowledgeProvider());
  assert.deepEqual(result, { status: "not_configured", references: [] });
});

test("two-mode report keeps run, user, and step in query state and exposes screenshot toggle", () => {
  const html = renderReport({ runId: "run1", profileId: "user1", steps: [{ stepId: "step1",
    state: { frustration: .2 }, evidence: [{ screenshot: { artifactId: "original" },
      perceivedScreenshot: { artifactId: "perceived" }, eyeson: { painPoints: [] } }] }] });
  assert.match(html, /User Journey/);
  assert.match(html, /UX Feedback/);
  assert.match(html, /Show perceived screenshot/);
  assert.match(html, /params\.set\('run'/);
  assert.match(html, /params\.set\('user'/);
  assert.match(html, /params\.set\('step'/);
  assert.match(html, /params\.set\('timestamp'/);
});
