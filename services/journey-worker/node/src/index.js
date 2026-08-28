/** Versioned JourneyTest adapter and native behavior-state owner. */
"use strict";
const http = require("node:http");
const { randomUUID } = require("node:crypto");
const { BehaviorController } = require("./behavior");
const { EvidenceCoordinator, normalizeStepEvidence } = require("./evidence");
const { runWithJourneyTest } = require("./journeytest");
const { replayFromEvidence } = require("./replay");
const { validateBrowserSafety } = require("./safety");

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

function timelineToEvents(timeline, runId) {
  return (timeline || []).map((entry) => ({
    type: `journeytest.${entry.type}`, runId, timestamp: entry.wallTime,
    data: { taskId: entry.taskId, summary: entry.summary, elapsedMs: entry.elapsedMs, ...entry.data },
  }));
}

async function runJourney(input, options = {}) {
  if (!input.url || !Array.isArray(input.tasks) || !input.profile?.behavior) throw new Error("url, tasks, and profile.behavior are required");
  const browserSafety = validateBrowserSafety(input);
  if (process.env.JOURNEY_ENGINE === "journeytest") {
    const result = await runWithJourneyTest(input);
    result.browserSafety = browserSafety;
    // journeytest-core's real RunResult (see @baguette-studios/journeytest-core's
    // core/schemas.ts RunResultSchema) has no `.steps` field -- it reports
    // `timeline` (real per-action events) and `artifacts.screenshots`/`snapshots`
    // (file paths on disk), not the fixture engine's elementMap-based step
    // evidence below. Surface the real timeline as events instead of the
    // previous no-op loop over a field that never existed on a live run.
    result.events = timelineToEvents(result.timeline, result.runId);
    // Eyeson evidence enqueueing (ux.analysis.*) requires the elementMap +
    // behavior-transition evidence contract built below for the native fixture
    // engine; live JourneyTest screenshots don't carry that yet (see
    // apps/api/executor.py's _pain_points_from_journeys limitations for the
    // user-facing note). Not wired here until that bridge exists.
    return result;
  }
  const controller = new BehaviorController(input.profile);
  const coordinator = options.evidenceCoordinator || new EvidenceCoordinator();
  const runId = input.runId || `run_${randomUUID().replaceAll("-", "")}`;
  const events = [{ type: "journey.started", runId, timestamp: new Date().toISOString() }];
  const queuedEvidence = [];
  const steps = input.tasks.map((task, index) => {
    // PLACEHOLDER: replace simulated observation with pinned journeytest-core's
    // library runner; this adapter remains the sole future browser owner.
    const supplied = input.experienceEvents?.[index];
    const experience = supplied || { id: `${runId}_event_${index + 1}`, stepId: `${runId}_step_${index + 1}`,
      timestampMs: index, type: "success", severity: 0, goalBlocked: false, progressVisible: true,
      attribution: { software: 0, interface: 0, capability: 0, user: 0 }, recoveryQuality: 1,
      evidenceRefs: [], classifierConfidence: 1 };
    const transition = controller.apply(experience, input.behaviorContext || {});
    events.push({ type: "experience.event.created", runId, data: experience });
    events.push({ type: "behavior.state.changed", runId, data: transition });
    events.push({ type: "behavior.coping.selected", runId, data: transition.coping });
    const step = { stepId: `${runId}_step_${index + 1}`, task, outcome: "simulated", state: transition.after,
      coping: transition.coping.decision, copingProbabilities: transition.coping.probabilities,
      waitTolerance: transition.waitTolerance, evidence: experience.evidenceRefs || [] };
    const evidence = normalizeStepEvidence(input.stepEvidence?.[index],
      { runId, profileId: input.profile.id, abilities: input.profile.abilities,
        physicalSeed: (input.physicalSimulationSeed ?? input.profile.behavior.seed ?? 1) + index },
      { ...step, index }, transition);
    if (evidence) {
      step.evidence = [evidence];
      events.push({ type: "ux.analysis.requested", runId, data: { evidenceId: evidence.id,
        stepId: evidence.stepId, timestampMs: evidence.timestampMs } });
      queuedEvidence.push(coordinator.enqueue(evidence).then((completed) => ({ step, completed })));
    }
    return step;
  });
  for (const queued of queuedEvidence) {
    const { step, completed } = await queued;
    step.evidence = [completed];
    if (completed.eyeson.status !== "pending") {
      events.push({ type: completed.eyeson.status === "completed" ? "ux.analysis.completed" : "ux.analysis.failed",
        runId, data: { evidenceId: completed.id, stepId: completed.stepId,
          timestampMs: completed.timestampMs, eyeson: completed.eyeson } });
    }
  }
  events.push({ type: "journey.completed", runId, timestamp: new Date().toISOString() });
  return { schemaVersion: "1.0", runId, verdict: "configured", url: input.url, browserSafety,
    profileId: input.profile.id, simulationProfile: input.profile, steps, events,
    limitations: ["PLACEHOLDER: journeytest-core browser capture is awaiting an approved pinned package."] };
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/healthz") return json(response, 200, { service: "journey-worker", status: "ready", behaviorController: true, engine: process.env.JOURNEY_ENGINE || "fixture", journeyTestVersion: "0.1.2" });
    if (request.method === "POST" && request.url === "/v1/runs") return json(response, 201, await runJourney(await body(request)));
    if (request.method === "POST" && request.url === "/v1/replays") return json(response, 201, replayFromEvidence(await body(request)));
    return json(response, 404, { error: "not_found" });
  } catch (error) {
    return json(response, 422, { error: "invalid_run", message: error.message });
  }
});
if (require.main === module) server.listen(Number(process.env.PORT || 8080), "0.0.0.0");

module.exports = { runJourney, replayFromEvidence, timelineToEvents };
