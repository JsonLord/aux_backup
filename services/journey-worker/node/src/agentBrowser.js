"use strict";
/**
 * One way to run an agent-browser command.
 *
 * Commands go through batch mode's stdin rather than argv wherever a value
 * might be sensitive: a password on the command line is visible in `ps` to every
 * other process on the host. Keeping one path means the quoting rules cannot
 * drift between the sensitive calls and the ordinary ones.
 */

const { execFile } = require("node:child_process");
const path = require("node:path");

const COMMAND_TIMEOUT_MS = 60000;

// Which browser these commands talk to.
//
// agent-browser keeps one browser per named session, and journeytest-core runs
// every journey in a session of its own (`--session <runId>`). A command sent
// without a name therefore lands in a *different* browser from the run -- which
// is what happened: during a live run, `stream status` reported the run's
// session on port 38091 and the unnamed one on 45977, two separate Chromes. The
// cursor overlay was being drawn into the empty one, and the position probe read
// it back from there, which is why the live view never had a pointer to show.
//
// So the run sets its session here when it starts, and everything the worker
// does on its behalf -- decorating the page, reading the pointer, handing
// control to a person -- follows it. A caller may still pass `session`
// explicitly; a login capture, which is not part of any run, does.
let activeSession = "";

/** Point the worker's own commands at the browser a run is driving. */
function setActiveSession(name) {
  activeSession = String(name || "");
  return activeSession;
}

function activeSessionName() {
  return activeSession;
}

function agentBrowserCommand() {
  return process.env.AGENT_BROWSER_COMMAND
    || path.join(__dirname, "..", "node_modules", ".bin", "agent-browser");
}

/** Run agent-browser. `input` is written to stdin and never appears in argv. */
function runAgentBrowser(args, { input, timeoutMs = COMMAND_TIMEOUT_MS, session } = {}) {
  // `--session` is a global option and has to precede the subcommand.
  const name = session === undefined ? activeSession : String(session || "");
  const argv = name ? ["--session", name, ...args] : args;
  return new Promise((resolve) => {
    const child = execFile(agentBrowserCommand(), argv, { timeout: timeoutMs },
      (error, stdout, stderr) => resolve({
        ok: !error,
        stdout: String(stdout || ""),
        // Only agent-browser's own output is passed on; a caller's arguments are
        // never interpolated into an error, because some of them are secrets.
        stderr: String(stderr || (error ? error.message : "")),
      }));
    if (input !== undefined) child.stdin.end(input);
  });
}

/** Run a batch of commands, given as [[command, ...args], ...]. */
function batch(commands, options = {}) {
  return runAgentBrowser(["batch", "--json"], { ...options, input: JSON.stringify(commands) });
}

/** Evaluate an expression in the page and coerce the obvious scalars. */
async function evaluateInPage(expression, options = {}) {
  const result = await batch([["eval", expression]], options);
  if (!result.ok) return { ok: false, value: null, detail: result.stderr };
  const text = result.stdout.trim();
  if (/\btrue\b/i.test(text)) return { ok: true, value: true };
  if (/\bfalse\b/i.test(text)) return { ok: true, value: false };
  return { ok: true, value: text };
}

module.exports = { COMMAND_TIMEOUT_MS, activeSessionName, agentBrowserCommand, batch, evaluateInPage,
  runAgentBrowser, setActiveSession };
