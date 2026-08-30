"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { mkdtemp, mkdir, writeFile } = require("node:fs/promises");
const { tmpdir } = require("node:os");
const path = require("node:path");

const { liveRunState, findRunDirectory, directoryStartedAt, safeId } = require("../src/liveRun");
const { startRunCapture, takeRunReasoning } = require("../src/reasoningCapture");

// A 1x1 PNG, so the frame really decodes.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64");

async function runTree(startedAtIso, runId, frames) {
  const root = await mkdtemp(path.join(tmpdir(), "live-"));
  const directory = path.join(root, "journeys", `${startedAtIso}-${safeId(runId)}`, "screenshots");
  await mkdir(directory, { recursive: true });
  for (const name of frames) {
    await writeFile(path.join(directory, name), PNG);
    await new Promise((resolve) => setTimeout(resolve, 12)); // distinct mtimes
  }
  return root;
}

test("a run in flight reports its newest frame and the thinking so far", async () => {
  const runId = "job_abc123def456ghi789jkl_persona_1";
  const root = await runTree("2026-08-30T14-58-52-774Z", runId,
    ["initial-view.png", "001-click-e1-before.png", "001-click-e1-after.png"]);
  startRunCapture(runId, { outputDir: root });
  try {
    const state = await liveRunState(runId);
    assert.equal(state.status, "live");
    assert.equal(state.frames, 3);
    assert.equal(state.frameName, "001-click-e1-after.png", "the newest capture, not the first");
    assert.ok(state.frame.startsWith("data:image/png;base64,"));
    assert.ok(Number.isFinite(state.elapsedMs));
  } finally {
    takeRunReasoning(runId);
  }
});

test("a finished run is reported as finished rather than as an error", async () => {
  const state = await liveRunState("a-run-that-was-never-registered");
  assert.equal(state.status, "finished");
  assert.equal(state.frames, 0);
  assert.deepEqual(state.reasoning, []);
});

test("personas of one job share a directory suffix and are told apart by start time", async () => {
  // safeId truncates to 24 characters, and this deployment's run ids are
  // `<jobId>_<personaId>` -- so both personas of a job produce the same suffix.
  const first = "job_924d4c5e15944e699204_persona_a";
  const second = "job_924d4c5e15944e699204_persona_b";
  assert.equal(safeId(first), safeId(second), "the suffix really is ambiguous");

  const root = await mkdtemp(path.join(tmpdir(), "live-"));
  const early = `2026-08-30T14-58-52-774Z-${safeId(first)}`;
  const late = `2026-08-30T15-02-46-493Z-${safeId(second)}`;
  for (const [name, frame] of [[early, "early.png"], [late, "late.png"]]) {
    const directory = path.join(root, "journeys", name, "screenshots");
    await mkdir(directory, { recursive: true });
    await writeFile(path.join(directory, frame), PNG);
  }

  const earlyAt = directoryStartedAt(early);
  const lateAt = directoryStartedAt(late);
  assert.ok(earlyAt && lateAt && lateAt > earlyAt);

  assert.equal(path.basename(await findRunDirectory(root, first, earlyAt)), early);
  assert.equal(path.basename(await findRunDirectory(root, second, lateAt)), late);
});

test("a registered run whose frames have not landed yet is still live", async () => {
  const runId = "job_nothing_written_yet";
  const root = await mkdtemp(path.join(tmpdir(), "live-"));
  startRunCapture(runId, { outputDir: root });
  try {
    const state = await liveRunState(runId);
    assert.equal(state.status, "live");
    assert.equal(state.frames, 0);
    assert.equal(state.frame, null);
  } finally {
    takeRunReasoning(runId);
  }
});
