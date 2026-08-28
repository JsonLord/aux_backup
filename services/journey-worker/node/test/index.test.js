"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { timelineToEvents } = require("../src/index");

test("live JourneyTest timeline maps to real per-action events, not an always-empty step loop", () => {
  // Regression test: journeytest-core's real RunResult has no `.steps` field (see
  // core/schemas.ts RunResultSchema in @baguette-studios/journeytest-core), so a
  // previous `for (const step of result.steps || [])` loop silently never ran for
  // live runs. Events must instead come from the real `timeline` the director
  // actually recorded.
  const timeline = [
    { id: "t1", type: "action.click", wallTime: "2026-08-28T10:00:00.000Z", elapsedMs: 1200, taskId: "task-1", summary: "Clicked 'Buy now'" },
    { id: "t2", type: "observation", wallTime: "2026-08-28T10:00:05.000Z", elapsedMs: 6200, taskId: "task-1", summary: "Spinner visible for 5s", data: { spinnerMs: 5000 } },
  ];

  const events = timelineToEvents(timeline, "run_abc");

  assert.equal(events.length, 2);
  assert.equal(events[0].type, "journeytest.action.click");
  assert.equal(events[0].runId, "run_abc");
  assert.equal(events[0].timestamp, "2026-08-28T10:00:00.000Z");
  assert.equal(events[0].data.taskId, "task-1");
  assert.equal(events[0].data.summary, "Clicked 'Buy now'");
  assert.equal(events[1].type, "journeytest.observation");
  assert.equal(events[1].data.spinnerMs, 5000);
});

test("timelineToEvents tolerates a missing/empty timeline", () => {
  assert.deepEqual(timelineToEvents(undefined, "run_1"), []);
  assert.deepEqual(timelineToEvents([], "run_1"), []);
});
