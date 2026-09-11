"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { CURSOR_OVERLAY_SCRIPT, directorKind, installCursorOverlay, journeyContract,
  resolveSessionState, testerContract } = require("../src/journeytest");

test("maps AUX run input to pinned JourneyTest contracts", () => {
  const profile = {
    id: "persona_1",
    persona: { name: "Ava", occupation: "Researcher", goals: ["Find pricing"] },
    behavior: { patience: 0.4 },
    abilities: { vision: { acuity: 1 } },
  };
  const journey = journeyContract({ runId: "run_1", url: "https://example.com", tasks: ["Find pricing"], profile });
  const tester = testerContract(profile);

  assert.equal(journey.testerProfile, "persona_1");
  assert.equal(journey.app.baseUrl, "https://example.com");
  assert.equal(journey.tasks[0].instruction, "Find pricing");
  assert.deepEqual(journey.evidenceRequirements.map((item) => item.kind), ["screenshot", "snapshot"]);
  assert.equal(tester.name, "Ava");
  assert.match(tester.perspective, /patience/);
});

test("every criterion states the result vocabulary journey_finish accepts", () => {
  // journeytest-core validates verdict.criteria[].result against a union of four
  // literals, but its director prompt never names them -- it only tells the model
  // to prefer "inconclusive" when evidence is weak, which is a verdict *status*.
  // A live run answered with status words and journey_finish was rejected
  // ("must be equal to constant" per literal, then "must match a schema in
  // anyOf"), aborting the journey with no verdict at all.
  const journey = journeyContract({
    runId: "run_1", url: "https://example.com", tasks: ["Find pricing"],
    profile: { id: "persona_1", persona: {}, behavior: {}, abilities: {} },
  });

  for (const criterion of [...journey.passCriteria, ...journey.failCriteria]) {
    for (const allowed of ["met", "not-met", "blocked", "not-observed"]) {
      assert.ok(criterion.statement.includes(`"${allowed}"`),
        `${criterion.id} must name the allowed result "${allowed}"`);
    }
    // The words the model reached for instead have to be ruled out by name.
    assert.match(criterion.statement, /never "passed", "failed", or "inconclusive"/);
  }

  // The criterion must still read as its own statement, not only as vocabulary.
  assert.match(journey.passCriteria[0].statement, /^The requested tasks can be completed\./);
  assert.match(journey.failCriteria[0].statement, /^A requested task cannot be completed\./);
});

test("a run with no configured session browses anonymously", () => {
  const previous = process.env.AGENT_BROWSER_STATE;
  delete process.env.AGENT_BROWSER_STATE;
  try {
    assert.equal(resolveSessionState({}), undefined);
  } finally {
    if (previous !== undefined) process.env.AGENT_BROWSER_STATE = previous;
  }
});

test("a configured session state file is resolved to an absolute path", () => {
  const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "aux-state-")), "auth.json");
  fs.writeFileSync(file, "{}");

  assert.equal(resolveSessionState({ sessionStatePath: file }), path.resolve(file));
  // The env var is the deployment-wide default for the same setting.
  const previous = process.env.AGENT_BROWSER_STATE;
  process.env.AGENT_BROWSER_STATE = file;
  try {
    assert.equal(resolveSessionState({}), path.resolve(file));
  } finally {
    if (previous === undefined) delete process.env.AGENT_BROWSER_STATE;
    else process.env.AGENT_BROWSER_STATE = previous;
  }
});

test("a missing session state file fails the run instead of silently signing out", () => {
  // Falling back to anonymous would produce a run that looks fine while testing
  // the logged-out product -- the failure a reader is least likely to catch.
  assert.throws(
    () => resolveSessionState({ sessionStatePath: "/nonexistent/aux-auth.json" }),
    /Browser session state file not found/);
});

test("the cursor overlay is registered through agent-browser's init-script env", () => {
  // journeytest-core's driver spawns the CLI with execFile and no env option, so
  // the child inherits this process's environment -- which is the whole reason
  // this needs no driver or library change.
  const env = {};
  const outcome = installCursorOverlay(env);

  assert.equal(outcome.requested, true);
  assert.equal(env.AGENT_BROWSER_INIT_SCRIPTS, CURSOR_OVERLAY_SCRIPT);
  assert.ok(fs.existsSync(CURSOR_OVERLAY_SCRIPT), "the registered script must exist on disk");
  // The pinned agent-browser 0.31.1 does not run init scripts (a trivial probe
  // script never executed, by flag or env). Reporting this as installed would
  // promise a cursor that never appears.
  assert.equal(outcome.effective, false);
  assert.match(outcome.reason, /0\.31\.1 does not run init scripts/);
});

