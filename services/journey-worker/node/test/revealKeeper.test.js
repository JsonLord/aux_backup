"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  DEFAULT_SETTLE_MS, MAX_STEPS, enabled, holdRevealKeeper, releaseRevealKeeper, revealHolds,
  revealScript, revealOnce, revealKeeperStatus, startRevealKeeper, stopRevealKeeper,
  __resetRevealKeeper,
} = require("../src/revealKeeper");

test.beforeEach(() => __resetRevealKeeper());
test.afterEach(() => stopRevealKeeper());

function recorder(ok = true, stdout = "", stderr = "") {
  const calls = [];
  return { calls, runner: async (commands) => { calls.push(commands); return { ok, stdout, stderr }; } };
}

const summary = (fields) => `[{"result":${JSON.stringify(JSON.stringify({
  steps: 11, height: 8244, revealable: 28, stillHidden: 0, restoredTo: 0, ...fields }))}}]`;

test("the pass scrolls the whole document and puts the page back where it was", async () => {
  const { calls, runner } = recorder(true, summary());
  const result = await revealOnce(runner);
  assert.equal(result.already, false);
  assert.equal(result.steps, 11);
  assert.equal(result.restoredTo, 0);

  const script = calls[0][0][1];
  // Reads the height every step, because firing a reveal can add more page.
  assert.match(script, /while \(y < root\.scrollHeight/);
  // Restores the scroll position in a finally, so a mid-pass failure cannot
  // leave the run looking at somewhere it never scrolled to.
  assert.match(script, /finally \{\s*window\.scrollTo\(0, startY\)/);
  // Bounded, so an infinite feed cannot hold the run open.
  assert.match(script, new RegExp(`steps < ${MAX_STEPS}`));
});

test("a document that already had its pass costs one round trip and changes nothing", async () => {
  const { runner } = recorder(true, '[{"result":"already"}]');
  assert.deepEqual(await revealOnce(runner), { already: true });
  assert.equal(revealKeeperStatus().passes, 0);
});

test("the page's own smooth scrolling is suspended for the pass and restored", async () => {
  // Without this a page with scroll-behavior:smooth animates every hop, turning
  // the pass into a long visible glide instead of a sweep.
  const script = revealScript();
  assert.match(script, /root\.style\.scrollBehavior = "auto"/);
  assert.match(script, /root\.style\.scrollBehavior = behavior/);
});

test("the pass reports what is still hidden after it, not just that it ran", async () => {
  // The measurement is the point: a real page reported 26 of 28 revealable
  // elements still hidden before any pass, and that number is what says whether
  // the capture about to be taken is worth anything.
  const { runner } = recorder(true, summary({ revealable: 28, stillHidden: 26 }));
  const result = await revealOnce(runner);
  assert.equal(result.revealable, 28);
  assert.equal(result.stillHidden, 26);
  assert.equal(revealKeeperStatus().last.stillHidden, 26);
});

test("a page that cannot be reached yet is not fatal", async () => {
  const { runner } = recorder(false, "", "no active page");
  assert.equal(await revealOnce(runner), null);
  assert.match(revealKeeperStatus().error, /no active page/);
});

test("the keeper can be turned off, and never starts twice", async () => {
  assert.equal(enabled({ AUX_REVEAL_PASS: "0" }), false);
  const { runner } = recorder(true, '[{"result":"already"}]');
  assert.deepEqual(startRevealKeeper({ env: { AUX_REVEAL_PASS: "0" }, runner }),
    { running: false, reason: "disabled" });

  const started = startRevealKeeper({ intervalMs: 100000, runner });
  assert.equal(started.running, true);
  assert.equal(startRevealKeeper({ intervalMs: 100000, runner }).reason, "already-running");
  assert.equal(revealKeeperStatus().running, true);
  stopRevealKeeper();
  assert.equal(revealKeeperStatus().running, false);
});

test("settle time is long enough for a transition to start", () => {
  // A reveal is a CSS transition; asking for its computed opacity in the same
  // frame it was triggered reads the old value.
  assert.ok(DEFAULT_SETTLE_MS >= 100);
});

const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// The keeper fires every 1500ms and a perception pass (snapshot, box walk,
// capture) takes longer than that, so a pass lands between the boxes being read
// and the pixels being captured. Every box is in viewport coordinates, so the
// crops then measure whatever sits at that offset on a page that has moved. A
// live run reported the entire navigation bar as failing WCAG AA at 1:1 -- "the
// region and everything around it are the same flat colour" -- for a persona with
// 0.95 acuity, because the crops had landed on blank page.
test("a held page is not scrolled out from under a measurement", async () => {
  const { calls, runner } = recorder(true, summary());
  startRevealKeeper({ intervalMs: 10, env: { AUX_REVEAL: "1" }, runner });
  await wait(40);
  const beforeHold = calls.length;
  assert.ok(beforeHold >= 1, "the keeper must be scrolling to begin with");

  holdRevealKeeper();
  await wait(60);
  assert.equal(calls.length, beforeHold, "no pass may run while a hold is outstanding");

  releaseRevealKeeper();
  await wait(40);
  assert.ok(calls.length > beforeHold, "the keeper must resume once the hold is released");
});

test("overlapping holds cannot end each other's", async () => {
  const { calls, runner } = recorder(true, summary());
  startRevealKeeper({ intervalMs: 10, env: { AUX_REVEAL: "1" }, runner });
  await wait(30);
  const before = calls.length;

  holdRevealKeeper();
  holdRevealKeeper();
  assert.equal(revealHolds(), 2);
  releaseRevealKeeper();
  assert.equal(revealHolds(), 1);
  await wait(50);
  assert.equal(calls.length, before, "one release must not resume the page for the other holder");

  releaseRevealKeeper();
  assert.equal(revealHolds(), 0);
  await wait(40);
  assert.ok(calls.length > before);
});

test("an unmatched release cannot leave the page permanently scrollable", () => {
  releaseRevealKeeper();
  releaseRevealKeeper();
  assert.equal(revealHolds(), 0, "the count is clamped, so the next hold still holds");
  holdRevealKeeper();
  assert.equal(revealHolds(), 1);
});
