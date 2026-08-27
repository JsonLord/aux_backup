"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { journeyContract, testerContract } = require("../src/journeytest");

test("maps AUX run input to pinned JourneyTest contracts", () => {
  const profile = {
    id: "persona_1",
    persona: { name: "Ava", occupation: "Researcher", goals: ["Find pricing"] },
    behavior: { patience: 0.4 },
    abilities: { vision: { acuity: 1 } },
  };
  const journey = journeyContract({ runId: "run_1", url: "https://example.com", tasks: ["Find pricing"], profile });
  const tester = testerContract(profile);

  assert.equal(journey.testerProfile, "persona_1");
  assert.equal(journey.app.baseUrl, "https://example.com");
  assert.equal(journey.tasks[0].instruction, "Find pricing");
  assert.deepEqual(journey.evidenceRequirements.map((item) => item.kind), ["screenshot", "snapshot"]);
  assert.equal(tester.name, "Ava");
  assert.match(tester.perspective, /patience/);
});
