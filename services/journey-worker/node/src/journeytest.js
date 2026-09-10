"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const { setActiveSession } = require("./agentBrowser");
const { startRunCapture, takeRunReasoning } = require("./reasoningCapture");
const { configureStreamPort, startViewportStream, stopViewportStream } = require("./viewportStream");
const { cursorKeeperStatus, startCursorKeeper, stopCursorKeeper } = require("./cursorKeeper");

function safeId(value, fallback) {
  const normalized = String(value || fallback).replace(/[^a-zA-Z0-9._-]/g, "-");
  return (normalized || fallback).slice(0, 24);
}

/**
 * The agent-browser session this run drives.
 *
 * journeytest-core names it after its own generated run id when we do not say --
 * a timestamped string the worker cannot know until the run directory exists,
 * and by then the pointer overlay and the stream have already had to pick a
 * browser. Naming it ourselves means the worker knows the session before the
 * driver launches, so everything it does on the run's behalf reaches the same
 * browser the run is in.
 *
 * The digest keeps two runs apart when safeId() truncates their ids to the same
 * prefix -- two personas in one job differ only in a suffix.
 */
function sessionNameFor(runId) {
  const digest = crypto.createHash("sha1").update(String(runId || "")).digest("hex").slice(0, 10);
  return `aux-${safeId(runId, "run").slice(0, 12)}-${digest}`;
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
  // An account issued for this run, when the flow under test is registration.
  // Handing the agent the exact values means the credential is known before the
  // browser opens, rather than having to be recovered from a transcript after --
  // an account invented mid-run and never written down is one nobody can get
  // back into, including the next run.
  const identity = input.identity && input.identity.email
    ? ` When the flow asks you to register or sign in, use exactly these details and invent nothing:`
      + ` email ${input.identity.email}; password ${input.identity.password};`
      + ` name ${input.identity.name || profileId}.`
    : "";
  return {
    id: safeId(input.runId, `journey-${Date.now()}`),
    title: `AUX live journey for ${profileId}`,
    app: { name: "Target application", baseUrl: input.url },
    testerProfile: profileId,
    objective: tasks.map((task) => task.instruction).join("; ") + identity,
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
 * Ask agent-browser to draw the pointer into the page.
 *
 * The browser's own cursor is composited above the page, so it is never in a
 * screencast frame, a screenshot, or a recorded video. A cursor that is part of
 * the DOM is, which is what assets/cursor-overlay.js provides -- verified in
 * Chromium: it centres on the pointer, lands in captured pixels, survives
 * navigation, and does not intercept clicks.
 *
 * KNOWN LIMITATION -- the pinned agent-browser 0.31.1 does not honour init
 * scripts. Neither AGENT_BROWSER_INIT_SCRIPTS nor `open --init-script <path>`
 * runs the file: a trivial probe script (`window.__probe = 42`) never executed
 * over http or file, by flag or by env, in a fresh session. Its README documents
 * the feature and a `removeinitscript` command the binary does not have, so that
 * README describes a later build than the pinned one.
 *
 * The request is still made because it costs nothing and, once the pin moves,
 * installs the overlay before the first navigation -- earlier than the keeper
 * below can. What it must not do is claim success: `requested` says the
 * environment was set, not that a cursor will appear. cursorKeeper.js is what
 * actually decorates the page on 0.31.1, by evaluating the same script in.
 *
 * Set AUX_CURSOR_OVERLAY=0 to leave the page untouched -- the overlay is a real
 * DOM node, and a page that inspects itself can see it.
 */
function installCursorOverlay(env = process.env) {
  if (String(env.AUX_CURSOR_OVERLAY || "").trim() === "0") return { requested: false, reason: "disabled" };
  if (!fs.existsSync(CURSOR_OVERLAY_SCRIPT)) return { requested: false, reason: "script-missing" };
  const existing = String(env.AGENT_BROWSER_INIT_SCRIPTS || "").trim();
  if (existing) {
    // agent-browser documents --init-script as repeatable but does not document
    // how the env form separates entries (unlike --args, which states "comma or
    // newline"). Appending on a guess could corrupt an operator's own value, so
    // theirs stands and the overlay stays out.
    return { requested: false, reason: "init-scripts-already-configured" };
  }
  env.AGENT_BROWSER_INIT_SCRIPTS = CURSOR_OVERLAY_SCRIPT;
  return {
    requested: true,
    script: CURSOR_OVERLAY_SCRIPT,
    // Honest about what the pinned build does with it.
    effective: false,
    reason: "agent-browser 0.31.1 does not run init scripts",
  };
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
  const sessionName = sessionNameFor(captureId);
  startRunCapture(captureId, { outputDir: path.resolve(outputDir), sessionName });
  const statePath = resolveSessionState(input);
  const cursorOverlay = installCursorOverlay();
  // Everything the worker does on this run's behalf goes to the run's own
  // browser. Set before anything is sent, because a command without a session
  // opens a second browser rather than failing.
  setActiveSession(sessionName);
  // Honour an operator-pinned stream port if there is one; the port is otherwise
  // discovered from the session, which is what the pinned build actually does.
  configureStreamPort();
  // Not awaited: discovery retries until the driver has launched the browser,
  // and the run must not wait on the live view to start.
  void startViewportStream({ session: sessionName });
  // `eval` is the one injection path 0.31.1 honours, and a navigation takes the
  // overlay with the old document, so it has to be put back rather than set once.
  startCursorKeeper();
  let result;
  try {
    result = await core.runJourney({
      journey: journeyContract(input),
      profile: testerContract(input.profile),
      driver,
      director,
      outputDir: path.resolve(outputDir),
      video: input.video !== false,
      browserEnvironment: input.browserEnvironment,
      uiChangeRecording: true,
      statePath,
      sessionName,
    });
  } finally {
    // The session is this run's. Leaving the keeper pointed at a browser that is
    // going away would have it evaluate into nothing every two seconds, and
    // leaving the socket open would serve a dead run's last frame to the next.
    stopCursorKeeper();
    stopViewportStream();
    setActiveSession("");
  }
  return { ...result, profileId: input.profile.id, simulationProfile: input.profile,
    browserSession: sessionName,
    // Whether this run browsed signed in. A finding from an authenticated run and
    // one from an anonymous run are about different products, so the report has to
    // be able to say which it saw.
    authenticatedSession: Boolean(statePath),
    cursorOverlay: { ...cursorOverlay, keeper: cursorKeeperStatus() },
    reasoning: takeRunReasoning(captureId) };
}

module.exports = { CURSOR_OVERLAY_SCRIPT, installCursorOverlay, journeyContract, loadJourneyTest,
  resolveSessionState, runWithJourneyTest, sessionNameFor, testerContract };
