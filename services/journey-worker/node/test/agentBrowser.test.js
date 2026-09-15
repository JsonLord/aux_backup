"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { activeSessionName, runAgentBrowser, setActiveSession,
  RETRYABLE} = require("../src/agentBrowser");
const { sessionNameFor } = require("../src/journeytest");

test.afterEach(() => setActiveSession(""));

/** Capture the argv a call would use, without running agent-browser. */
async function argvFor(options) {
  // A command that cannot exist: execFile fails, and the resolved argv is what
  // this is asserting on, not the outcome.
  const previous = process.env.AGENT_BROWSER_COMMAND;
  process.env.AGENT_BROWSER_COMMAND = "/nonexistent/agent-browser-for-argv-capture";
  try {
    const result = await runAgentBrowser(["stream", "status", "--json"], options);
    assert.equal(result.ok, false);
    return result;
  } finally {
    if (previous === undefined) delete process.env.AGENT_BROWSER_COMMAND;
    else process.env.AGENT_BROWSER_COMMAND = previous;
  }
}

test("a command with no session named reaches whichever browser is the default", async () => {
  assert.equal(activeSessionName(), "");
  const result = await argvFor(undefined);
  // Nothing to assert about a session that was never set; what matters is that
  // the call is still made rather than refused.
  assert.equal(result.ok, false);
});

test("the run's session is used once it has been set", () => {
  assert.equal(setActiveSession("aux-run-7"), "aux-run-7");
  assert.equal(activeSessionName(), "aux-run-7");
  setActiveSession("");
  assert.equal(activeSessionName(), "");
});

test("a caller can opt out of the active session explicitly", async () => {
  // A login capture is not part of any run and must not sign in inside a running
  // journey's browser, so it passes an empty session rather than omitting it.
  setActiveSession("aux-run-7");
  const result = await argvFor({ session: "" });
  assert.equal(result.ok, false);
  assert.equal(activeSessionName(), "aux-run-7");
});

test("two runs of one job get different browser sessions", () => {
  // safeId() truncates to 24 characters, so two personas in one job share a
  // prefix and would otherwise share a browser -- each would see the other's
  // pages.
  const first = sessionNameFor("job_01JQZX9WQ0000000000000_persona_ada");
  const second = sessionNameFor("job_01JQZX9WQ0000000000000_persona_friedrich");
  assert.notEqual(first, second);
  // And a re-ask for the same run gives the same answer, so a second command
  // during a run reaches the browser the first one used.
  assert.equal(sessionNameFor("job_01JQZX9WQ0000000000000_persona_ada"), first);
});

test("a session name is safe to pass as a command-line argument", () => {
  const name = sessionNameFor("../../etc/passwd; rm -rf /");
  assert.match(name, /^aux-[A-Za-z0-9._-]+$/);
});

test("a command agent-browser asks to have retried is retried", async () => {
  // Cycle 34 ended a three-persona run on a daemon race: two commands arrived
  // together, each wanting the daemon started with its own configuration, and
  // the loser was told "Retry the command so agent-browser can restart it with
  // the requested configuration". Nothing retried.
  assert.ok(RETRYABLE.test(
    "✗ A daemon for session 'aux-job_2e30' started concurrently with different daemon "
    + "configuration. Retry the command so agent-browser can restart it with the requested "
    + "configuration."));

  // A daemon that exits during startup "with no error output" is the same kind
  // of non-answer: no command was carried out, and the tool is saying it does
  // not know why either. Cycle 38 ended on the first command of the run this
  // way -- `record start`, three seconds in, nothing retried.
  assert.ok(RETRYABLE.test(
    "\u2717 Daemon process exited during startup with no error output. "
    + "Re-run with --debug for more details."));

  // And only those. A click that found no element, a page that would not load
  // and a timeout are answers: running the same command again spends the time
  // to receive the same answer.
  for (const answer of ["element not found: e17", "Command failed: timeout", "net::ERR_NAME_NOT_RESOLVED",
                        "No such session", "page crashed"]) {
    assert.ok(!RETRYABLE.test(answer), `"${answer}" is an answer, not a request to try again`);
  }
});
