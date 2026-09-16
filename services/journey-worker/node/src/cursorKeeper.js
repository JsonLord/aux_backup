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

// How many positions a hand passes through on its way somewhere. Enough that a
// page watching the pointer sees a movement rather than an appearance; few
// enough that a forty-step run does not spend its time on mouse events.
const TRAVEL_STEPS = 8;

/**
 * The positions a hand passes through between two points.
 *
 * Not a straight line and not a constant speed, because neither is what a hand
 * does: the path bows slightly towards the side it came from and eases in and
 * out of rest. The bow is proportional to the distance, so a short correction
 * stays almost straight and a reach across the page arcs.
 *
 * This matters beyond looking right. A menu that opens on hover opens because
 * the pointer crossed it; a tooltip appears because the pointer paused near it.
 * A pointer that teleports from one control to the next never crosses anything,
 * so a run could not see any of it -- and a review of a page whose navigation
 * only opens on hover would report the navigation as not working.
 */
function pathBetween(from, to, steps = TRAVEL_STEPS) {
  const start = { x: Number(from?.x) || 0, y: Number(from?.y) || 0 };
  const end = { x: Number(to?.x) || 0, y: Number(to?.y) || 0 };
  const spanX = end.x - start.x;
  const spanY = end.y - start.y;
  const distance = Math.hypot(spanX, spanY);
  if (!distance) return [];
  // Perpendicular to the direction of travel, a twelfth of the way out.
  const bow = distance / 12;
  const midX = (start.x + end.x) / 2 - (spanY / distance) * bow;
  const midY = (start.y + end.y) / 2 + (spanX / distance) * bow;
  const points = [];
  for (let step = 1; step <= steps; step += 1) {
    const linear = step / steps;
    // Ease in and out, so the hand accelerates away from rest and settles.
    const time = linear < 0.5 ? 2 * linear * linear : 1 - ((-2 * linear + 2) ** 2) / 2;
    const rest = 1 - time;
    points.push({
      x: Math.round(rest * rest * start.x + 2 * rest * time * midX + time * time * end.x),
      y: Math.round(rest * rest * start.y + 2 * rest * time * midY + time * time * end.y),
    });
  }
  return points;
}

/**
 * Move the pointer there, through every point in between.
 *
 * Sent down the viewport stream when it is connected, because that goes through
 * the browser's own input pipeline and is therefore the only way a CSS `:hover`
 * rule ever fires. When it is not, the events are dispatched in the page
 * instead: that still reaches every script listening for pointer movement, which
 * is most of what opens a menu, and it keeps the overlay honest about where the
 * pointer is.
 */
async function travelTo(to, { runner = batch, send, steps = TRAVEL_STEPS, now = Date.now() } = {}) {
  const from = lastSeen || { x: 0, y: 0 };
  const points = pathBetween(from, to, steps);
  if (!points.length) return { moved: false, points: 0, through: "nothing to do" };
  const sender = send || (() => ({ sent: false }));
  let through = "the page";
  const streamed = points.every((point) =>
    sender({ type: "input_mouse", event: "mousemove", x: point.x, y: point.y }).sent);
  if (streamed) {
    through = "the viewport stream";
  } else {
    // One batch, not one command per point: a round trip each would cost more
    // than the movement is worth.
    const script = points.map((point) => "window.dispatchEvent(new MouseEvent('mousemove', "
      + `{clientX: ${point.x}, clientY: ${point.y}, bubbles: true}))`).join(";");
    const result = await runner([["eval", `(() => { ${script}; return "moved"; })()`]]);
    if (!result.ok) return { moved: false, points: points.length, through: "nothing: " + result.stderr };
  }
  const landed = points[points.length - 1];
  lastSeen = { x: landed.x, y: landed.y, viewport: lastSeen?.viewport, at: now };
  return { moved: true, points: points.length, through };
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
  pathBetween, travelTo, TRAVEL_STEPS,
  CURSOR_POSITION_PROBE, DEFAULT_INTERVAL_MS, OVERLAY_SCRIPT, cursorKeeperStatus, enabled,
  installOnce, readCursorPosition, startCursorKeeper, stopCursorKeeper, __resetCursorKeeper,
};
