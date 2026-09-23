"use strict";
/**
 * Recognising a loop by what a control says, not which ref pointed at it.
 *
 * The real run this was built against clicked "Pricing" four times under three
 * different refs (e153, e27 twice, e367 twice) and alternated with "Start free
 * for 30 days" seven times running -- and nothing anywhere noticed, because
 * every counter in this codebase that tracks repetition keys off the ref a walk
 * happened to assign this page load, not off the thing a person would say they
 * clicked. `behavior.js`'s own `repeatedEventCounts` never saw a repeat: three
 * different refs for "Pricing" are three different keys, so the escalating-
 * frustration math that exists for exactly this situation never engaged.
 *
 * Two distinct patterns, because they call for different fixes and read
 * differently in a report:
 *
 *   - the same control again: this many times, whatever it was pointed at by.
 *   - two controls, alternating: neither one repeats on its own, so a same-key
 *     counter never fires, but a person going Pricing, Start free, Pricing,
 *     Start free is not making progress either.
 *
 * Deliberately not the same thing as `behavior.js`'s `repeatedEventCounts`,
 * which is unbounded, whole-run, and keyed however the caller likes (its own
 * `repeatKey`, fixed to use a label rather than a ref by the same change that
 * added this file). This is a short, ordered window purpose-built to notice
 * alternation, which a flat per-key count cannot express -- "Pricing" and
 * "Start free" each recur here too, but neither is a repeat of itself.
 */

// Three tries at the identical control is a pattern; two is trying again.
const REPEAT_THRESHOLD = 3;

// A, B, A, B: back to the first control a second time. Once (A, B, A) is a
// single reconsideration -- a person backing out of a decision -- and this
// waits for it to actually be a cycle before calling it one.
const ALTERNATION_WINDOW = 4;

// How much ordered history a loop needs to be seen in. Longer than the
// alternation window so a same-control repeat spread across a couple of
// intervening clicks (Pricing, Start free, Pricing, Pricing, as the real run's
// own tail did once the alternation broke) is still counted, shorter than a
// whole run so a control clicked once near the start does not keep the label
// "repeated" alive twenty steps later on an unrelated part of the site.
const HISTORY_LIMIT = 8;

/** The identity a loop is tracked by: what kind of action, on what the walk
 * called it -- never the ref, which is only ever good for one page load. */
function actionKey(type, label) {
  return `${type}:${label || "(unnamed)"}`;
}

/**
 * Add one really-attempted action to the run's rolling history, and say
 * whether it completes a loop.
 *
 * `recent` is the history *before* this action; the caller owns the array and
 * is expected to push `{key, label, type}` afterwards (or use `pushed`,
 * returned already trimmed to `HISTORY_LIMIT`, to save a second call).
 */
function detectLoop(recent, current) {
  const withThis = [...recent, current];
  const trimmed = withThis.slice(-HISTORY_LIMIT);

  const repeatCount = trimmed.filter((item) => item.key === current.key).length;
  const repeated = repeatCount >= REPEAT_THRESHOLD ? repeatCount : 0;

  let alternating = null;
  const window = trimmed.slice(-ALTERNATION_WINDOW);
  if (window.length === ALTERNATION_WINDOW) {
    const [a, b, c, d] = window;
    if (a.key !== b.key && a.key === c.key && b.key === d.key) {
      alternating = { a: a.label, b: b.label };
    }
  }
  return { repeated, alternating, label: current.label, pushed: trimmed };
}

/**
 * The loop, said the way the persona would say it -- so it can be handed back
 * as something this person now knows about themselves, the same channel
 * `history` already uses for everything else they have done.
 */
function loopNotice(loop) {
  if (loop.alternating) {
    return `You keep going back and forth between "${loop.alternating.a}" and `
      + `"${loop.alternating.b}" without getting anywhere.`;
  }
  if (loop.repeated) {
    return `You have gone for "${loop.label}" ${loop.repeated} times now; `
      + "it has not gotten you anywhere.";
  }
  return "";
}

module.exports = { ALTERNATION_WINDOW, HISTORY_LIMIT, REPEAT_THRESHOLD, actionKey, detectLoop, loopNotice };
