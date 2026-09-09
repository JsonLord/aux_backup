"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  beginTakeover, endTakeover, noteInput, takeoverActive, takeoverState, __resetTakeover,
} = require("../src/takeover");

test.beforeEach(() => __resetTakeover());

test("input is refused until the browser is actually handed over", () => {
  // An agent mid-action and a person clicking are two hands on the same pointer,
  // and the run is then evidence of neither one's behaviour.
  assert.equal(takeoverActive(), false);
  beginTakeover({ runId: "run_1", reason: "challenge" });
  assert.equal(takeoverActive(), true);
  endTakeover();
  assert.equal(takeoverActive(), false);
});

test("a second request joins the handover rather than starting a rival one", () => {
  const first = beginTakeover({ runId: "run_1", reason: "second factor" });
  const second = beginTakeover({ runId: "run_1", reason: "challenge" });

  assert.equal(second.alreadyActive, true);
  assert.equal(second.takeoverId, first.takeoverId);
  assert.equal(second.reason, "second factor", "the original reason stands");
});

test("the record says how much of a run was done by hand", () => {
  // A step a person completed is not a step the product afforded, so a reader
  // has to be able to tell them apart.
  beginTakeover({ runId: "run_1", reason: "challenge", url: "https://shop.example.com" });
  noteInput(); noteInput(); noteInput();

  const finished = endTakeover();
  assert.equal(finished.events, 3);
  assert.equal(finished.runId, "run_1");
  assert.equal(finished.url, "https://shop.example.com");
  assert.ok(finished.startedAt && finished.endedAt);
});

test("handovers stay in the record after they end", () => {
  beginTakeover({ runId: "run_1", reason: "second factor" });
  endTakeover();
  beginTakeover({ runId: "run_2", reason: "challenge" });

  const state = takeoverState();
  assert.equal(state.active.runId, "run_2");
  assert.equal(state.recent.length, 1);
  assert.equal(state.recent[0].runId, "run_1");
});

test("counting input while nobody has taken over is harmless", () => {
  noteInput();
  assert.equal(takeoverState().active, null);
});

test("ending a handover nobody started is not an error", () => {
  assert.equal(endTakeover(), null);
});
