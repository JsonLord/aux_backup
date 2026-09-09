"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const {
  DEFAULT_INTERVAL_MS, OVERLAY_SCRIPT, cursorKeeperStatus, enabled, installOnce,
  startCursorKeeper, stopCursorKeeper, __resetCursorKeeper,
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
