"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { perceivedScreenshot, materializePerceivedArtifact, readingDurationMs, filterWorkingMemory, simulatePointer } = require("../src/physical");
const { replayFromEvidence } = require("../src/replay");

const abilities = { vision: { colorVision: "deuteranopia", acuity: .6, contrastSensitivity: .7 },
  motor: { pointerPrecision: .4 }, cognition: { workingMemoryItems: 2 }, reading: { wordsPerMinute: 120 } };

test("perceptual artifact preserves its original reference and reproducible transform", () => {
  const original = { artifactId: "screen_1", kind: "evidence.screenshot", contentType: "image/png" };
  const first = perceivedScreenshot(original, abilities, 11);
  assert.deepEqual(first, perceivedScreenshot(original, abilities, 11));
  assert.equal(first.sourceArtifactId, original.artifactId);
  assert.equal(first.transform.colorVision, "deuteranopia");
  assert.equal(first.transform.blurPx, 1.2);
});

test("perceived pixels can be materialized through the artifact boundary", async () => {
  const writes = [];
  const original = { artifactId: "screen-1", url: "https://artifacts.invalid/screen.png", width: 800, height: 600 };
  const ref = await materializePerceivedArtifact(original, abilities, 4, async (artifact) => {
    writes.push(artifact);
    return { artifactId: "perceived-1", kind: artifact.kind, contentType: artifact.contentType };
  });
  assert.equal(ref.artifactId, "perceived-1");
  assert.equal(writes[0].metadata.sourceArtifactId, "screen-1");
  assert.match(writes[0].content, /feColorMatrix/);
  assert.match(writes[0].content, /feGaussianBlur/);
});

test("stored evidence replays behavior without a browser", () => {
  const profile = { id: "persona-1", behavior: { seed: 17, patience: .4, persistence: .6,
    irritability: .5, angerReactivity: .5, angerRecovery: .4, impulsivity: .3,
    repeatFailureTolerance: .4, selfEfficacy: .6, helpSeeking: .4 } };
  const event = { type: "validation_failure", severity: .8, goalBlocked: true,
    progressVisible: false, repeatKey: "submit", attribution: { interface: 1 } };
  const input = { replayId: "replay-1", sourceRunId: "run-1", profile, evidence: [{ event }, { event }] };
  assert.deepEqual(replayFromEvidence(input), replayFromEvidence(input));
  assert.equal(replayFromEvidence(input).mode, "evidence_without_browser");
  assert.equal(replayFromEvidence(input).transitions.length, 2);
});

test("reading, memory, and motor effects are executable and seeded", () => {
  assert.equal(readingDurationMs("one two three four", abilities), 2000);
  assert.deepEqual(filterWorkingMemory(["a", "b", "c"], abilities), ["b", "c"]);
  const target = { x: 10, y: 20, width: 100, height: 40 };
  assert.deepEqual(simulatePointer(target, abilities, 7), simulatePointer(target, abilities, 7));
  assert.notDeepEqual(simulatePointer(target, abilities, 7), simulatePointer(target, abilities, 8));
});
