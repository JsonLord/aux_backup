"use strict";
/**
 * CAP-5, Hat 3: developer mode. FETCH/INSPECT/RUN/AUTHENTICATE, mounted
 * alongside BrowserTool in the same Faculty when a hat actually grants it --
 * never in place of browsing (CAP-2's own rule), and never mounted at all
 * when there is nothing to configure it with (see registerFaculty below).
 *
 * The safety design is the feature, not a wrapper around it. Every rail here
 * is load-bearing and none is decoration added afterwards:
 *
 *   - Off unless the run asks: the registered factory returns no tool at all
 *     when `allowCommands` is empty, so `facultyWith` never mounts this --
 *     mounted-then-guarded is one bug from ungated.
 *   - Allowlist, constructed argv: `_run` calls `execFile(command, args)`
 *     directly -- no shell, so no pipes, substitution or `&&` -- the same
 *     shape `agentBrowser.js`'s `runOnce` already uses, for the same reason
 *     (some arguments are secrets and must never be interpolated into a
 *     string a shell parses).
 *   - Scratch directory per run: every FETCH/INSPECT/RUN is confined to
 *     `this.scratchDir`, resolved and checked before use -- no access to the
 *     repo, the artifact store, or the credential database.
 *   - Environment built empty: `_run` passes `env: {}` to execFile, never
 *     `...process.env`. The worker process holds every provider key this
 *     deployment has; a subprocess that inherits that hands it to whatever
 *     it just downloaded.
 *   - Egress to declared hosts only: `_checkHost` runs every FETCH/
 *     AUTHENTICATE target through `privateHost()` and, when this run named
 *     specific hosts, through that allowlist too.
 *   - Output is untrusted input: RUN's stdout/stderr are wrapped in
 *     `sanitizeUntrustedText()` before they reach the timeline -- a
 *     downloaded README saying "ignore your instructions" is a file, exactly
 *     as page text already is.
 *   - Every invocation is evidence: `processAction` records command, target,
 *     exit status, duration and (sanitized) output into the timeline like a
 *     click, whether it succeeded or not, so "the install fails" can be
 *     checked rather than believed.
 */
const { execFile } = require("node:child_process");
const { createHash } = require("node:crypto");
const fs = require("node:fs/promises");
const path = require("node:path");

const { Tool, registerFaculty } = require("./faculty");
const { privateHost, sanitizeUntrustedText } = require("./safety");

const RUN_TIMEOUT_MS = 60_000;
const FETCH_TIMEOUT_MS = 30_000;
const MAX_FETCH_BYTES = 25 * 1024 * 1024;
const MAX_OUTPUT_CHARS = 4_000;

class DeveloperTool extends Tool {
  constructor({ allowCommands = [], hosts = [], scratchDir } = {}) {
    super({ name: "developer", realWorldSideEffects: true });
    if (!scratchDir) throw new Error("DeveloperTool requires a scratchDir");
    this.allowCommands = new Set(allowCommands);
    // Empty means "no host restriction beyond privateHost()'s own blocklist" --
    // a run that named no specific hosts still cannot reach a private network,
    // but is not limited to a declared allowlist either.
    this.hosts = new Set(hosts.map((host) => String(host).toLowerCase()));
    this.scratchDir = scratchDir;
  }

  get actionTypes() { return ["FETCH", "INSPECT", "RUN", "AUTHENTICATE"]; }

  actionsDefinitionsPrompt() {
    return [
      "- FETCH: target=<url> -- download what the page offers into this run's scratch directory",
      "- INSPECT: target=<path within the scratch directory> -- checksum, size and type of a fetched file; never executes it",
      "- RUN: target=<allowlisted command> content=<space-separated arguments> -- one command in the scratch directory",
      "- AUTHENTICATE: target=<url> content=<a key or token this run was issued> -- exercise it against the product's own API",
    ].join("\n");
  }

  actionsConstraintsPrompt() {
    return "FETCH and AUTHENTICATE only reach hosts this run declared or was told about by the page. "
      + "RUN only executes a command this run was explicitly given permission to run.";
  }

  _checkHost(rawUrl) {
    let url;
    try {
      url = new URL(String(rawUrl));
    } catch {
      throw new Error(`"${rawUrl}" is not a valid URL`);
    }
    if (!["http:", "https:"].includes(url.protocol)) {
      throw new Error("only HTTP(S) targets are allowed");
    }
    if (privateHost(url.hostname)) {
      throw new Error(`${url.hostname} is a private/local target network and is blocked`);
    }
    if (this.hosts.size && !this.hosts.has(url.hostname.toLowerCase())) {
      throw new Error(`${url.hostname} is not a host this run declared`);
    }
    return url;
  }