test("an operator's own init scripts are not overwritten or guessed at", () => {
  // agent-browser documents --init-script as repeatable but never states how the
  // env form separates entries, so appending on a guess could corrupt the value.
  const env = { AGENT_BROWSER_INIT_SCRIPTS: "/opt/site/probe.js" };
  const outcome = installCursorOverlay(env);

  assert.equal(outcome.requested, false);
  assert.equal(outcome.reason, "init-scripts-already-configured");
  assert.equal(env.AGENT_BROWSER_INIT_SCRIPTS, "/opt/site/probe.js");
});

test("the overlay can be turned off so the page under test is untouched", () => {
  const env = { AUX_CURSOR_OVERLAY: "0" };
  const outcome = installCursorOverlay(env);

  assert.equal(outcome.requested, false);
  assert.equal(outcome.reason, "disabled");
  assert.equal(env.AGENT_BROWSER_INIT_SCRIPTS, undefined);
});

test("an issued account is handed to the agent so nothing is invented mid-run", () => {
  // An account the agent made up and nobody recorded is one no later run can get
  // back into, so the values are decided up front and the agent is told them.
  const journey = journeyContract({
    runId: "run_1", url: "https://shop.example.com", tasks: ["Create an account"],
    profile: { id: "persona_1", persona: {}, behavior: {}, abilities: {} },
    identity: { email: "p.9f2@aux-test.invalid", password: "Aux-abc123-DEAD", name: "Persona One" },
  });

  assert.match(journey.objective, /email p\.9f2@aux-test\.invalid/);
  assert.match(journey.objective, /password Aux-abc123-DEAD/);
  assert.match(journey.objective, /invent nothing/);
  // The task itself still leads.
  assert.match(journey.objective, /^Create an account/);
});

test("a run with no issued account is not told to register", () => {
  const journey = journeyContract({
    runId: "run_1", url: "https://shop.example.com", tasks: ["Find pricing"],
    profile: { id: "persona_1", persona: {}, behavior: {}, abilities: {} },
  });

  assert.equal(journey.objective, "Find pricing");
  assert.doesNotMatch(journey.objective, /register|password/i);
});

// The persona director is the product. It shipped unreachable: the selection was
// `JOURNEY_DIRECTOR === "persona"` against a variable no deployment script set,
// so every live run browsed as the competent agent and the persona's eyes,
// expectations, adherence gate and memory bank never executed. Nothing failed --
// the runs looked healthy, and the only trace was `director: "pi-sdk"` in the log.
// These assert the default rather than the mechanism, because the mechanism was
// always correct and the default was the defect.
test("browses as the persona unless a run asks for the agent by name", () => {
  assert.equal(directorKind({}), "persona");
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "" }), "persona");
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "   " }), "persona");
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "persona" }), "persona");
});

test("falls back to the competent agent only for the exact opt-out", () => {
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "pi" }), "pi");
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "  pi  " }), "pi");
  // A typo must not silently cost a run its persona -- that is the failure this
  // whole test exists for, and defaulting the unknown value the other way would
  // reintroduce it under a new spelling.
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "pi-sdk" }), "persona");
  assert.equal(directorKind({ JOURNEY_DIRECTOR: "agent" }), "persona");
});

// The guard above is only half the story: the persona director has to be the one
// the worker actually constructs. Reading the source is the only way to check
// that without a live journeytest-core, and comments are stripped first -- a
// regression test that passes because its own explanation contains the string it
// searches for has happened twice in this repo already.
test("the worker constructs the persona director on the default path", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "src", "journeytest.js"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "");
  const branch = source.match(/if \(directorKind\(\) === "pi"\) \{([\s\S]*?)\n  \} else \{([\s\S]*?)\n  \}/);
  assert.ok(branch, "the director selection is no longer a directorKind() branch");
  assert.match(branch[1], /piDirector\(\)/, "the opt-out branch must build the Pi director");
  assert.match(branch[2], /new PersonaDirector\(/, "the default branch must build the persona director");
});
