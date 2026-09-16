"use strict";
/**
 * Keeps a visible pointer in the page a run is driving.
 *
 * The browser draws its own cursor above the page, so it is never in a CDP
 * screencast frame, a screenshot, or a recorded video: watching a run, controls
 * react with nothing visibly touching them. A cursor that is part of the DOM is
 * in all three, which is what assets/cursor-overlay.js provides.
 *
 * Getting it into the page is the awkward part. The pinned agent-browser 0.31.1
 * does not run init scripts -- neither AGENT_BROWSER_INIT_SCRIPTS nor
 * `open --init-script` executes the file, verified with a trivial probe -- so the
 * documented hook is unavailable. `eval` does work, so the overlay is evaluated
 * into the page instead, and because a navigation replaces the document and
 * takes the overlay with it, that has to happen more than once.
 *
 * Hence a keeper rather than an installer: re-evaluate on a timer. The script
 * guards on its own flag, so re-evaluating an already-decorated page costs one
 * round trip and changes nothing; after a navigation the flag is gone with the
 * old document and the overlay is put back. A pointer that reappears a second
 * into a new page is worth far more than one that vanishes at the first click
 * through.
 *
 * The tracking itself is real: agent-browser dispatches pointermove, mousemove,
 * mousedown, mouseup and click at the element it acts on, so the overlay follows
 * the agent rather than approximating it.
 */

const fs = require("node:fs");
const path = require("node:path");

const { batch } = require("./agentBrowser");

const OVERLAY_SCRIPT = path.join(__dirname, "..", "assets", "cursor-overlay.js");
// Often enough that a fresh page is decorated before anyone notices, seldom
// enough to be nothing next to what a journey step already costs.
const DEFAULT_INTERVAL_MS = 2000;

let timer = null;
let source = null;
let lastError = "";
let installs = 0;

function enabled(env = process.env) {
  return String(env.AUX_CURSOR_OVERLAY || "").trim() !== "0";
}

function overlaySource() {
  if (source === null) {
    source = fs.existsSync(OVERLAY_SCRIPT) ? fs.readFileSync(OVERLAY_SCRIPT, "utf-8") : "";
  }
  return source;
}

/** Put the overlay in the current page. Idempotent by the script's own guard. */
async function installOnce(runner = batch) {
  const script = overlaySource();
  if (!script) {
    lastError = "cursor overlay script is missing";
    return false;
  }
  const result = await runner([["eval", script]]);
  if (!result.ok) {
    // A page that cannot be reached yet is normal between navigations, and is
    // not worth stopping the keeper over.
    lastError = result.stderr;
    return false;
  }
  lastError = "";
  installs += 1;
  return true;
}

// Reads the marker's own position rather than tracking mouse events a second
// time in the worker: the overlay is the thing the viewer can see, so where it
// is drawn is the honest answer to where the pointer is.
const CURSOR_POSITION_PROBE = `(() => {
  const c = document.getElementById("__aux_cursor_overlay__");
  if (!c) return "";
  const r = c.getBoundingClientRect();
  if (!r.width || r.left < -1000) return "";
  return Math.round(r.left + r.width / 2) + "," + Math.round(r.top + r.height / 2)
    + "," + Math.round(innerWidth) + "," + Math.round(innerHeight);
})()`;

// Where the pointer was last actually seen, kept outside the page because the
// page is where it keeps getting lost.
let lastSeen = null;

/**
 * Where the pointer is, in CSS pixels, with the viewport it is relative to.
 *
 * A navigation destroys the document and the overlay with it, and the keeper's
 * fresh copy is parked off-screen until something moves it again. In a real run
 * that is most of the time: the agent clicks a link, the click lands on the old
 * document, and the new page has never been touched. Watching a live run, the
 * position came back null on all ninety polls of a five-minute journey that
 * clicked throughout -- so a viewer that only draws a live position draws
 * nothing, and the pane meant to show the pointer stays empty.
 *
 * So the last real position is remembered here and reported with `stale` set
 * once the page can no longer confirm it, along with how old it is. That is
 * enough for a viewer to keep the marker where the pointer last was and dim it,
 * rather than choosing between a blank pane and a position it cannot support.
 * `stale` is never guessed: it is false only when the page itself just answered.
 */
async function readCursorPosition(runner = batch, now = Date.now()) {
  const result = await runner([["eval", CURSOR_POSITION_PROBE]]);
  const match = result.ok ? String(result.stdout).match(/(\d+),(\d+),(\d+),(\d+)/) : null;
  if (match) {
    const [, x, y, width, height] = match.map(Number);
    if (width && height) {
      lastSeen = { x, y, viewport: { width, height }, at: now };
      return { x, y, viewport: { width, height }, stale: false, ageMs: 0 };
    }
  }
  if (!lastSeen) return null;
  return { x: lastSeen.x, y: lastSeen.y, viewport: lastSeen.viewport,
    stale: true, ageMs: Math.max(0, now - lastSeen.at) };
}

function startCursorKeeper({ intervalMs, env = process.env, runner = batch } = {}) {
  if (!enabled(env)) return { running: false, reason: "disabled" };
  if (timer) return { running: true, reason: "already-running" };
  const every = Number.isInteger(intervalMs) && intervalMs > 0
    ? intervalMs
    : Number.parseInt(env.AUX_CURSOR_OVERLAY_INTERVAL_MS || "", 10) || DEFAULT_INTERVAL_MS;

  const tick = () => { installOnce(runner).catch(() => {}); };
  tick();
  timer = setInterval(tick, every);
  // The keeper must never be the reason the worker stays alive.
  if (typeof timer.unref === "function") timer.unref();
  return { running: true, intervalMs: every, script: OVERLAY_SCRIPT };
}

function stopCursorKeeper() {
  if (timer) clearInterval(timer);
  timer = null;
}

function cursorKeeperStatus() {
  return { running: Boolean(timer), installs, error: lastError || undefined };
}

/** Test seam: forget everything between cases. */
function __resetCursorKeeper() {
  stopCursorKeeper();
  source = null;
  lastError = "";
  installs = 0;
  lastSeen = null;
}

module.exports = {
  CURSOR_POSITION_PROBE, DEFAULT_INTERVAL_MS, OVERLAY_SCRIPT, cursorKeeperStatus, enabled,
  installOnce, readCursorPosition, startCursorKeeper, stopCursorKeeper, __resetCursorKeeper,
};
