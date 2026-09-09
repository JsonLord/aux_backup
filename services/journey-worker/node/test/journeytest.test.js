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

test("every criterion states the result vocabulary journey_finish accepts", () => {
  // journeytest-core validates verdict.criteria[].result against a union of four
  // literals, but its director prompt never names them -- it only tells the model
  // to prefer "inconclusive" when evidence is weak, which is a verdict *status*.
  // A live run answered with status words and journey_finish was rejected
  // ("must be equal to constant" per literal, then "must match a schema in
  // anyOf"), aborting the journey with no verdict at all.
  const journey = journeyContract({
    runId: "run_1", url: "https://example.com", tasks: ["Find pricing"],
    profile: { id: "persona_1", persona: {}, behavior: {}, abilities: {} },
  });

  for (const criterion of [...journey.passCriteria, ...journey.failCriteria]) {
    for (const allowed of ["met", "not-met", "blocked", "not-observed"]) {
      assert.ok(criterion.statement.includes(`"${allowed}"`),
        `${criterion.id} must name the allowed result "${allowed}"`);
    }
    // The words the model reached for instead have to be ruled out by name.
    assert.match(criterion.statement, /never "passed", "failed", or "inconclusive"/);
  }

  // The criterion must still read as its own statement, not only as vocabulary.
  assert.match(journey.passCriteria[0].statement, /^The requested tasks can be completed\./);
  assert.match(journey.failCriteria[0].statement, /^A requested task cannot be completed\./);
});
