"use strict";
/**
 * A persona's turn is one model reply, so what happens when that reply arrives
 * damaged decides whether the run keeps a real thought or invents a fake one.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  ACTION_TYPES, ACTION_VOCABULARY, completionBudget, parseDecision, salvageAction,
} = require("../src/personaActor");

test("a decision cut off mid-sentence keeps what the person actually said", async () => {
  // Discarding it costs the run a turn and produces the "malformed" fallback --
  // a READ nobody chose, which then reads as a real observation in the record.
  const cut = '{"visible": "A page of vision statements, no numbers", '
    + '"expectation": "there is no price here", "action": {"type": "GIVE_UP", "content": "Four pages and not one num';
  const decision = parseDecision(cut);
  assert.equal(decision.action.type, "GIVE_UP");
  assert.equal(decision.visible, "A page of vision statements, no numbers");
  assert.equal(decision.expectation, "there is no price here");
});

test("a fragment with no action at all is still a failure", async () => {
  assert.equal(parseDecision('{"visible": "a page", "expectation": "somethi'), null);
  assert.equal(parseDecision('{"action": {"type": "TELEPORT"}}'), null, "and an action nothing implements");
});

test("the completion budget covers thinking the caller cannot see", () => {
  assert.equal(completionBudget({}), 4096);
  assert.equal(completionBudget({ OPENAI_MAX_COMPLETION_TOKENS: "8192" }), 8192);
  assert.equal(completionBudget({ OPENAI_MAX_COMPLETION_TOKENS: "nonsense" }), 4096);
});

test("a reply wrapped in a code fence or prose is still read", () => {
  const fenced = '```json\n{"visible": "a form", "expectation": "it submits", '
    + '"action": {"type": "CLICK", "target": "e3"}}\n```';
  assert.equal(parseDecision(fenced).action.target, "e3");
  const chatty = 'Sure! {"visible": "a form", "expectation": "it submits", '
    + '"action": {"type": "CLICK", "target": "e3"}} Let me know if you need more.';
  assert.equal(parseDecision(chatty).action.type, "CLICK");
});

test("an action nothing implements is refused however well-formed the reply", () => {
  assert.equal(salvageAction('{"type": "TELEPORT"}').type, "TELEPORT",
    "salvage reports what was said");
  assert.equal(parseDecision('{"action": {"type": "TELEPORT", "target": "mars"}}'), null,
    "and the vocabulary is what decides whether it counts");
  assert.ok(!ACTION_TYPES.includes("TELEPORT"));
  assert.ok(ACTION_VOCABULARY.includes("GIVE_UP"));
});
