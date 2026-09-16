"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  DEFAULT_SECOND_FACTOR_WAIT_MS, DEFAULT_SUBMIT_WAIT_MS, PASSWORD_PROBE, SECOND_FACTOR_PROBE,
  STATUS_FAILED, STATUS_SECOND_FACTOR_TIMED_OUT, STATUS_SUCCEEDED, waitForSignIn,
} = require("../src/loginCapture");

/** A fake clock, so a three-minute wait can be asserted in microseconds. */
function clock() {
  let t = 0;
  return { now: () => t, wait: async (ms) => { t += ms; } };
}

/** Answers the two probes from a script of page states, one per poll.
 *
 * Every poll begins with the password probe, so that is what advances the
 * script; the challenge probe reads the same state within the poll. Advancing on
 * the challenge probe instead would stall on any state where the password field
 * is still up, because that poll never reaches it. */
function pageStates(states) {
  let index = -1;
  return async (expression) => {
    if (expression === PASSWORD_PROBE) index += 1;
    const state = states[Math.min(Math.max(index, 0), states.length - 1)];
    if (expression === PASSWORD_PROBE) return { ok: true, value: state.password };
    if (expression === SECOND_FACTOR_PROBE) return { ok: true, value: state.challenge };
    return { ok: true, value: null };
  };
}

const base = (extra) => ({
  submitWaitMs: 20000, secondFactorWaitMs: 180000, pollIntervalMs: 1000, ...extra,
});

test("a clean sign-in succeeds as soon as the password prompt is gone", async () => {
  const { now, wait } = clock();
  const outcome = await waitForSignIn(base({
    probe: pageStates([{ password: false, challenge: false }]), now, wait,
  }));

  assert.equal(outcome.status, STATUS_SUCCEEDED);
});

test("a second factor extends the wait instead of failing the capture", async () => {
  // The password is right; the site now wants a code from a phone. Racing that
  // to the sign-in timeout would throw away a half-finished login.
  const { now, wait } = clock();
  const announced = [];
  const outcome = await waitForSignIn(base({
    probe: pageStates([
      { password: true, challenge: false },     // still on the form
      { password: false, challenge: true },     // challenge appears
      { password: false, challenge: true },     // person is fetching a code
      { password: false, challenge: false },    // answered
    ]),
    onStatus: (update) => announced.push(update), now, wait,
  }));

  assert.equal(outcome.status, STATUS_SUCCEEDED);
  assert.equal(announced.length, 1, "the challenge is announced once, not every poll");
  assert.equal(announced[0].waitingForMs, 180000);
  assert.match(announced[0].detail, /live view/);
});

test("a challenge is announced once even while it stays on screen", async () => {
  const { now, wait } = clock();
  const announced = [];
  await waitForSignIn(base({
    secondFactorWaitMs: 5000,
    probe: pageStates([{ password: false, challenge: true }]),
    onStatus: (update) => announced.push(update), now, wait,
  }));

  assert.equal(announced.length, 1, "a repeated announcement would be noise, not news");
});

test("an unanswered second factor times out distinctly from a wrong password", async () => {
  // These need different messages: one means go and answer it, the other means
  // the credential is wrong.
  const { now, wait } = clock();
  const unanswered = await waitForSignIn(base({
    secondFactorWaitMs: 4000,
    probe: pageStates([{ password: false, challenge: true }]), now, wait,
  }));
  assert.equal(unanswered.status, STATUS_SECOND_FACTOR_TIMED_OUT);
  assert.match(unanswered.detail, /not answered in time/);

  const clock2 = clock();
  const rejected = await waitForSignIn(base({
    submitWaitMs: 4000,
    probe: pageStates([{ password: true, challenge: false }]),
    now: clock2.now, wait: clock2.wait,
  }));
  assert.equal(rejected.status, STATUS_FAILED);
  assert.match(rejected.detail, /password prompt is still on screen/);
});

test("the human wait is much longer than the sign-in wait", async () => {
  // A sign-in either lands or fails in seconds; a person fetching a code needs
  // minutes. Collapsing them into one number breaks whichever it is not sized for.
  assert.ok(DEFAULT_SECOND_FACTOR_WAIT_MS >= DEFAULT_SUBMIT_WAIT_MS * 4,
    "the second-factor wait must leave real time to reach for a phone");
  assert.ok(DEFAULT_SUBMIT_WAIT_MS >= 10000);
});

test("waiting is bounded, so a capture cannot hang forever", async () => {
  const { now, wait } = clock();
  const outcome = await waitForSignIn(base({
    submitWaitMs: 3000, secondFactorWaitMs: 9000,
    probe: pageStates([{ password: false, challenge: true }]), now, wait,
  }));

  assert.equal(outcome.status, STATUS_SECOND_FACTOR_TIMED_OUT);
  // Sign-in window, then the extension -- not an unbounded loop.
  assert.ok(outcome.elapsedMs <= 3000 + 9000 + 1000, `bounded, got ${outcome.elapsedMs}ms`);
});

test("the second-factor probe recognises what sites actually show", () => {
  for (const phrase of ["Enter your verification code", "Two-factor authentication",
                        "Open your authenticator app", "Check your phone to approve this sign-in",
                        "Enter the one-time code we sent"]) {
    assert.match(phrase, /two[- ]?factor|verification code|authenticator|one[- ]?time (code|password)|security code|approve (the |this )?(sign|log)[- ]?in|check your (phone|device)/i,
      `should be treated as a challenge: ${phrase}`);
  }
  // An ordinary page must not be mistaken for a challenge and wait three minutes.
  assert.doesNotMatch("Add to basket. Free delivery over 30.",
    /two[- ]?factor|verification code|authenticator|one[- ]?time (code|password)|security code/i);
});
