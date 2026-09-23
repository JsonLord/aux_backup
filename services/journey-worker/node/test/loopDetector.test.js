"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");

const { ALTERNATION_WINDOW, HISTORY_LIMIT, REPEAT_THRESHOLD, actionKey, detectLoop,
  loopNotice } = require("../src/loopDetector");

const item = (type, label) => ({ key: actionKey(type, label), label, type });

test("actionKey pairs the action with what it was called, never the ref", () => {
  assert.equal(actionKey("CLICK", "Pricing"), "CLICK:Pricing");
  assert.equal(actionKey("CLICK", "Pricing"), actionKey("CLICK", "Pricing"),
    "the same control is the same key however many times it is asked");
  assert.notEqual(actionKey("CLICK", "Pricing"), actionKey("TYPE", "Pricing"),
    "a click and a type on the same control are not the same action");
  // Nothing to call it by is still a key, not an exception -- a run with no
  // perception configured still has to be able to track its own repeats.
  assert.equal(actionKey("CLICK", ""), "CLICK:(unnamed)");
});

test("fewer than the threshold is trying, not a pattern yet", () => {
  let recent = [];
  for (const label of ["Pricing", "Pricing"]) {
    const loop = detectLoop(recent, item("CLICK", label));
    recent = loop.pushed;
    assert.equal(loop.repeated, 0, `${recent.length} tries at the same thing is not a loop yet`);
  }
});

test("the same control the threshold-th time is a loop, and keeps being one", () => {
  let recent = [];
  const results = [];
  for (let visit = 1; visit <= 5; visit += 1) {
    const loop = detectLoop(recent, item("CLICK", "Pricing"));
    recent = loop.pushed;
    results.push(loop.repeated);
  }
  assert.deepEqual(results, [0, 0, 3, 4, 5],
    `fires at REPEAT_THRESHOLD (${REPEAT_THRESHOLD}) and grows with every visit after`);
});

test("a different control in between does not reset the count, because the other one is a separate key", () => {
  // The real shape this was built for: Pricing, Start free, Pricing, Start
  // free, Pricing -- "Pricing" itself still occurred three times.
  let recent = [];
  const clicks = ["Pricing", "Start free", "Pricing", "Start free", "Pricing"];
  let last;
  for (const label of clicks) {
    last = detectLoop(recent, item("CLICK", label));
    recent = last.pushed;
  }
  assert.equal(last.repeated, 3, "Pricing recurred three times despite Start free in between");
});

test("A, B, A, B is an alternation; A, B, A alone is only a reconsideration", () => {
  let recent = detectLoop([], item("CLICK", "Pricing")).pushed;
  let loop = detectLoop(recent, item("CLICK", "Start free"));
  recent = loop.pushed;
  loop = detectLoop(recent, item("CLICK", "Pricing"));
  recent = loop.pushed;
  assert.equal(loop.alternating, null, "back once is not yet a cycle");

  loop = detectLoop(recent, item("CLICK", "Start free"));
  assert.deepEqual(loop.alternating, { a: "Pricing", b: "Start free" },
    `back a second time (${ALTERNATION_WINDOW} actions total) completes the cycle`);
});

test("A, B, C, B is not an alternation -- the third action has to be A again", () => {
  let recent = detectLoop([], item("CLICK", "Pricing")).pushed;
  recent = detectLoop(recent, item("CLICK", "Start free")).pushed;
  recent = detectLoop(recent, item("CLICK", "Contact")).pushed;
  const loop = detectLoop(recent, item("CLICK", "Start free"));
  assert.equal(loop.alternating, null, "the middle action differed, so this is not A/B");
});

test("A, A, A is not an alternation -- alternation needs two different things", () => {
  let recent = [];
  let loop;
  for (let visit = 0; visit < 4; visit += 1) {
    loop = detectLoop(recent, item("CLICK", "Pricing"));
    recent = loop.pushed;
  }
  assert.equal(loop.alternating, null, "one control repeated is the repeat case, not alternation");
  assert.ok(loop.repeated >= REPEAT_THRESHOLD);
});

