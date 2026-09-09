"use strict";

const fs = require("node:fs");
const path = require("node:path");

const { startRunCapture, takeRunReasoning } = require("./reasoningCapture");

function safeId(value, fallback) {
  const normalized = String(value || fallback).replace(/[^a-zA-Z0-9._-]/g, "-");
  return (normalized || fallback).slice(0, 24);
}

// journeytest-core's director prompt names the criterion ids and tells the model
// to use "inconclusive" when evidence is weak, but never states the vocabulary
// `verdict.criteria[].result` actually accepts -- "met" | "not-met" | "blocked" |
// "not-observed" (AgentVerdictType, dist/directors/pi/tools.js). A live run had
// the model answer with the verdict *status* words instead, so journey_finish was
// rejected by schema validation with one "must be equal to constant" per allowed
// literal plus "must match a schema in anyOf", and the whole journey aborted with
// no verdict. runJourney() exposes no prompt hook, but it serialises the journey
// contract into the prompt verbatim -- so the criterion the model is assessing is
// where the vocabulary can be restated.
const CRITERION_RESULT_VOCABULARY =
  ' Report this criterion with result exactly one of "met", "not-met", "blocked", or'
  + ' "not-observed" -- never "passed", "failed", or "inconclusive", which are verdict'
  + " status values rather than criterion results.";

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
    passCriteria: [{ id: "tasks-completed",
      statement: `The requested tasks can be completed.${CRITERION_RESULT_VOCABULARY}`,
      requiredEvidence: ["screenshot"] }],
    failCriteria: [{ id: "tasks-blocked",
      statement: `A requested task cannot be completed.${CRITERION_RESULT_VOCABULARY}`,
      requiredEvidence: ["screenshot"], severity: "major" }],
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

const CURSOR_OVERLAY_SCRIPT = path.join(__dirname, "..", "assets", "cursor-overlay.js");

/**
 * Make the pointer visible in everything this run captures.
 *
 * agent-browser reads AGENT_BROWSER_INIT_SCRIPTS at launch and registers the
 * script before first navigation. journeytest-core's driver spawns the CLI with
 * execFile and no env option, so the child inherits this process's environment
 * and no driver or library change is needed to reach it.
 *
 * Returns what it did so a caller can report it. Set AUX_CURSOR_OVERLAY=0 to
 * leave the page untouched -- the overlay is a real DOM node, and a page that
 * inspects itself can see it.
 */
function installCursorOverlay(env = process.env) {
  if (String(env.AUX_CURSOR_OVERLAY || "").trim() === "0") return { installed: false, reason: "disabled" };
  if (!fs.existsSync(CURSOR_OVERLAY_SCRIPT)) return { installed: false, reason: "script-missing" };
  const existing = String(env.AGENT_BROWSER_INIT_SCRIPTS || "").trim();
  if (existing) {
    // agent-browser documents --init-script as repeatable but does not document
    // how the env form separates entries (unlike --args, which states "comma or
    // newline"). Appending on a guess could corrupt an operator's own value, so
    // theirs stands and the overlay stays out.
    return { installed: false, reason: "init-scripts-already-configured" };
  }
  env.AGENT_BROWSER_INIT_SCRIPTS = CURSOR_OVERLAY_SCRIPT;
  return { installed: true, script: CURSOR_OVERLAY_SCRIPT };
}

/**
 * Where the authenticated browser session for this run lives, if any.
 *
 * journeytest-core forwards `statePath` to agent-browser as `--state <path>`, a
 * storage-state JSON of cookies and localStorage. A run given one starts already
 * signed in; a run given none browses anonymously.
 *
 * A path that does not exist is thrown rather than ignored. Silently falling back
 * to an anonymous session would produce a run that looks successful while testing
 * the logged-out product -- the failure a reader is least likely to notice.
 */
function resolveSessionState(input) {
  const configured = String(
    input.sessionStatePath || input.statePath || process.env.AGENT_BROWSER_STATE || "",
  ).trim();
  if (!configured) return undefined;
  const resolved = path.resolve(configured);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Browser session state file not found: ${resolved}`);
  }
  return resolved;
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
  // The output directory is registered with the capture so a live view can find
  // the frames journeytest-core is writing while the run is still going.
  startRunCapture(captureId, { outputDir: path.resolve(outputDir) });
  const statePath = resolveSessionState(input);
  const cursorOverlay = installCursorOverlay();
  const result = await core.runJourney({
    journey: journeyContract(input),
    profile: testerContract(input.profile),
    driver,
    director,
    outputDir: path.resolve(outputDir),
    video: input.video !== false,
    browserEnvironment: input.browserEnvironment,
    uiChangeRecording: true,
    statePath,
  });
  return { ...result, profileId: input.profile.id, simulationProfile: input.profile,
    // Whether this run browsed signed in. A finding from an authenticated run and
    // one from an anonymous run are about different products, so the report has to
    // be able to say which it saw.
    authenticatedSession: Boolean(statePath),
    cursorOverlay,
    reasoning: takeRunReasoning(captureId) };
}

module.exports = { CURSOR_OVERLAY_SCRIPT, installCursorOverlay, journeyContract, loadJourneyTest,
  resolveSessionState, runWithJourneyTest, testerContract };
