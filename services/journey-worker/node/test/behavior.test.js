"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { BehaviorController, computeWaitTolerance, initialState, seededRandom } = require("../src/behavior");
const { EvidenceCoordinator } = require("../src/evidence");
const { runJourney } = require("../src/index");

const behavior = { seed: 19, patience: .2, persistence: .25, irritability: .8, angerReactivity: .8,
  angerRecovery: .2, impulsivity: .7, failureTolerance: .4, repeatFailureTolerance: .2,
  selfEfficacy: .4, helpSeeking: .8, exploration: .3, verificationTendency: .6 };
const profile = { id: "p1", behavior };
const failure = (repeatKey = "submit") => ({ type: "validation_failure", severity: .8, goalBlocked: true,
  progressVisible: false, repeatKey, attribution: { interface: .8, user: .2 }, evidenceRefs: [] });

test("state transitions are deterministic and repeated failures escalate", () => {
  const first = new BehaviorController(profile);
  const second = new BehaviorController(profile);
  const a1 = first.apply(failure());
  const a2 = first.apply(failure());
  assert.deepEqual(a1, second.apply(failure()));
  assert.deepEqual(a2, second.apply(failure()));
  assert.ok(a2.after.frustration - a1.after.frustration > a1.after.frustration);
  assert.equal(a2.after.repeatedEventCounts.submit, 2);
  assert.equal(Object.keys(a2.coping.probabilities).length, 8);
});

test("visible progress raises an auditable wait threshold", () => {
  const state = initialState();
  const blank = computeWaitTolerance(behavior, state, { progressVisible: false });
  const progress = computeWaitTolerance(behavior, state, { progressVisible: true });
  assert.ok(progress.thresholdMs > blank.thresholdMs);
  assert.equal(progress.version, "wait-tolerance-v1");
});

test("successful recovery reduces emotional state", () => {
  const controller = new BehaviorController(profile);
  const failed = controller.apply(failure()).after;
  const recovered = controller.apply({ type: "recovery", severity: 0, goalBlocked: false,
    progressVisible: true, recoveryQuality: 1, evidenceRefs: [] }).after;
  assert.ok(recovered.frustration < failed.frustration);
  assert.ok(recovered.anger < failed.anger);
  assert.equal(recovered.consecutiveFailures, 0);
});

test("seeded sampling is reproducible and profile-sensitive", () => {
  const firstRandom = seededRandom(4);
  const secondRandom = seededRandom(4);
  assert.deepEqual([firstRandom(), firstRandom(), firstRandom()], [secondRandom(), secondRandom(), secondRandom()]);
  const patient = new BehaviorController({ id: "patient", behavior: { ...behavior, seed: 5, patience: 1, persistence: 1 } });
  const impatient = new BehaviorController({ id: "impatient", behavior: { ...behavior, seed: 5, patience: 0, persistence: 0, irritability: 1 } });
  const a = patient.apply(failure()).coping.probabilities;
  const b = impatient.apply(failure()).coping.probabilities;
  assert.ok(a.wait > b.wait);
  assert.ok(a.retry > b.retry);
});

test("fixture profiles select reproducibly different coping behavior", () => {
  const persistent = { id: "persistent", behavior: { ...behavior, seed: 1, patience: 1, persistence: 1,
    irritability: 0, impulsivity: 0, helpSeeking: 0, selfEfficacy: 1 } };
  const impulsive = { id: "impulsive", behavior: { ...behavior, seed: 1, patience: 0, persistence: 0,
    irritability: 1, impulsivity: 1, helpSeeking: 0, selfEfficacy: 0 } };
  const persistentDecision = new BehaviorController(persistent).apply(failure()).coping.decision.type;
  const impulsiveDecision = new BehaviorController(impulsive).apply(failure()).coping.decision.type;
  assert.equal(persistentDecision, "retry");
  assert.equal(impulsiveDecision, "impulsive_retry");
});

test("run persists transitions, probability distributions, and exact profile", async () => {
  const result = await runJourney({ url: "https://example.com", tasks: ["Submit"], profile,
    experienceEvents: [failure()], runId: "run_fixture" });
  assert.equal(result.steps.length, 1);
  assert.equal(result.events[1].type, "experience.event.created");
  assert.equal(result.events[3].type, "behavior.coping.selected");
  assert.equal(result.steps[0].waitTolerance.version, "wait-tolerance-v1");
  assert.ok(result.steps[0].copingProbabilities.retry > 0);
  assert.deepEqual(result.simulationProfile, profile);
});

test("selected screenshot is queued with exact map and transition and findings reattach to its timestamp", async () => {
  const received = [];
  const coordinator = new EvidenceCoordinator({ analyze: async (evidence) => {
    received.push(evidence);
    return { analysisId: "analysis_1", findings: [{ id: "finding_1", elementIds: ["submit"] }] };
  } });
  const screenshot = { artifactId: "artifact_screen_1", kind: "evidence.screenshot", contentType: "image/png" };
  const elementMap = { elements: [{ id: "submit", role: "button", label: "Submit order" }] };
  const result = await runJourney({ url: "https://example.com", tasks: ["Submit"], profile,
    experienceEvents: [failure()], stepEvidence: [{ id: "evidence_1", timestampMs: 4200,
      screenshot, elementMap, action: { type: "click", elementId: "submit" } }], runId: "run_evidence" },
  { evidenceCoordinator: coordinator });
  assert.equal(received.length, 1);
  assert.deepEqual(received[0].screenshot, screenshot);
  assert.deepEqual(received[0].elementMap, elementMap);
  assert.deepEqual(received[0].behavior.after, result.steps[0].state);
  assert.equal(result.steps[0].evidence[0].timestampMs, 4200);
  assert.equal(result.steps[0].evidence[0].screenshot.artifactId, "artifact_screen_1");
  assert.equal(result.steps[0].evidence[0].perceivedScreenshot.sourceArtifactId, "artifact_screen_1");
  assert.equal(result.steps[0].evidence[0].eyeson.findings[0].id, "finding_1");
  const completed = result.events.find((event) => event.type === "ux.analysis.completed");
  assert.equal(completed.data.stepId, result.steps[0].stepId);
  assert.equal(completed.data.timestampMs, 4200);
});
