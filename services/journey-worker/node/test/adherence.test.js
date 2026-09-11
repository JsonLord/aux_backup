"use strict";
/**
 * The gate is the difference between a persona and a paragraph of instructions,
 * so what has to be pinned is that it actually rejects, that it does not become
 * a way for the run to fail, and that it does not quietly reject the findings.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const { AdherenceGate, actionBrief, parseScore, personaBrief } = require("../src/adherence");

const FRIEDRICH = {
  persona: { name: "Friedrich Wolf", occupation: "Architect",
    goals: ["Understand quickly whether a tool is worth evaluating"],
    constraints: ["Impatient with vague marketing copy"] },
  behavior: { seed: 7, patience: 0.2, irritability: 0.8 },
};

const READING_ON = { visible: "more marketing copy", expectation: "still no prices",
  action: { type: "READ", target: "the manifesto" } };
const LEAVING = { visible: "more marketing copy", expectation: "there is no price here",
  action: { type: "GIVE_UP", content: "No prices anywhere. Not worth more of my time." } };

function judgeReturning(...replies) {
  const queue = [...replies];
  const asked = [];
  return { asked, judge: async (prompt) => { asked.push(prompt); return queue.shift() ?? queue.at(-1); } };
}

test("an action that does not sound like the person is sent back with the reason", async () => {
  const { judge, asked } = judgeReturning(
    '{"score": 3, "flaw": "an impatient person would not settle in to read a fourth page of copy"}',
    '{"score": 9, "flaw": ""}');
  const gate = new AdherenceGate({ judge });

  let toldWhy = "";
  const settled = await gate.settle(FRIEDRICH, READING_ON, async (flaw) => {
    toldWhy = flaw;
    return LEAVING;
  });

  assert.equal(settled.decision.action.type, "GIVE_UP", "the second attempt is what stands");
  assert.match(toldWhy, /impatient/, "regeneration is told what was wrong, not just that it failed");
  assert.equal(settled.adherence.passed, true);
  assert.equal(settled.adherence.attempts, 2);
  assert.equal(gate.stats.regenerated, 1);
  assert.match(asked[0].user, /patience 0\.20/, "the traits are what it is judged against");
});

test("an action that already fits is not regenerated, because that costs a call every step", async () => {
  const { judge } = judgeReturning('{"score": 9, "flaw": ""}');
  const gate = new AdherenceGate({ judge });
  let regenerated = false;

  const settled = await gate.settle(FRIEDRICH, LEAVING, async () => { regenerated = true; return LEAVING; });

  assert.equal(regenerated, false);
  assert.equal(gate.stats.passedFirst, 1);
  assert.equal(settled.adherence.attempts, 1);
});

test("when nothing clears the bar the last attempt stands, not the first", async () => {
  // TinyTroupe's choice and the right one: the final attempt has been through
  // the most criticism, and refusing to act is not something a person does.
  const { judge } = judgeReturning('{"score": 2, "flaw": "too patient"}', '{"score": 4, "flaw": "still too patient"}');
  const gate = new AdherenceGate({ judge, maxAttempts: 2 });

  const settled = await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);

  assert.equal(settled.decision.action.type, "GIVE_UP");
  assert.equal(settled.adherence.passed, false, "and it is recorded as not having passed");
  assert.equal(gate.stats.keptDespiteFailing, 1);
});

test("a judge that is unreachable leaves the action exactly as it was", async () => {
  // The gate improves a persona; it is not something a run depends on.
  const gate = new AdherenceGate({ judge: async () => { throw new Error("connection refused"); } });
  const settled = await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);

  assert.equal(settled.decision, READING_ON);
  assert.equal(settled.adherence, null);
  assert.equal(gate.stats.judged, 0);
});

test("a judge that answers with prose rather than a score is treated as no answer", async () => {
  const gate = new AdherenceGate({ judge: async () => "I think this is broadly fine, honestly." });
  const settled = await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  assert.equal(settled.adherence, null);
  assert.equal(settled.decision, READING_ON);
});

test("with no judge configured the gate is simply off", async () => {
  const gate = new AdherenceGate({});
  assert.equal(gate.enabled, false);
  const settled = await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  assert.equal(settled.decision, READING_ON);
});

test("a score is read out of a reply that wraps it in anything", () => {
  assert.deepEqual(parseScore('```json\n{"score": 8, "flaw": ""}\n```'), { score: 8, flaw: "" });
  assert.deepEqual(parseScore('Here you go: {"score": 11, "flaw": "x"} hope that helps'),
    { score: 10, flaw: "x" }, "out of range is clamped rather than believed");
  assert.equal(parseScore("no json here"), null);
  assert.equal(parseScore('{"flaw": "no score at all"}'), null);
});

test("a constraint written as a whole sentence is not given a prefix that repeats it", () => {
  assert.match(personaBrief(FRIEDRICH), /True of them: Impatient with vague marketing copy/);
  assert.doesNotMatch(personaBrief(FRIEDRICH), /Impatient with: Impatient with/);
});

test("the judge sees what they said they could see, not just the action", () => {
  // An action is only off-persona relative to what the person believed was in
  // front of them: giving up is right on a page with no prices and wrong on a
  // pricing table.
  const brief = actionBrief(READING_ON);
  assert.match(brief, /more marketing copy/);
  assert.match(brief, /still no prices/);
  assert.match(brief, /READ the manifesto/);
});

test("a judgement cut off mid-sentence still yields its score", async () => {
  // Measured against the router: this reply came back finish_reason=length after
  // 29 completion tokens against a budget of 800, because the model spent 767 on
  // reasoning that is never returned. The score was complete and correct; only
  // the sentence explaining it was truncated, and JSON.parse threw away both.
  const cut = '{"score": 0, "flaw": "His impatience makes reading a whole philosophy section after four';
  const judged = parseScore(cut);
  assert.equal(judged.score, 0);
  assert.match(judged.flaw, /impatience/, "a truncated reason is still enough to regenerate against");
  assert.equal(judged.truncated, true);

  // And it reaches the gate, rather than reading as a judge that is not there.
  const gate = new AdherenceGate({ judge: async () => cut });
  const settled = await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  assert.equal(settled.decision.action.type, "GIVE_UP");
});

test("a judge that keeps failing is stopped, and says why", async () => {
  // A missing key for the second endpoint 401s every step. Swallowing each one
  // is right; swallowing them forever is how a run looks fine while nothing
  // ever held the persona to itself.
  const gate = new AdherenceGate({ judge: async () => { throw new Error("HTTP 401: bad token"); } });

  await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  assert.equal(gate.enabled, true, "one failure is tolerated");
  await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  assert.equal(gate.enabled, false);
  assert.match(gate.unavailableReason, /401/);
});

test("a judge that answers prose twice is also treated as absent", async () => {
  const gate = new AdherenceGate({ judge: async () => "Looks fine to me!" });
  await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  await gate.settle(FRIEDRICH, READING_ON, async () => LEAVING);
  assert.equal(gate.enabled, false);
  assert.match(gate.unavailableReason, /carried no score/);
});

test("a success clears the count, so an occasional blip does not disable it", async () => {
  let call = 0;
  const gate = new AdherenceGate({ judge: async () => {
    call += 1;
    if (call === 1 || call === 3) throw new Error("timeout");
    return '{"score": 9, "flaw": ""}';
  } });
  for (let step = 0; step < 4; step += 1) await gate.settle(FRIEDRICH, LEAVING, async () => LEAVING);
  assert.equal(gate.enabled, true);
});

test("a rejected action is kept with the reason it was rejected", async () => {
  // A rejected action and the sentence explaining why it did not sound like this
  // person is the most informative training example the gate produces -- a
  // labelled negative nobody had to write. Keeping only {score, flaw} threw the
  // action away, leaving a corpus made entirely of actions that had already
  // passed, which teaches an optimiser very little.
  const answers = [
    JSON.stringify({ score: 3, flaw: "Far too patient for them" }),
    JSON.stringify({ score: 9, flaw: "" }),
  ];
  const gate = new AdherenceGate({ judge: async () => answers.shift() });
  const first = { action: { type: "READ", target: "e1" }, expectation: "read it all" };
  const second = { action: { type: "CLICK", target: "e7" }, expectation: "get to the price" };

  const settled = await gate.settle({ persona: { name: "Friedrich" } }, first, async () => second);

  assert.equal(settled.adherence.passed, true);
  assert.equal(settled.decision.action.type, "CLICK");
  // Both attempts are on the record, each with the action it was about.
  assert.equal(settled.adherence.history.length, 2);
  assert.deepEqual(settled.adherence.history[0].action, { type: "READ", target: "e1" });
  assert.equal(settled.adherence.history[0].score, 3);
  assert.equal(settled.adherence.history[0].flaw, "Far too patient for them");
  assert.deepEqual(settled.adherence.history[1].action, { type: "CLICK", target: "e7" });
});
