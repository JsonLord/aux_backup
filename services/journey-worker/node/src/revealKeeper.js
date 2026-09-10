"use strict";
/**
 * Makes a page show what a person scrolling it would see, before anything captures it.
 *
 * A full-page screenshot is stitched from viewport-sized captures taken by
 * `Page.captureScreenshot` with captureBeyondViewport -- the renderer paints the
 * whole document without ever scrolling it. Any content gated on
 * IntersectionObserver therefore never intersects, so its reveal never fires and
 * it paints in its un-revealed state. The pattern is everywhere in modern
 * marketing pages:
 *
 *     var io = new IntersectionObserver(...)  // adds .is-visible
 *     .reveal { opacity: 0; transform: translateY(10px); }
 *
 * Measured on a real page: opening it and asking immediately reported 26 of 28
 * `[data-reveal]` elements still un-revealed, over a document 8244px tall. The
 * captures that came out of that were blank below the fold -- four of eight
 * evidence crops in a delivered deck were a single colour -- and the vision
 * critique dutifully reported findings about the emptiness.
 *
 * The faithful fix is to do what a person does: scroll through. That fires every
 * observer on the way down, in the order a reader would trigger them, and leaves
 * the page's motion design intact -- which matters, because the motion is part of
 * the experience under test and a later perception stage needs animations live to
 * model what catches the eye. Forcing prefers-reduced-motion would also reveal the
 * content, by taking the short-circuit most of these scripts offer, but it would
 * do so by switching off the thing we are here to observe. It stays an opt-in
 * escape hatch (AUX_REVEAL_REDUCED_MOTION), not the default.
 *
 * The pass is one `eval`: agent-browser awaits a promise returned from the page,
 * so the scroll, the settle and the restore all happen inside a single command
 * that cannot interleave with whatever the run does next.
 */

const { batch } = require("./agentBrowser");

// Long enough for a transition to start and an observer to fire, short enough
// that a tall page does not cost the run a visible pause.
const DEFAULT_SETTLE_MS = 120;
// A page that grows as you scroll it (infinite feeds, lazy lists) would otherwise
// never end. This many viewports is far past any ordinary marketing page.
const MAX_STEPS = 60;
// How often to check whether the current document still needs a pass. The script
// no-ops on a document it has already done, so this is one cheap round trip.
const DEFAULT_INTERVAL_MS = 1500;

let timer = null;
let lastError = "";
let passes = 0;
let lastResult = null;

function enabled(env = process.env) {
  return String(env.AUX_REVEAL_PASS || "").trim() !== "0";
}

/**
 * The in-page pass. Returns a JSON summary, or "already" when this document has
 * had one -- so re-running costs a round trip and changes nothing.
 *
 * scrollHeight is re-read every step because firing a reveal can add height, and
 * the original scroll position is restored so the run's own view of the page is
 * exactly where it left it.
 */
function revealScript(settleMs = DEFAULT_SETTLE_MS, maxSteps = MAX_STEPS) {
  return `(async () => {
  if (window.__auxRevealedFor === location.href) return "already";
  window.__auxRevealedFor = location.href;
  const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const root = document.documentElement;
  // A page with scroll-behavior:smooth would animate every hop and turn this
  // into a long, visible glide. Restored before returning.
  const behavior = root.style.scrollBehavior;
  root.style.scrollBehavior = "auto";
  const startY = window.scrollY;
  const step = Math.max(200, Math.round(window.innerHeight * 0.8));
  let steps = 0;
  let y = 0;
  try {
    while (y < root.scrollHeight && steps < ${maxSteps}) {
      window.scrollTo(0, y);
      await settle(${settleMs});
      y += step;
      steps += 1;
    }
    window.scrollTo(0, root.scrollHeight);
    await settle(${settleMs});
  } finally {
    window.scrollTo(0, startY);
    root.style.scrollBehavior = behavior;
  }
  const revealable = document.querySelectorAll("[data-reveal],[data-aos],[data-animate],.reveal,.fade-in,.animate-on-scroll");
  let hidden = 0;
  for (const element of revealable) {
    const style = getComputedStyle(element);
    if (Number(style.opacity) < 0.05 || style.visibility === "hidden") hidden += 1;
  }
  return JSON.stringify({ steps: steps, height: root.scrollHeight,
    revealable: revealable.length, stillHidden: hidden, restoredTo: startY });
})()`;
}

/**
 * Ask the page to reveal itself once. Safe to call repeatedly.
 *
 * A page that cannot be reached yet is normal between navigations and is not
 * worth stopping over -- the next tick will find it.
 */
async function revealOnce(runner = batch, { settleMs = DEFAULT_SETTLE_MS, maxSteps = MAX_STEPS } = {}) {
  const result = await runner([["eval", revealScript(settleMs, maxSteps)]]);
  if (!result.ok) {
    lastError = result.stderr;
    return null;
  }
  lastError = "";
  const returned = evalResult(result.stdout);
  if (returned === "already") return { already: true };
  if (!returned || typeof returned !== "object") return { already: false };
  lastResult = returned;
  passes += 1;
  return { already: false, ...returned };
}

/**
 * What the page returned from an `eval`.
 *
 * agent-browser answers a batch as `[{command, error, result}]`, and that `result`
 * is itself an envelope -- `{lifecycle, origin, result}` -- whose innermost
 * `result` holds what the page returned, as a string. So a script returning JSON
 * needs unwrapping three times. Every layer is optional, so a build that answers
 * with a bare value reads the same.
 */
function evalResult(stdout) {
  let value = String(stdout || "").trim();
  if (!value) return null;
  try {
    value = JSON.parse(value);
  } catch {
    return value;    // not an envelope; the raw text is the answer
  }
  if (Array.isArray(value)) value = value[0];
  // Unwrap `result` for as long as there is one, so an extra envelope layer in a
  // future build costs nothing.
  let depth = 0;
  while (value && typeof value === "object" && "result" in value && depth < 5) {
    value = value.result;
    depth += 1;
  }
  if (typeof value !== "string") return value;
  const text = value.trim();
  if (!text.startsWith("{") && !text.startsWith("[")) return text;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function startRevealKeeper({ intervalMs, env = process.env, runner = batch, settleMs, maxSteps } = {}) {
  if (!enabled(env)) return { running: false, reason: "disabled" };
  if (timer) return { running: true, reason: "already-running" };
  const every = Number.isInteger(intervalMs) && intervalMs > 0
    ? intervalMs
    : Number.parseInt(env.AUX_REVEAL_INTERVAL_MS || "", 10) || DEFAULT_INTERVAL_MS;

  const tick = () => { revealOnce(runner, { settleMs, maxSteps }).catch(() => {}); };
  tick();
  timer = setInterval(tick, every);
  // The keeper must never be the reason the worker stays alive.
  if (typeof timer.unref === "function") timer.unref();
  return { running: true, intervalMs: every };
}

function stopRevealKeeper() {
  if (timer) clearInterval(timer);
  timer = null;
}

function revealKeeperStatus() {
  return { running: Boolean(timer), passes, last: lastResult || undefined, error: lastError || undefined };
}

/** Test seam: forget everything between cases. */
function __resetRevealKeeper() {
  stopRevealKeeper();
  lastError = "";
  passes = 0;
  lastResult = null;
}

module.exports = {
  DEFAULT_INTERVAL_MS, DEFAULT_SETTLE_MS, MAX_STEPS, enabled, evalResult, revealScript, revealOnce,
  revealKeeperStatus, startRevealKeeper, stopRevealKeeper, __resetRevealKeeper,
};
