"use strict";

const path = require("node:path");

const { startRunCapture, takeRunReasoning } = require("./reasoningCapture");

function safeId(value, fallback) {
  const normalized = String(value || fallback).replace(/[^a-zA-Z0-9._-]/g, "-");
  return (normalized || fallback).slice(0, 24);
}

function journeyContract(input) {
  const profileId = safeId(input.profile.id, "persona");
  const tasks = input.tasks.map((task, index) => ({
    id: `task-${index + 1}`,
    instruction: String(task),
    expectedOutcome: `The tester can complete: ${task}`,
    evidence: ["screenshot", "snapshot", "url", "uiChangeTimeline"],
  }));
  return {
    id: safeId(input.runId, `journey-${Date.now()}`),
    title: `AUX live journey for ${profileId}`,
    app: { name: "Target application", baseUrl: input.url },
    testerProfile: profileId,
    objective: tasks.map((task) => task.instruction).join("; "),
    tasks,
    passCriteria: [{ id: "tasks-completed", statement: "The requested tasks can be completed", requiredEvidence: ["screenshot"] }],
    failCriteria: [{ id: "tasks-blocked", statement: "A requested task cannot be completed", requiredEvidence: ["screenshot"], severity: "major" }],
    evidenceRequirements: [
      { kind: "screenshot", description: "Observed browser state", required: true },
      { kind: "snapshot", description: "Observed semantic browser state", required: true },
    ],
    riskLevel: "read-only",
  };
}

function testerContract(profile) {
  const persona = profile.persona || {};
  return {
    id: safeId(profile.id, "persona"),
    name: String(persona.name || profile.id || "Synthetic user"),
    role: String(persona.occupation || "Website visitor"),
    perspective: JSON.stringify({ behavior: profile.behavior, abilities: profile.abilities }),
    goals: Array.isArray(persona.goals) ? persona.goals.map(String) : undefined,
    constraints: Array.isArray(persona.constraints) ? persona.constraints.map(String) : undefined,
  };
}

async function loadJourneyTest() {
  return import("@baguette-studios/journeytest-core");
}

async function runWithJourneyTest(input) {
  const core = await loadJourneyTest();
  if (typeof core.runJourney !== "function" || typeof core.createDefaultJourneyTestFactoryRegistry !== "function") {
    throw new Error("journeytest-core@0.1.2 is missing its documented library exports");
  }
  const modelId = process.env.JOURNEY_MODEL;
  if (!modelId) throw new Error("JOURNEY_MODEL is required for live JourneyTest execution");
  const provider = process.env.JOURNEY_PROVIDER || "openai";
  const apiKey = process.env.OPENAI_API_KEY || process.env.BLABLADOR_API_KEY;
  if (!apiKey) throw new Error("OPENAI_API_KEY or BLABLADOR_API_KEY is required for live JourneyTest execution");
  const registry = core.createDefaultJourneyTestFactoryRegistry();
  const driver = process.env.AGENT_BROWSER_COMMAND && typeof core.AgentBrowserDriver === "function"
    ? new core.AgentBrowserDriver({ command: process.env.AGENT_BROWSER_COMMAND })
    : registry.browserDrivers.create("agent-browser", {});
  const baseUrl = process.env.OPENAI_BASE_URL || process.env.OPENAI_COMPATIBLE_ENDPOINT;
  const knownModel = registry.directors.create.bind(registry.directors);
  let director;
  try {
    director = knownModel("pi", { provider, modelId, getApiKey: () => apiKey });
  } catch (error) {
    if (!baseUrl || typeof core.PiSdkDirector !== "function") throw error;
    // Pi's built-in catalog cannot know arbitrary OpenAI-compatible model IDs.
    // Supply the documented model contract while retaining the pinned director.
    director = new core.PiSdkDirector({
      // pi-ai gates the `reasoning_effort` request parameter and the
      // provider-specific thinking formats on this flag
      // (dist/api/openai-completions.js). Off by default: the configured router
      // already returns reasoning without being asked -- a live run recorded 12
      // `thinking` blocks with this false -- and asking for reasoning_effort on a
      // route that rejects the parameter would fail the whole journey.
      // JOURNEY_MODEL_REASONING=1 turns it on for a router known to accept it.
      model: { id: modelId, name: modelId, provider, api: "openai-completions", baseUrl,
        reasoning: process.env.JOURNEY_MODEL_REASONING === "1",
        input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
        contextWindow: 128000, maxTokens: 16384 },
      getApiKey: () => apiKey,
    });
  }
  const outputDir = input.artifactDirectory || process.env.JOURNEY_ARTIFACT_ROOT || "/tmp/aux-journeys";
  // journeytest-core keeps only `text` content blocks when it records an
  // assistant turn, so the model's real thinking never reaches the run
  // artifacts. Capture it from the completions responses instead.
  const captureId = String(input.runId || `run-${Date.now()}`);
  startRunCapture(captureId);
  const result = await core.runJourney({
    journey: journeyContract(input),
    profile: testerContract(input.profile),
    driver,
    director,
    outputDir: path.resolve(outputDir),
    video: input.video !== false,
    browserEnvironment: input.browserEnvironment,
    uiChangeRecording: true,
  });
  return { ...result, profileId: input.profile.id, simulationProfile: input.profile,
    reasoning: takeRunReasoning(captureId) };
}

module.exports = { journeyContract, loadJourneyTest, runWithJourneyTest, testerContract };
