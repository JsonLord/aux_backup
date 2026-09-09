"use strict";
/**
 * Sign in once, by hand or by password, and keep the session.
 *
 * A run browses signed in when it is handed a storage-state file. This produces
 * one: it drives agent-browser to a login page, fills the credential, waits for
 * the sign-in to actually land, and exports the resulting cookies and
 * localStorage. From then on the credential itself is not needed again until the
 * session expires.
 *
 * Two-factor authentication is the reason this waits rather than reports.
 * A password alone does not finish a modern login: the site asks for a code from
 * a phone, an authenticator app, or a push notification, and none of those can
 * be produced here. What can be done is stay out of the way -- keep the page
 * alive, keep saying that it is waiting, and let a person finish the challenge
 * through the live viewport (agent-browser's stream accepts input events, so the
 * headless browser on the server can be typed into from the viewer). The capture
 * then continues on its own the moment the challenge clears.
 *
 * The waits are therefore two different kinds of patience, and are configured
 * separately: a normal sign-in either lands or fails in seconds, while a person
 * fetching a code needs minutes.
 *
 * The password never appears in argv. agent-browser's batch mode accepts
 * commands as JSON on stdin, which keeps it out of `ps` on a shared host; the
 * alternative, `fill <selector> <password>`, would not.
 */

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { batch, evaluateInPage, runAgentBrowser } = require("./agentBrowser");

// A sign-in that is going to work redirects quickly; this only has to outlast a
// slow auth round trip.
const DEFAULT_SUBMIT_WAIT_MS = 20000;
// A person has to reach for a phone, open an app, and read a code back. Minutes,
// not seconds -- and cutting this short throws away a half-finished login.
const DEFAULT_SECOND_FACTOR_WAIT_MS = 180000;
const DEFAULT_POLL_INTERVAL_MS = 1500;
const COMMAND_TIMEOUT_MS = 60000;

const STATUS_SUCCEEDED = "succeeded";
const STATUS_AWAITING_SECOND_FACTOR = "awaiting_second_factor";
const STATUS_SECOND_FACTOR_TIMED_OUT = "second_factor_timed_out";
const STATUS_FAILED = "failed";

const USERNAME_SELECTORS = [
  "input[autocomplete='username']", "input[type='email']", "input[name='email' i]",
  "input[name='username' i]", "input[id='email' i]", "input[id='username' i]",
];
const PASSWORD_SELECTORS = [
  "input[autocomplete='current-password']", "input[type='password']",
];
const SUBMIT_SELECTORS = [
  "button[type='submit']", "input[type='submit']",
  "button[name='signin' i]", "button[id*='login' i]", "button[id*='signin' i]",
];

/** Markers of a challenge that only a person can answer. */
const SECOND_FACTOR_PROBE = `(() => {
  const field = document.querySelector(
    "input[autocomplete='one-time-code'], input[name*='otp' i], input[id*='otp' i]," +
    " input[name*='mfa' i], input[id*='mfa' i], input[name*='totp' i]," +
    " input[name*='verification' i], input[id*='verification' i]");
  const text = (document.body && document.body.innerText || "").slice(0, 4000);
  const phrase = /two[- ]?factor|２fa|\\b2fa\\b|verification code|authenticator|one[- ]?time (code|password)|security code|approve (the |this )?(sign|log)[- ]?in|check your (phone|device)/i.test(text);
  // A bot challenge wants a person for the same reason a second factor does, so
  // it extends the same wait rather than needing its own.
  const challenge = /verify(ing)? (you are|you're) human|are you a human|checking your browser|needs to review the security|just a moment|cf-turnstile|hcaptcha|recaptcha|i'm not a robot/i.test(text)
    || Boolean(document.querySelector(
      "iframe[src*='challenges.cloudflare.com'], .cf-turnstile, iframe[src*='hcaptcha.com']," +
      " iframe[src*='recaptcha'], #challenge-form, [data-sitekey]"));
  return Boolean(field) || phrase || challenge;
})()`;

/** Whether a password prompt is still on screen -- i.e. sign-in has not landed. */
const PASSWORD_PROBE =
  `Boolean(document.querySelector("input[type='password']"))`;

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(String(value ?? ""), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback;
}

const run = (args, options) => runAgentBrowser(args, options);
const evaluate = (expression) => evaluateInPage(expression);

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Poll until sign-in lands, reporting a second-factor challenge as soon as one
 * appears so a caller can tell a person to go and answer it.
 */