  /** Resolve a path strictly within the scratch directory. Throws on any
   * attempt to escape it (`..`, an absolute path elsewhere, a symlink target
   * outside it is not followed since this never execs the file). */
  _withinScratch(target) {
    const base = path.resolve(this.scratchDir);
    const resolved = path.resolve(base, String(target || ""));
    if (resolved !== base && !resolved.startsWith(base + path.sep)) {
      throw new Error(`"${target}" is outside this run's scratch directory`);
    }
    return resolved;
  }

  async _fetch(target) {
    const url = this._checkHost(target);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    let response;
    try {
      response = await fetch(url, { redirect: "follow", signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
    const buffer = Buffer.from(await response.arrayBuffer());
    if (buffer.length > MAX_FETCH_BYTES) {
      throw new Error(`fetched ${buffer.length} bytes, over the ${MAX_FETCH_BYTES}-byte limit`);
    }
    const name = path.basename(url.pathname) || "fetched";
    const dest = this._withinScratch(name);
    await fs.mkdir(this.scratchDir, { recursive: true });
    await fs.writeFile(dest, buffer);
    return { status: response.status, ok: response.ok, bytes: buffer.length,
      contentType: response.headers.get("content-type") || "", savedAs: name };
  }

  async _inspect(target) {
    const resolved = this._withinScratch(target);
    const stat = await fs.stat(resolved);
    if (!stat.isFile()) throw new Error(`"${target}" is not a file`);
    const data = await fs.readFile(resolved);
    return { bytes: stat.size, sha256: createHash("sha256").update(data).digest("hex"),
      // The first four bytes are enough to name the common archive/image
      // formats a downloaded file is likely to be, without a dependency and
      // without ever executing the file to find out.
      magic: data.subarray(0, 4).toString("hex") };
  }

  async _run(command, argsText) {
    if (!this.allowCommands.has(command)) {
      throw new Error(`"${command}" is not on this run's command allowlist`);
    }
    const args = String(argsText || "").trim() ? String(argsText).trim().split(/\s+/) : [];
    await fs.mkdir(this.scratchDir, { recursive: true });
    return new Promise((resolve, reject) => {
      execFile(command, args, {
        cwd: this.scratchDir,
        // Never `...process.env`: the worker process holds every provider key
        // this deployment has, and a subprocess that inherits that hands it
        // to whatever it just downloaded.
        env: {},
        timeout: RUN_TIMEOUT_MS,
      }, (error, stdout, stderr) => {
        if (error?.killed) { reject(new Error(`"${command}" timed out after ${RUN_TIMEOUT_MS}ms`)); return; }
        if (error?.code === "ENOENT") { reject(new Error(`"${command}" is allowlisted but not installed`)); return; }
        resolve({
          exitCode: error ? (typeof error.code === "number" ? error.code : 1) : 0,
          // Untrusted the moment it leaves the child process -- a downloaded
          // tool's own output is exactly as untrusted as page text.
          stdout: sanitizeUntrustedText(stdout, MAX_OUTPUT_CHARS),
          stderr: sanitizeUntrustedText(stderr, MAX_OUTPUT_CHARS),
        });
      });
    });
  }

  async _authenticate(target, keyHint) {
    const url = this._checkHost(target);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
    try {
      const response = await fetch(url, {
        signal: controller.signal,
        headers: keyHint ? { authorization: String(keyHint) } : {},
      });
      return { status: response.status, ok: response.ok };
    } finally {
      clearTimeout(timer);
    }
  }

  async processAction(action, context) {
    if (!this.actionTypes.includes(action.type)) return { handled: false };
    const startedAt = Date.now();
    const record = async (outcome) => {
      // Every invocation is evidence, in the timeline like a click, whether
      // it succeeded or failed -- "the install fails" has to be checkable,
      // not believed.
      await context.recorder?.record("developer.invocation",
        `${action.type} ${action.target}${outcome.failed ? " failed" : ""}`,
        { actionType: action.type, target: action.target,
          durationMs: Date.now() - startedAt, ...outcome });
    };
    try {
      let result;
      if (action.type === "FETCH") result = await this._fetch(action.target);
      else if (action.type === "INSPECT") result = await this._inspect(action.target);
      else if (action.type === "RUN") result = await this._run(action.target, action.content);
      else result = await this._authenticate(action.target, action.content);
      await record(result);
      return { handled: true, acted: true, failed: false, ...result };
    } catch (error) {
      const outcome = { failed: true, error: error.message };
      await record(outcome);
      return { handled: true, acted: true, ...outcome };
    }
  }
}

// CAP-2: this run's hat has to actually grant a command allowlist for the
// tool to mount at all -- an empty grant returns no tool, which is how
// facultyWith keeps this off by default rather than mounted-then-refusing
// everything.
registerFaculty("developer", (options) => {
  const grants = options.grants?.developer;
  if (!grants?.allowCommands?.length) return null;
  if (!options.scratchDir) return null;
  return new DeveloperTool({
    allowCommands: grants.allowCommands, hosts: grants.hosts || [], scratchDir: options.scratchDir,
  });
});

module.exports = { DeveloperTool };
