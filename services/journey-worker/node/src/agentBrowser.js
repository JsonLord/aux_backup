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

function agentBrowserCommand() {
  return process.env.AGENT_BROWSER_COMMAND
    || path.join(__dirname, "..", "node_modules", ".bin", "agent-browser");
}

/** Run agent-browser. `input` is written to stdin and never appears in argv. */
function runAgentBrowser(args, { input, timeoutMs = COMMAND_TIMEOUT_MS } = {}) {
  return new Promise((resolve) => {
    const child = execFile(agentBrowserCommand(), args, { timeout: timeoutMs },
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

module.exports = { COMMAND_TIMEOUT_MS, agentBrowserCommand, batch, evaluateInPage, runAgentBrowser };
