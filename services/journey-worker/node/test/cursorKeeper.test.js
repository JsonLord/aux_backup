"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {
  DEFAULT_INTERVAL_MS, OVERLAY_SCRIPT, TRAVEL_STEPS, cursorKeeperStatus, enabled, installOnce,
  pathBetween, readCursorPosition, startCursorKeeper, stopCursorKeeper, travelTo,
  __resetCursorKeeper,
} = require("../src/cursorKeeper");

test.beforeEach(() => __resetCursorKeeper());
test.after(() => stopCursorKeeper());

function recorder(ok = true, stderr = "") {
  const calls = [];
  return { calls, runner: async (commands) => { calls.push(commands); return { ok, stdout: "", stderr }; } };
}

test("the overlay is evaluated into the page, since 0.31.1 ignores init scripts", async () => {
  // Neither AGENT_BROWSER_INIT_SCRIPTS nor `open --init-script` runs the file in
  // the pinned build (verified with a trivial probe), and `eval` does.
  const { calls, runner } = recorder();

  assert.equal(await installOnce(runner), true);
  assert.equal(calls.length, 1);
  const [[command, script]] = calls[0];
  assert.equal(command, "eval");
  assert.equal(script, fs.readFileSync(OVERLAY_SCRIPT, "utf-8"));
});

test("a page that cannot be reached does not stop the keeper", async () => {
  // Between navigations there is a moment with nothing to decorate. That is
  // ordinary, not a reason to give up for the rest of the run.
  const { runner } = recorder(false, "no active page");

  assert.equal(await installOnce(runner), false);
  assert.match(cursorKeeperStatus().error, /no active page/);
});

test("the overlay is put back, because a navigation takes it with the old document", async () => {
  const { calls, runner } = recorder();
  const started = startCursorKeeper({ intervalMs: 15, runner });
  assert.equal(started.running, true);

  await new Promise((resolve) => setTimeout(resolve, 90));
  stopCursorKeeper();

  assert.ok(calls.length >= 3,
    `re-evaluating is what survives a navigation; got ${calls.length} installs`);
  assert.equal(cursorKeeperStatus().running, false);
});

test("it decorates the first page immediately rather than after one interval", async () => {
  const { calls, runner } = recorder();
  startCursorKeeper({ intervalMs: 100000, runner });
  await new Promise((resolve) => setTimeout(resolve, 20));
  stopCursorKeeper();

  assert.equal(calls.length, 1, "waiting a full interval would leave the first page bare");
});

test("it can be turned off, leaving the page untouched", async () => {
  const { calls, runner } = recorder();
  const outcome = startCursorKeeper({ env: { AUX_CURSOR_OVERLAY: "0" }, runner });

  assert.equal(outcome.running, false);
  assert.equal(outcome.reason, "disabled");
  assert.equal(calls.length, 0);
  assert.equal(enabled({ AUX_CURSOR_OVERLAY: "0" }), false);
  assert.equal(enabled({}), true);
});

test("starting twice does not run two timers", async () => {
  const { runner } = recorder();
  startCursorKeeper({ intervalMs: 100000, runner });
  const second = startCursorKeeper({ intervalMs: 100000, runner });
  stopCursorKeeper();

  assert.equal(second.reason, "already-running");
});

test("the interval is frequent enough to matter and cheap enough to ignore", () => {
  assert.ok(DEFAULT_INTERVAL_MS <= 5000, "a bare page for longer than this is noticeable");
  assert.ok(DEFAULT_INTERVAL_MS >= 500, "polling faster than this buys nothing");
});

test("the pointer's last real position survives the navigation that wipes it", async () => {
  __resetCursorKeeper();
  // The page answers with "x,y,width,height" while the overlay is in it.
  const seen = async () => ({ ok: true, stdout: '[{"result":"515,316,1280,633"}]', stderr: "" });
  const live = await readCursorPosition(seen, 1000);
  assert.deepEqual(live, { x: 515, y: 316, viewport: { width: 1280, height: 633 }, stale: false, ageMs: 0 });

  // After a navigation the overlay is gone until the keeper puts it back, and
  // parked off-screen until something moves it -- the probe answers with "".
  const gone = async () => ({ ok: true, stdout: '[{"result":""}]', stderr: "" });
  const remembered = await readCursorPosition(gone, 3500);
  assert.deepEqual(remembered,
    { x: 515, y: 316, viewport: { width: 1280, height: 633 }, stale: true, ageMs: 2500 });

  // And a fresh reading is live again, with the age reset.
  const again = async () => ({ ok: true, stdout: '[{"result":"20,40,1280,633"}]', stderr: "" });
  assert.deepEqual(await readCursorPosition(again, 9000),
    { x: 20, y: 40, viewport: { width: 1280, height: 633 }, stale: false, ageMs: 0 });
});

test("a pointer that has never been seen is reported as absent, not as a guess", async () => {
  __resetCursorKeeper();
  const nothing = async () => ({ ok: true, stdout: '[{"result":""}]', stderr: "" });
  assert.equal(await readCursorPosition(nothing, 1000), null);
  // A page that cannot be reached at all is the same answer.
  const unreachable = async () => ({ ok: false, stdout: "", stderr: "no active page" });
  assert.equal(await readCursorPosition(unreachable, 1000), null);
});

test("a hand moves through the points between two places", () => {
  const points = pathBetween({ x: 0, y: 0 }, { x: 100, y: 0 });
  assert.equal(points.length, TRAVEL_STEPS, "it passes through every step of the way");
  assert.deepEqual(points[points.length - 1], { x: 100, y: 0 }, "and arrives where it was sent");
  // Not a straight line: a hand bows towards the side it came from.
  assert.ok(points.some((point) => point.y !== 0), "a hand does not travel on a rail");
  // Not a constant speed either: it accelerates away from rest and settles.
  const first = Math.hypot(points[0].x, points[0].y);
  const middle = Math.hypot(points[4].x - points[3].x, points[4].y - points[3].y);
  assert.ok(middle > first, "it should be moving faster in the middle than at the start");
  // Going nowhere is not a movement.
  assert.deepEqual(pathBetween({ x: 7, y: 7 }, { x: 7, y: 7 }), []);
});

test("the pointer is sent down the stream when there is one, and into the page when not", async () => {
  const sent = [];
  const streamed = await travelTo({ x: 50, y: 40 },
    { send: (payload) => { sent.push(payload); return { sent: true }; } });
  assert.equal(streamed.moved, true);
  assert.equal(streamed.through, "the viewport stream",
    "the browser's own input pipeline is the only thing a CSS :hover rule listens to");
  assert.equal(sent.length, TRAVEL_STEPS);
  assert.ok(sent.every((item) => item.type === "input_mouse" && item.event === "mousemove"));

  // No stream: the events are dispatched in the page, which still reaches every
  // script listening for pointer movement.
  const commands = [];
  const inPage = await travelTo({ x: 90, y: 90 }, {
    send: () => ({ sent: false }),
    runner: async (batch) => { commands.push(batch); return { ok: true, stdout: "moved", stderr: "" }; },
  });
  assert.equal(inPage.through, "the page");
  assert.equal(commands.length, 1, "one batch, not a round trip per point");
  assert.match(String(commands[0][0][1]), /dispatchEvent\(new MouseEvent\('mousemove'/);
});
