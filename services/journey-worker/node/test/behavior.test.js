"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { BehaviorController, abandonTolerance, computeWaitTolerance, copingScores, initialState,
  probabilities, seededRandom } = require("../src/behavior");
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
  // Named rather than counted. "continue" -- getting on with it -- was missing
  // entirely, so every step forced a coping behaviour on a persona who had nothing
  // to cope with: a calm one whose expectation had just been met retried the
  // action that worked 60.3% of the time. Coping is control flow in the director,
  // so those were real wasted steps.
  assert.deepEqual(Object.keys(a2.coping.probabilities).sort(), [
    "abandon", "backtrack", "continue", "explore", "impulsive_retry", "reread", "retry",
    "seek_help", "wait",
  ].sort());
});

test("a person with nothing to cope with gets on with it", () => {
  const calm = new BehaviorController(profile);
  const settled = { ...initialState(), perceivedProgress: 0.5 };
  const easy = probabilities(copingScores(calm.profile, settled, { taskImportance: 0.6 }));

  assert.ok(easy.continue > 0.5, `carrying on should be the common case, got ${easy.continue}`);
  assert.ok(easy.continue > easy.retry, "retrying an action that just worked is not what a person does");
  assert.ok(easy.continue > easy.impulsive_retry + easy.reread + easy.wait);

  // And it gets out of the way the moment there is something to cope with: the
  // rest of this table exists for the person who is stuck.
  const stuck = { ...settled, frustration: 0.6, confusion: 0.5, anger: 0.3, perceivedProgress: 0,
    consecutiveFailures: 2 };
  const hard = probabilities(copingScores(calm.profile, stuck, { taskImportance: 0.6 }));
  assert.ok(hard.continue < 0.1, `a stuck person should be coping, got continue=${hard.continue}`);
  assert.ok(hard.retry + hard.reread > hard.continue * 5);
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

test("abandon tolerance is the documented persistence-scaled formula", () => {
  assert.equal(abandonTolerance({ repeatFailureTolerance: .2, persistence: .25 }), .2 + .25 * .35);
  const normalized = new BehaviorController(profile).profile;
  assert.equal(abandonTolerance(normalized), normalized.repeatFailureTolerance + normalized.persistence * 0.35);
});

test("the abandon boost applies only once tolerance is crossed by more than one failure", () => {
  // JRN-1's gate, checked directly against copingScores rather than through a
  // full run: the three states a run can be in relative to it, each proven
  // by recomputing the plain (unboosted) formula by hand and comparing --
  // not just asserting the boosted score is "different".
  const controllerProfile = new BehaviorController(profile).profile;
  const tolerance = abandonTolerance(controllerProfile);
  const plainAbandon = (state) => state.frustration * 1.3 + state.fatigue * 0.8
    - controllerProfile.persistence * 0.9 - 0.5 * 0.5;

  // Below tolerance, two failures in a row: unaffected.
  const belowTolerance = { ...initialState(), frustration: tolerance - 0.05, fatigue: 0.1, consecutiveFailures: 2 };
  assert.equal(copingScores(controllerProfile, belowTolerance, {}).abandon, plainAbandon(belowTolerance));

  // Above tolerance, but only one failure: the gate needs a second, so still unaffected.
  const oneFailure = { ...initialState(), frustration: tolerance + 0.2, fatigue: 0.1, consecutiveFailures: 1 };
  assert.equal(copingScores(controllerProfile, oneFailure, {}).abandon, plainAbandon(oneFailure));

  // Above tolerance, two failures in a row: both conditions hold, so it boosts --
  // by exactly this file's own documented formula, +1 growing with the excess.
  const crossed = { ...initialState(), frustration: tolerance + 0.2, fatigue: 0.3, consecutiveFailures: 2 };
  const boost = 1 + Math.min(1, Math.max(0, crossed.frustration - tolerance)) * 4;
  const boosted = copingScores(controllerProfile, crossed, {}).abandon;
  assert.equal(boosted, plainAbandon(crossed) + boost);
  assert.ok(boosted > copingScores(controllerProfile, crossed, {}).retry,
    "once boosted, abandon should be competitive with retry, not just nonzero");
});

test("crossing tolerance on a second failure flips the leading coping choice to abandon", () => {
  // The realistic path, through BehaviorController and the same repeated
  // failure() fixture every other test in this file uses -- not a synthetic
  // state object. Before JRN-1, abandon's score never got the boost above at
  // any step, so it stayed a long-shot alongside impulsive_retry/backtrack
  // throughout an identical run (verified separately against the pre-fix
  // formula: p(abandon) peaked under 0.09 and never led). Now the second
  // repeated failure is enough to cross this profile's tolerance (0.2875)
  // and abandon takes over as the clear leader.
  const controller = new BehaviorController(profile);
  const first = controller.apply(failure());
  assert.equal(first.after.consecutiveFailures, 1);
  assert.ok(first.coping.probabilities.abandon < 0.05, "a single failure must not cross tolerance yet");

  const second = controller.apply(failure());
  assert.equal(second.after.consecutiveFailures, 2);
  assert.ok(second.after.frustration > abandonTolerance(controller.profile));
  const [leader] = Object.entries(second.coping.probabilities).sort((a, b) => b[1] - a[1])[0];
  assert.equal(leader, "abandon", `abandon should lead once tolerance is crossed, got ${leader}`);
  assert.ok(second.coping.probabilities.abandon > 0.6);
});

test("apply() can now actually produce abandonment, not just a discarded label", () => {
  // Deterministic, not a probability check: seed 8 on this profile samples
  // "abandon" itself on the second repeated failure, once frustration
  // (0.509) clears tolerance (0.2875) with two failures in a row. Before
  // this fix, apply() computed that exact same crossing and then threw the
  // result away three lines later -- see the comment left on apply() itself
  // -- so state.abandoned could never become true and copingMode could never
  // become "abandoning" through this path, no matter how many failures piled
  // up, because the sampler was never made to prefer it. It now can, and for
  // this seed, does.
  const controller = new BehaviorController({ id: "p_8", behavior: { ...behavior, seed: 8 } });
  controller.apply(failure());
  const second = controller.apply(failure());
  assert.equal(second.coping.decision.type, "abandon");
  assert.equal(second.coping.decision.reason, "frustration and effort exceeded this profile's tolerance");
  assert.equal(second.after.abandoned, true);
  assert.equal(second.after.copingMode, "abandoning");
});

test("with no loop context, coping scores are exactly as before JRN-2", () => {
  const controller = new BehaviorController(profile);
  const stuck = { ...initialState(), frustration: 0.2, confusion: 0.3, anger: 0.1, perceivedProgress: 0,
    consecutiveFailures: 2, fatigue: 0.1 };
  const bare = copingScores(controller.profile, stuck, {});
  const explicitlyNotLooping = copingScores(controller.profile, stuck,
    { loopRepeatCount: 0, loopAlternating: false });
  assert.deepEqual(bare, explicitlyNotLooping);
});

test("a loop -- repeated or alternating -- lifts explore, backtrack and abandon, and suppresses the three that made it", () => {
  const controller = new BehaviorController(profile);
  // Below this profile's own abandon tolerance (0.2875, from the formula
  // test above), so JRN-1's own boost is not also in play here -- isolating
  // what the loop context alone does to the distribution.
  const stuck = { ...initialState(), frustration: 0.2, confusion: 0.3, anger: 0.1, perceivedProgress: 0,
    consecutiveFailures: 2, fatigue: 0.1 };
  assert.ok(stuck.frustration <= abandonTolerance(controller.profile), "fixture must stay below tolerance");
  const base = copingScores(controller.profile, stuck, {});

  for (const loopContext of [{ loopRepeatCount: 3 }, { loopAlternating: true }]) {
    const looping = copingScores(controller.profile, stuck, loopContext);
    // Exact, not approximate: the same six terms this file's own comment on
    // the boost names, nothing else moved.
    const expected = { ...base };
    expected.explore += 1.1; expected.backtrack += 1.1; expected.abandon += 0.7;
    expected.continue -= 0.8; expected.retry -= 0.8; expected.impulsive_retry -= 0.6;
    assert.deepEqual(looping, expected, `${JSON.stringify(loopContext)} should apply exactly this boost`);
  }

  // And the distribution actually moves where it matters: on this fixture,
  // unboosted, seek_help and impulsive_retry tie for the lead (0.217 each) --
  // clicking the same failing thing again, just picked by a coin flip among
  // near-identical options. A loop is direct evidence against exactly that
  // being a good idea.
  const baseLeader = Object.entries(probabilities(base)).sort((a, b) => b[1] - a[1])[0];
  assert.equal(baseLeader[0], "seek_help");
  const loopDist = probabilities(copingScores(controller.profile, stuck, { loopRepeatCount: 3 }));
  const loopLeader = Object.entries(loopDist).sort((a, b) => b[1] - a[1])[0];
  assert.equal(loopLeader[0], "backtrack", "a control that keeps failing should be left, not retried");
  assert.ok(loopDist.impulsive_retry < 0.05,
    `impulsive_retry re-clicks the same thing immediately -- the worst option once a loop is known, `
    + `got ${loopDist.impulsive_retry}`);
});

test("a loop past this profile's abandon tolerance boosts abandon on top of JRN-1's own boost, not instead of it", () => {
  // Calibrated against a real run (docs/parallel-development-spec.md's JRN-2
  // row): boosting explore/backtrack alone, with no share for abandon, took
  // p(abandon) on that run's own last step from 0.615 (JRN-1 alone) down to
  // 0.284 -- diluted by softmax renormalisation exactly where JRN-1 had just
  // made it competitive. Reproduced here on the shared fixture: composing
  // JRN-2's smaller +0.7 with JRN-1's own tolerance-crossing boost must leave
  // abandon at least as strong as JRN-1 alone left it, not weaker.
  const controller = new BehaviorController(profile);
  const pastTolerance = { ...initialState(), frustration: 0.9, confusion: 0.3, anger: 0.1,
    perceivedProgress: 0, consecutiveFailures: 3, fatigue: 0.2 };
  assert.ok(pastTolerance.frustration > abandonTolerance(controller.profile));

  const tolerance = abandonTolerance(controller.profile);
  const abandonOnly = copingScores(controller.profile, pastTolerance, {}).abandon;
  const withLoopToo = copingScores(controller.profile, pastTolerance, { loopRepeatCount: 4 }).abandon;
  const expectedAbandonOnly = pastTolerance.frustration * 1.3 + pastTolerance.fatigue * 0.8
    - controller.profile.persistence * 0.9 - 0.5 * 0.5
    + 1 + Math.min(1, pastTolerance.frustration - tolerance) * 4;
  assert.ok(Math.abs(abandonOnly - expectedAbandonOnly) < 1e-9);
  assert.equal(withLoopToo, abandonOnly + 0.7, "the loop's own share of the boost, added on top");
  assert.ok(withLoopToo > abandonOnly, "a loop found on top of crossed tolerance should not make leaving less likely");
});
