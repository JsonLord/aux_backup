"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { critiqueScreenshot, toPainPoint, buildPrompt, parseFindings } = require("../src/visionCritique");
const { aggregateCohort } = require("../src/aggregate");

test("buildPrompt includes the real element list so findings can reference actual selectors", () => {
  const { user } = buildPrompt({
    url: "https://example.com", task: "Find pricing",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy now", boundingBox: { x: 10, y: 20, width: 80, height: 30 } }],
  });
  assert.match(user, /#buy-button/);
  assert.match(user, /Buy now/);
  assert.match(user, /Find pricing/);
});

test("parseFindings tolerates a markdown-fenced JSON array, normalizes elements/impact/alternatives, and rejects malformed entries", () => {
  const content = "```json\n"
    + '[{"category":"accessibility","severity":"high",'
    + '"elements":[{"elementSelector":"#buy-button","role":"trigger"},{"elementSelector":"#unknown","role":"bogus-role"}],'
    + '"title":"Low contrast","description":"Text fails WCAG AA contrast.",'
    + '"estimatedImpact":{"frustration":0.6,"confusion":"not-a-number","trust":1.4},'
    + '"alternatives":[{"proposedChange":"Darken the text color.","rationale":"Meets WCAG AA.","effort":"low"},{"proposedChange":""}]},'
    + '{"category":"nonsense","severity":"unknown"}]'
    + "\n```";
  const findings = parseFindings(content);
  assert.equal(findings.length, 1); // second top-level entry has no title/description, dropped
  const finding = findings[0];
  assert.equal(finding.category, "accessibility");
  assert.equal(finding.severity, "high");
  assert.equal(finding.elements.length, 2);
  assert.equal(finding.elements[0].role, "trigger");
  assert.equal(finding.elements[1].role, "cause"); // invalid role normalized to a safe default
  assert.equal(finding.estimatedImpact.frustration, 0.6);
  assert.equal(finding.estimatedImpact.confusion, 0); // non-numeric normalized to 0
  assert.equal(finding.estimatedImpact.trust, 1); // out-of-range clamped to 1
  assert.equal(finding.alternatives.length, 1); // the empty-proposedChange entry is dropped
  assert.equal(finding.alternatives[0].effort, "low");
});

test("critiqueScreenshot resolves elements to their real boundingBox and grounds the finding", async (t) => {
  t.mock.method(global, "fetch", async () => ({
    ok: true,
    json: async () => ({ choices: [{ message: { content: JSON.stringify([
      { category: "accessibility", severity: "medium",
        elements: [{ elementSelector: "#buy-button", role: "trigger" }],
        title: "Ambiguous button label", description: "The button text does not describe the action clearly.",
        estimatedImpact: { frustration: 0.3, confusion: 0.5, trust: 0.1 },
        alternatives: [{ proposedChange: "Use a more specific label like 'Complete purchase'.", effort: "low" }] },
    ]) } }] }),
  }));

  const findings = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy", boundingBox: { x: 10, y: 20, width: 80, height: 30 } }],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto" },
  });

  assert.equal(findings.length, 1);
  assert.deepEqual(findings[0].elements[0].box, { x: 10, y: 20, width: 80, height: 30 });
  assert.ok(findings[0].grounding);
  assert.equal(global.fetch.mock.callCount(), 1);
  const [calledUrl, calledInit] = global.fetch.mock.calls[0].arguments;
  assert.equal(calledUrl, "https://router.invalid/v1/chat/completions");
  const sentBody = JSON.parse(calledInit.body);
  assert.equal(sentBody.messages[1].content[1].image_url.url, "data:image/png;base64,Zm9v");
});

test("critiqueScreenshot retries once on a transient failure then succeeds", async (t) => {
  let calls = 0;
  t.mock.method(global, "fetch", async () => {
    calls += 1;
    if (calls === 1) throw new Error("ECONNRESET");
    return { ok: true, json: async () => ({ choices: [{ message: { content: "[]" } }] }) };
  });
  const findings = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item", elements: [],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto", retryWaitMs: 1 },
  });
  assert.deepEqual(findings, []);
  assert.equal(calls, 2);
});