async function waitForSignIn({ submitWaitMs, secondFactorWaitMs, pollIntervalMs, onStatus,
  probe = evaluate, wait = sleep, now = Date.now }) {
  const started = now();
  let deadline = started + submitWaitMs;
  let announcedChallenge = false;

  while (now() < deadline) {
    const passwordVisible = await probe(PASSWORD_PROBE);
    if (passwordVisible.ok && passwordVisible.value === false) {
      const challenge = await probe(SECOND_FACTOR_PROBE);
      if (!(challenge.ok && challenge.value === true)) {
        return { status: STATUS_SUCCEEDED, elapsedMs: now() - started };
      }
      // A challenge is not a failure and must not be raced: extend to the
      // human-scale wait once, and keep polling while a person answers it.
      if (!announcedChallenge) {
        announcedChallenge = true;
        deadline = now() + secondFactorWaitMs;
        if (onStatus) {
          onStatus({
            status: STATUS_AWAITING_SECOND_FACTOR,
            waitingForMs: secondFactorWaitMs,
            detail: "Waiting for a second factor. Answer the challenge in the live view; "
              + "the capture continues on its own once it clears.",
          });
        }
      }
    }
    await wait(pollIntervalMs);
  }

  return {
    status: announcedChallenge ? STATUS_SECOND_FACTOR_TIMED_OUT : STATUS_FAILED,
    elapsedMs: now() - started,
    detail: announcedChallenge
      ? "The second factor was not answered in time; nothing was saved."
      : "Sign-in did not complete: the password prompt is still on screen.",
  };
}

/**
 * Drive a login and return the storage state it produced.
 *
 * Omit `password` to drive nothing and only wait: the page is opened and a
 * person signs in through the live view. That is the path for a site this cannot
 * fill, and for one where storing the password is not wanted at all.
 */
async function captureLogin(options = {}) {
  const url = String(options.url || "").trim();
  if (!url) throw new Error("a login capture needs the URL of the sign-in page");

  const submitWaitMs = positiveInt(options.submitWaitMs,
    positiveInt(process.env.AUX_LOGIN_SUBMIT_WAIT_MS, DEFAULT_SUBMIT_WAIT_MS));
  const secondFactorWaitMs = positiveInt(options.secondFactorWaitMs,
    positiveInt(process.env.AUX_LOGIN_2FA_WAIT_MS, DEFAULT_SECOND_FACTOR_WAIT_MS));
  const pollIntervalMs = positiveInt(options.pollIntervalMs, DEFAULT_POLL_INTERVAL_MS);
  const onStatus = typeof options.onStatus === "function" ? options.onStatus : null;

  const opened = await run(["open", url]);
  if (!opened.ok) return { status: STATUS_FAILED, detail: `could not open the sign-in page: ${opened.stderr}` };

  if (options.password) {
    const usernameSelector = options.usernameSelector || USERNAME_SELECTORS.join(", ");
    const passwordSelector = options.passwordSelector || PASSWORD_SELECTORS.join(", ");
    const submitSelector = options.submitSelector || SUBMIT_SELECTORS.join(", ");
    const commands = [];
    if (options.username) commands.push(["fill", usernameSelector, String(options.username)]);
    commands.push(["fill", passwordSelector, String(options.password)]);
    commands.push(["click", submitSelector]);

    // stdin, so the password is not in this process's argv.
    const filled = await batch(commands);
    if (!filled.ok) {
      return { status: STATUS_FAILED,
        detail: `could not fill the sign-in form: ${filled.stderr}` };
    }
  } else if (onStatus) {
    onStatus({ status: STATUS_AWAITING_SECOND_FACTOR, waitingForMs: secondFactorWaitMs,
      detail: "Sign in through the live view; the capture saves the session once you are in." });
  }

  const outcome = await waitForSignIn({
    // With no password there is nobody to race: the whole wait is human-scale.
    submitWaitMs: options.password ? submitWaitMs : secondFactorWaitMs,
    secondFactorWaitMs, pollIntervalMs, onStatus,
  });
  if (outcome.status !== STATUS_SUCCEEDED) return outcome;

  const target = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "aux-login-")), "state.json");
  const saved = await run(["state", "save", target]);
  if (!saved.ok || !fs.existsSync(target)) {
    return { status: STATUS_FAILED, detail: `signed in, but the session could not be saved: ${saved.stderr}` };
  }
  const state = fs.readFileSync(target, "utf-8");
  // The temp copy is a bearer credential; the caller stores the value itself.
  fs.rmSync(path.dirname(target), { recursive: true, force: true });

  return { status: STATUS_SUCCEEDED, elapsedMs: outcome.elapsedMs, state };
}

module.exports = {
  DEFAULT_POLL_INTERVAL_MS, DEFAULT_SECOND_FACTOR_WAIT_MS, DEFAULT_SUBMIT_WAIT_MS,
  PASSWORD_PROBE, SECOND_FACTOR_PROBE, STATUS_AWAITING_SECOND_FACTOR, STATUS_FAILED,
  STATUS_SECOND_FACTOR_TIMED_OUT, STATUS_SUCCEEDED,
  captureLogin, waitForSignIn,
};
