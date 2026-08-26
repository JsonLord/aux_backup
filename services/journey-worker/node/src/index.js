/** Versioned JourneyTest adapter and native behavior-state owner. */
"use strict";
const http = require("node:http");
const { randomUUID } = require("node:crypto");
const { BehaviorController } = require("./behavior");
const { runWithJourneyTest } = require("./journeytest");

function json(response, status, body) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(body));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

async function runJourney(input) {
  if (!input.url || !Array.isArray(input.tasks) || !input.profile?.behavior) throw new Error("url, tasks, and profile.behavior are required");
  if (process.env.JOURNEY_ENGINE === "journeytest") {
    return runWithJourneyTest(input);
  }
  const controller = new BehaviorController(input.profile);
  const runId = input.runId || `run_${randomUUID().replaceAll("-", "")}`;
  const events = [{ type: "journey.started", runId, timestamp: new Date().toISOString() }];
  const steps = input.tasks.map((task, index) => {
    // PLACEHOLDER: replace simulated observation with pinned journeytest-core's
    // library runner; this adapter remains the sole future browser owner.
    const experience = { type: "task.observed", outcome: "success", task, index };
    const state = controller.apply(experience);
    const coping = controller.copingDecision();
    events.push({ type: "experience.event.created", runId, data: experience });
    events.push({ type: "behavior.state.changed", runId, data: state });
    events.push({ type: "behavior.coping.selected", runId, data: { coping } });
    return { stepId: `${runId}_step_${index + 1}`, task, outcome: "simulated", state, coping, evidence: [] };
  });
  events.push({ type: "journey.completed", runId, timestamp: new Date().toISOString() });
  return { schemaVersion: "1.0", runId, verdict: "configured", url: input.url, profileId: input.profile.id, simulationProfile: input.profile, steps, events, limitations: ["PLACEHOLDER: journeytest-core browser capture is awaiting an approved pinned package."] };
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/healthz") return json(response, 200, { service: "journey-worker", status: "ready", behaviorController: true, engine: process.env.JOURNEY_ENGINE || "fixture", journeyTestVersion: "0.1.2" });
    if (request.method === "POST" && request.url === "/v1/runs") return json(response, 201, await runJourney(await body(request)));
    return json(response, 404, { error: "not_found" });
  } catch (error) {
    return json(response, 422, { error: "invalid_run", message: error.message });
  }
});
if (require.main === module) server.listen(Number(process.env.PORT || 8080), "0.0.0.0");

module.exports = { runJourney };
