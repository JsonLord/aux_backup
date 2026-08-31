"use strict";
/**
 * What a still-running journey can show while it runs.
 *
 * The recording cannot: journeytest-core finalizes the WebM when the run ends, so
 * there is no video to stream mid-flight. Two things do exist during the run --
 * the screenshots the driver writes to disk as it goes, and the model's reasoning
 * tokens (reasoningCapture.js holds them in memory as they arrive) -- and between
 * them they are the run: what the agent is looking at, and what it is thinking
 * about it.
 *
 * Frames are read from the run's own output directory. journeytest-core names it
 * `<outputDir>/journeys/<ISO timestamp>-<safeId(runId)>`, and safeId truncates to
 * 24 characters -- which for this deployment's `<jobId>_<personaId>` run ids means
 * every persona of one job produces the *same* suffix. The registered start time
 * disambiguates them: a run's directory is the one whose timestamp is closest to
 * when that run began.
 */

const { readdir, readFile, stat } = require("node:fs/promises");
const path = require("node:path");

const { getRunContext, peekRunReasoning } = require("./reasoningCapture");

// journeytest-core's own safeId(): non-portable characters replaced, capped at 24.
function safeId(value, fallback = "run") {
  const normalized = String(value || fallback).replace(/[^a-zA-Z0-9._-]/g, "-");
  return (normalized || fallback).slice(0, 24);
}

/** The ISO timestamp journeytest-core prefixes a run directory with. */
function directoryStartedAt(name) {
  const match = name.match(/^(\d{4}-\d{2}-\d{2}T[\d-]+Z)-/);
  if (!match) return null;
  // "2026-08-30T14-58-52-774Z" -> a parseable ISO string.
  const iso = match[1].replace(/T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z$/, "T$1:$2:$3.$4Z");
  const parsed = Date.parse(iso);
  return Number.isFinite(parsed) ? parsed : null;
}

async function findRunDirectory(outputDir, runId, startedAt) {
  const journeys = path.join(outputDir, "journeys");
  let entries;
  try {
    entries = await readdir(journeys, { withFileTypes: true });
  } catch {
    return null;
  }
  const suffix = `-${safeId(runId)}`;
  const candidates = entries
    .filter((entry) => entry.isDirectory() && entry.name.endsWith(suffix))
    .map((entry) => ({ name: entry.name, at: directoryStartedAt(entry.name) }))
    .filter((entry) => entry.at !== null);
  if (!candidates.length) return null;
  // Several personas of one job share the suffix; the one that began nearest this
  // run's registered start is this run's.
  candidates.sort((left, right) => Math.abs(left.at - startedAt) - Math.abs(right.at - startedAt));
  return path.join(journeys, candidates[0].name);
}

async function latestScreenshot(runDirectory) {
  const directory = path.join(runDirectory, "screenshots");
  let names;
  try {
    names = (await readdir(directory)).filter((name) => name.endsWith(".png"));
  } catch {
    return { frames: 0, frame: null, name: null };
  }
  if (!names.length) return { frames: 0, frame: null, name: null };
  const stats = await Promise.all(names.map(async (name) => {
    try {
      return { name, at: (await stat(path.join(directory, name))).mtimeMs };
    } catch {
      return { name, at: 0 };
    }
  }));
  stats.sort((left, right) => right.at - left.at);
  const newest = stats[0];
  try {
    const bytes = await readFile(path.join(directory, newest.name));
    return { frames: names.length, name: newest.name,
      frame: `data:image/png;base64,${bytes.toString("base64")}` };
  } catch {
    return { frames: names.length, name: newest.name, frame: null };
  }
}

/**
 * A snapshot of a run in progress: its newest frame and everything the model has
 * thought so far. `status` is "live" while the run is registered and "finished"
 * once it is not -- a completed run's capture is taken and cleared by
 * takeRunReasoning(), so the absence of a context is exactly the end of the run.
 */
async function liveRunState(runId) {
  const context = getRunContext(runId);
  if (!context) {
    return { runId, status: "finished", frames: 0, frame: null, frameName: null, reasoning: [] };
  }
  const reasoning = peekRunReasoning(runId);
  const elapsedMs = Date.now() - context.startedAt;
  if (!context.outputDir) {
    return { runId, status: "live", elapsedMs, frames: 0, frame: null, frameName: null, reasoning };
  }
  const directory = await findRunDirectory(context.outputDir, runId, context.startedAt);
  if (!directory) {
    return { runId, status: "live", elapsedMs, frames: 0, frame: null, frameName: null, reasoning };
  }
  const { frames, frame, name } = await latestScreenshot(directory);
  // The directory basename *is* journeytest-core's own run id, which is what the
  // stored artifacts are tagged with -- the caller's run id is a different
  // identifier. Reporting it is what lets a finished live run be matched to its
  // recording.
  return { runId, journeyRunId: path.basename(directory), status: "live", elapsedMs,
    frames, frame, frameName: name, reasoning };
}

module.exports = { liveRunState, findRunDirectory, directoryStartedAt, safeId };