test("the tracked window is bounded, so a control from long ago does not keep a label alive", () => {
  let recent = [];
  recent = detectLoop(recent, item("CLICK", "Pricing")).pushed;
  // Fill the window with enough unrelated clicks to push "Pricing" out of it.
  for (let visit = 0; visit < HISTORY_LIMIT; visit += 1) {
    recent = detectLoop(recent, item("CLICK", `Unrelated ${visit}`)).pushed;
  }
  assert.equal(recent.length, HISTORY_LIMIT, "the window itself stays bounded");
  const loop = detectLoop(recent, item("CLICK", "Pricing"));
  assert.equal(loop.repeated, 0, "the first Pricing click aged out of the window entirely");
});

test("loopNotice says what kind of loop it is, in the persona's own history", () => {
  const alternating = { repeated: 0, alternating: { a: "Pricing", b: "Start free for 30 days" }, label: "" };
  assert.equal(loopNotice(alternating),
    'You keep going back and forth between "Pricing" and "Start free for 30 days" without getting anywhere.');

  const repeated = { repeated: 4, alternating: null, label: "Pricing" };
  assert.equal(loopNotice(repeated), 'You have gone for "Pricing" 4 times now; it has not gotten you anywhere.');

  // Alternation is the more specific diagnosis when a step is both -- the
  // real run's own tail was, briefly, exactly this (see personaDirector's own
  // test for the full sequence).
  const both = { repeated: 3, alternating: { a: "Start free for 30 days", b: "Pricing" }, label: "Pricing" };
  assert.match(loopNotice(both), /going back and forth/);

  assert.equal(loopNotice({ repeated: 0, alternating: null, label: "" }), "",
    "no loop, no notice -- history is not padded with silence");
});

test("the real run this file was built against: an A/B alternation resolving into a repeat", () => {
  // Reconstructed from last_runs/artifacts/journey_log__*.json's
  // journeytest.persona.expectation events (targetName, in order), with the
  // two proposals that were never performed -- coping was "reread" on the
  // step before each -- left out, since a reread that skipped acting never
  // repeated anything. See docs/parallel-development-spec.md's JRN-2 row for
  // the full derivation.
  const sequence = [
    ["CLICK", "Download OpenDesign desktop"],
    ["CLICK", "Download OpenDesign for free. Design with your agent."],
    ["CLICK", "Download OpenDesign free"],
    ["CLICK", "Pricing"],                    // e153
    ["CLICK", "Start free for 30 days"],     // e3
    ["CLICK", "Pricing"],                    // e27
    ["CLICK", "Start free for 30 days"],     // e3
    ["CLICK", "Pricing"],                    // e27
    ["CLICK", "Pricing"],                    // e367 (the e3 reread-skipped in between)
    ["CLICK", "Start free for 30 days"],     // e3
  ];
  const expected = [
    { repeated: 0, alternating: null },
    { repeated: 0, alternating: null },
    { repeated: 0, alternating: null },
    { repeated: 0, alternating: null },
    { repeated: 0, alternating: null },
    { repeated: 0, alternating: null },
    { repeated: 0, alternating: { a: "Pricing", b: "Start free for 30 days" } },
    { repeated: 3, alternating: { a: "Start free for 30 days", b: "Pricing" } },
    { repeated: 4, alternating: null },
    { repeated: 3, alternating: null },
  ];
  let recent = [];
  sequence.forEach(([type, label], index) => {
    const loop = detectLoop(recent, item(type, label));
    recent = loop.pushed;
    assert.equal(loop.repeated, expected[index].repeated, `repeated at step ${index + 1}`);
    assert.deepEqual(loop.alternating, expected[index].alternating, `alternating at step ${index + 1}`);
  });
});