test("critiqueScreenshot requires credentials rather than silently returning fake findings", async () => {
  const originalKey = process.env.OPENAI_API_KEY;
  const originalBlablador = process.env.BLABLADOR_API_KEY;
  delete process.env.OPENAI_API_KEY;
  delete process.env.BLABLADOR_API_KEY;
  try {
    await assert.rejects(
      critiqueScreenshot({ imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [], options: { baseUrl: "https://router.invalid/v1" } }),
      /OPENAI_API_KEY/,
    );
  } finally {
    if (originalKey !== undefined) process.env.OPENAI_API_KEY = originalKey;
    if (originalBlablador !== undefined) process.env.BLABLADOR_API_KEY = originalBlablador;
  }
});

test("toPainPoint shapes a critique finding into the full UXPainPoint record aggregateCohort expects", () => {
  const finding = {
    category: "accessibility", severity: "high", title: "Low contrast form labels",
    description: "Labels are hard to read against the background.",
    elements: [{ elementSelector: "#email-label", role: "trigger", box: { x: 5, y: 10, width: 60, height: 20 } }],
    estimatedImpact: { frustration: 0.4, confusion: 0.6, trust: 0.2 },
    alternatives: [{ proposedChange: "Increase label contrast to meet WCAG AA.", rationale: "Improves readability.", effort: "low" }],
    grounding: { status: "completed", references: [{ source: "W3C Web Accessibility Initiative" }] },
  };
  const painPoint = toPainPoint(finding, { runId: "run1", userId: "persona1", route: "https://example.com",
    stepId: "step-001", screenshotRef: "/tmp/run/screenshots/001.png", videoTimestampMs: 4200 });

  assert.equal(painPoint.runId, "run1");
  assert.equal(painPoint.userId, "persona1");
  assert.deepEqual(painPoint.stepIds, ["step-001"]);
  assert.equal(painPoint.screenshotRef, "/tmp/run/screenshots/001.png");
  assert.equal(painPoint.videoTimestampMs, 4200);
  assert.equal(painPoint.behavioralImpact.frustrationDelta, 0.4);
  assert.equal(painPoint.behavioralImpact.confusionDelta, 0.6);
  assert.equal(painPoint.behavioralImpact.trustDelta, -0.2); // trust erosion is a negative delta
  assert.equal(painPoint.elements[0].elementId, "#email-label");
  assert.equal(painPoint.elements[0].role, "trigger");
  assert.equal(painPoint.elements[0].contribution, 1);
  assert.equal(painPoint.diagnosis.category, "accessibility");
  assert.equal(painPoint.alternatives.length, 1);
  assert.deepEqual(painPoint.alternatives[0].addressesPainPointIds, [painPoint.id]);
  assert.equal(painPoint.overlays.length, 1);
  assert.deepEqual(painPoint.overlays[0].box, { x: 5, y: 10, width: 60, height: 20 });
});

test("vision-critique pain points from different personas aggregate into one synthesized root cause", () => {
  const findingFor = (frustration) => ({
    category: "accessibility", severity: "high", title: "Low contrast form labels",
    description: "Labels are hard to read against the background.",
    elements: [{ elementSelector: "#email-label", role: "trigger", box: { x: 5, y: 10, width: 60, height: 20 } }],
    estimatedImpact: { frustration, confusion: 0.5, trust: 0.1 },
    alternatives: [{ proposedChange: "Increase label contrast.", effort: "low" }],
    grounding: { status: "completed", references: [] },
  });
  const runs = [
    { runId: "run-ada", profileId: "ada", iterationId: "iteration-1", verdict: "passed",
      simulationProfile: { behavior: { patience: 0.8 } },
      painPoints: [toPainPoint(findingFor(0.3), { runId: "run-ada", userId: "ada", route: "https://example.com",
        stepId: "step-1", screenshotRef: "shots/ada-1.png" })] },
    { runId: "run-lin", profileId: "lin", iterationId: "iteration-2", verdict: "passed",
      simulationProfile: { behavior: { patience: 0.2 } },
      painPoints: [toPainPoint(findingFor(0.7), { runId: "run-lin", userId: "lin", route: "https://example.com",
        stepId: "step-1", screenshotRef: "shots/lin-1.png" })] },
  ];
  const rootCauses = aggregateCohort(runs);
  // Same title/elements/category from two different personas collapse into one
  // synthesized root cause instead of two separate per-persona findings.
  assert.equal(rootCauses.length, 1);
  assert.deepEqual(rootCauses[0].affectedUsers.sort(), ["ada", "lin"]);
  assert.equal(rootCauses[0].affectedIterations.length, 2);
  assert.equal(rootCauses[0].averageStateImpact.frustration, 0.5); // (0.3 + 0.7) / 2
});
