"use strict";
/**
 * Letting a person drive the browser a run is using.
 *
 * Some things an agent cannot finish: a second factor whose code is on someone's
 * phone, or a challenge that is specifically asking whether a human is there.
 * Rather than fail the run, the browser is handed over -- the viewer sends real
 * mouse and keyboard events down the stream it is already watching, and the run
 * carries on once the obstacle clears.
 *
 * Handover is explicit, and input is refused without it. An agent mid-action and
 * a person clicking are two hands on the same pointer, and the resulting run is
 * evidence of neither one's behaviour. Making it a mode also means the record
 * says a human intervened, which matters when the artifact is a usability
 * finding: a step a person completed by hand is not a step the product afforded.
 *
 * What it does not do is make a browser look human. Challenge scoring reads the
 * browser as much as the interaction, and this one is still driven over CDP. A
 * person clicking helps with the half that watches behaviour and does nothing
 * for the half that fingerprints the client.
 */

const MAX_HISTORY = 20;

let active = null;
let history = [];

function nowIso() {
  return new Date().toISOString();
}

/**
 * Hand the browser to a person.
 *
 * `reason` is recorded rather than validated: "second factor", "challenge",
 * "sign-in" and anything else a caller needs are all the same mechanism, and the
 * record is more useful than a taxonomy.
 */
function beginTakeover({ runId = "", reason = "", url = "", by = "" } = {}) {
  if (active) {
    return { ...active, alreadyActive: true };
  }
  active = {
    takeoverId: `to_${Date.now().toString(36)}`,
    runId: String(runId || ""),
    reason: String(reason || "unspecified"),
    url: String(url || ""),
    by: String(by || ""),
    startedAt: nowIso(),
    events: 0,
  };
  return { ...active, alreadyActive: false };
}

function endTakeover() {
  if (!active) return null;
  const finished = { ...active, endedAt: nowIso() };
  history = [finished, ...history].slice(0, MAX_HISTORY);
  active = null;
  return finished;
}

function takeoverActive() {
  return Boolean(active);
}

/** Count one relayed event, so the record says how much was done by hand. */
function noteInput() {
  if (active) active.events += 1;
}

/**
 * The current handover and the recent ones.
 *
 * The history is what a reader needs later: a finding from a step a person
 * completed by hand should not be read as something the product afforded.
 */
function takeoverState() {
  return { active: active ? { ...active } : null, recent: history.map((item) => ({ ...item })) };
}

/** Test seam. */
function __resetTakeover() {
  active = null;
  history = [];
}

module.exports = {
  MAX_HISTORY, beginTakeover, endTakeover, noteInput, takeoverActive, takeoverState,
  __resetTakeover,
};
