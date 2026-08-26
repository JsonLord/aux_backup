"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { BehaviorController } = require("../src/behavior");
const { runJourney } = require("../src/index");

const profile = { id: "p1", behavior: { irritability: .8, angerRecovery: .2, failureTolerance: .4, repeatFailureTolerance: .2, persistence: .3, helpSeeking: .8 } };

test("behavior transitions are deterministic", () => {
  const controller = new BehaviorController(profile);
  assert.deepEqual(controller.apply({ outcome: "failure" }), { frustration: .31, trust: .9, effort: .2, failures: 1, abandoned: false });
  assert.equal(controller.copingDecision(), "seek_help");
});

test("run attaches the simulation profile and events", async () => {
  const result = await runJourney({ url: "https://example.com", tasks: ["Find support"], profile, runId: "run_fixture" });
  assert.equal(result.steps.length, 1);
  assert.equal(result.events[1].type, "experience.event.created");
  assert.deepEqual(result.simulationProfile, profile);
});
