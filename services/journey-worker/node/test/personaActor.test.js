"use strict";
/**
 * A persona's turn is one model reply, so what happens when that reply arrives
 * damaged decides whether the run keeps a real thought or invents a fake one.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  ACTION_TYPES, ACTION_VOCABULARY, backoffMs, buildPrompt, completion, completionBudget, parseDecision,
  retryAfterMs, salvageAction,
  buildReflectionPrompt,
  describeTarget,
  unreachable,
  UNREACHABLE_ATTEMPTS,
  describeFailure} = require("../src/personaActor");

test("a decision cut off mid-sentence keeps what the person actually said", async () => {
  // Discarding it costs the run a turn and produces the "malformed" fallback --
  // a READ nobody chose, which then reads as a real observation in the record.
  const cut = '{"visible": "A page of vision statements, no numbers", '
    + '"expectation": "there is no price here", "action": {"type": "GIVE_UP", "content": "Four pages and not one num';
  const decision = parseDecision(cut);
  assert.equal(decision.action.type, "GIVE_UP");
  assert.equal(decision.visible, "A page of vision statements, no numbers");
  assert.equal(decision.expectation, "there is no price here");
});

test("a fragment with no action at all is still a failure", async () => {
  assert.equal(parseDecision('{"visible": "a page", "expectation": "somethi'), null);
  assert.equal(parseDecision('{"action": {"type": "TELEPORT"}}'), null, "and an action nothing implements");
});

test("the completion budget covers thinking the caller cannot see", () => {
  assert.equal(completionBudget({}), 4096);
  assert.equal(completionBudget({ OPENAI_MAX_COMPLETION_TOKENS: "8192" }), 8192);
  assert.equal(completionBudget({ OPENAI_MAX_COMPLETION_TOKENS: "nonsense" }), 4096);
});

test("a reply wrapped in a code fence or prose is still read", () => {
  const fenced = '```json\n{"visible": "a form", "expectation": "it submits", '
    + '"action": {"type": "CLICK", "target": "e3"}}\n```';
  assert.equal(parseDecision(fenced).action.target, "e3");
  const chatty = 'Sure! {"visible": "a form", "expectation": "it submits", '
    + '"action": {"type": "CLICK", "target": "e3"}} Let me know if you need more.';
  assert.equal(parseDecision(chatty).action.type, "CLICK");
});

test("an action nothing implements is refused however well-formed the reply", () => {
  assert.equal(salvageAction('{"type": "TELEPORT"}').type, "TELEPORT",
    "salvage reports what was said");
  assert.equal(parseDecision('{"action": {"type": "TELEPORT", "target": "mars"}}'), null,
    "and the vocabulary is what decides whether it counts");
  assert.ok(!ACTION_TYPES.includes("TELEPORT"));
  assert.ok(ACTION_VOCABULARY.includes("GIVE_UP"));
});

test("a rate limit is waited out, not given up on", async () => {
  // A live run died after a single action -- having already opened the page,
  // looked at it and formed an expectation -- because two jobs shared a router
  // for a minute. 429 was being treated exactly like a 502: three attempts, 1.5s
  // then 3s, four and a half seconds of patience against a rate-limit window that
  // outlasts it easily.
  const waits = [];
  let calls = 0;
  const fetchStub = async () => {
    calls += 1;
    if (calls <= 4) {
      return { ok: false, status: 429, text: async () => "Too Many Requests",
        headers: { get: () => "" } };
    }
    return { ok: true, json: async () => ({ choices: [{ message: { content: "done" } }] }) };
  };
  const original = global.fetch;
  global.fetch = fetchStub;
  try {
    const answer = await completion({ system: "s", user: "u", model: "m", apiKey: "k",
      baseUrl: "https://example.test", wait: async (ms) => { waits.push(ms); } });
    assert.equal(answer, "done");
  } finally {
    global.fetch = original;
  }

  assert.equal(calls, 5, "three attempts is not enough patience for a rate limit");
  // Doubling, so a minute of throttling is outlasted rather than run into.
  assert.deepEqual(waits, [3000, 6000, 12000, 24000]);
});

test("a rate limit does not make a healthy endpoint slower", () => {
  // Everything that is not a 429 keeps exactly the patience it had.
  assert.deepEqual([1, 2, 3].map((attempt) => backoffMs({ status: 502 }, attempt, 1500)),
    [1500, 3000, 4500]);
  assert.equal(backoffMs({}, 1, 1500), 1500);
});

test("the server's own Retry-After is preferred, and capped", () => {
  // It is the one party that knows. But a server asking for ten minutes is asking
  // for more than a journey has, and waiting it out would cost the run anyway.
  assert.equal(retryAfterMs("5"), 5000);
  assert.equal(retryAfterMs(""), null);
  assert.equal(retryAfterMs("soon"), null);
  assert.equal(backoffMs({ status: 429, retryAfter: "8" }, 1, 1500), 8000);
  assert.equal(backoffMs({ status: 429, retryAfter: "600" }, 1, 1500), 30000);
  // An HTTP-date form resolves to a delay rather than being discarded.
  const soon = new Date(Date.now() + 4000).toUTCString();
  assert.ok(Math.abs(retryAfterMs(soon) - 4000) < 1500);
});

test("the prompt carries what GEPA found, and nothing that needs GEPA to run", () => {
  // Four things in the instruction are measured rather than guessed: GEPA
  // optimised it against the same adherence judge the run uses, over the corpus
  // of judged actions the runs produced, and the best candidate scored 8.6/10
  // against 2.67 for a bare signature. What it converged on is what is asserted
  // here -- concision, the kinds of thing on a page, the persona's own language,
  // and naming a control by its label rather than by its ref.
  const { system } = buildPrompt({
    profile: { persona: { name: "Friedrich Wolf" }, behavior: {} },
    tasks: ["find the price"], observation: "[e17] button Annual",
    affect: "", history: [], notLikeYou: "", constraints: "",
  });

  assert.match(system, /using only\nthe language you would use/);
  assert.match(system, /concise, and about the page: headings, buttons, links, sections/);
  // The worked example is the part that earns its place: the prompt already said
  // not to mention refs and never showed what to say instead, and reports were
  // carrying "CLICK e17" into sentences meant for a human reader.
  assert.match(system, /I will click the 'Annual - save 17%' button/);
  assert.match(system, /not "I will click e17"/);
});

test("the reflection prompt names controls the way the acting prompt does", () => {
  // The rule went into the acting prompt and only there, so reflection kept
  // writing refs into prose a reader sees: "The Monthly button (e18) is still
  // present" reached a live report as evidence.
  const { system, user } = buildReflectionPrompt({
    profile: { persona: { name: "Friedrich Wolf" } },
    expectation: "the monthly price",
    action: { type: "CLICK", target: "e18", content: "" },
    observation: "[e18] button Monthly",
    targetName: "Monthly",
  });
  assert.match(system, /Never mention refs, selectors or/, "the rule has to be stated here too");
  assert.match(user, /What you did: CLICK the "Monthly"/,
    "the prompt handed it the ref and then the model echoed it back");
  assert.doesNotMatch(user.split("\n")[0], /e18/, "the ref is not what you did");
});

test("an unnamed target still says what was acted on", () => {
  assert.equal(describeTarget({ type: "CLICK", target: "e18" }, ""), " e18",
    "a ref nobody can read beats an action with no object at all");
  assert.equal(describeTarget({ type: "CLICK", target: "" }, ""), "");
  assert.equal(describeTarget({ type: "CLICK", target: "e18" }, "  Monthly  "), ' the "Monthly"');
});

test("an endpoint that is gone gets more patience than one that is busy", async () => {
  // Cycle 20 lost two of three personas to a blip that lasted under a minute.
  // Both died on their first actor call, 33 seconds apart, because a transport
  // failure carries no HTTP status and so fell through to the plain linear retry
  // -- three tries over four seconds -- while a 429, which at least proves
  // something is listening, was given seven attempts and up to thirty seconds
  // between them.
  assert.ok(unreachable(new TypeError("fetch failed")));
  assert.ok(unreachable(Object.assign(new Error("aborted"), { name: "AbortError" })));
  assert.ok(unreachable(new Error("connect ECONNREFUSED 10.0.0.1:443")));
  assert.ok(!unreachable({ status: 502 }), "something answered, unhappily");
  assert.ok(!unreachable({ status: 429 }), "the rate limit has its own patience");

  // Exponential, and it climbs to the same ceiling a rate limit does.
  const gone = new TypeError("fetch failed");
  assert.deepEqual([1, 2, 3, 4, 5].map((n) => backoffMs(gone, n, 1500)),
    [3000, 6000, 12000, 24000, 30000]);
  // A plain upstream error is unchanged: it was never the problem.
  assert.deepEqual([1, 2, 3].map((n) => backoffMs({ status: 502 }, n, 1500)),
    [1500, 3000, 4500]);
});

test("a transport failure is retried past the default attempt count", async () => {
  let calls = 0;
  const originalFetch = global.fetch;
  global.fetch = async () => {
    calls += 1;
    if (calls < 5) throw new TypeError("fetch failed");
    return { ok: true, json: async () => ({ choices: [{ message: { content: "recovered" } }] }) };
  };
  try {
    const answer = await completion({ system: "s", user: "u", model: "m", apiKey: "k",
      baseUrl: "https://example.test/v1", wait: async () => {} });
    assert.equal(answer, "recovered");
    assert.equal(calls, 5, "three attempts would have given up before the endpoint came back");
  } finally {
    global.fetch = originalFetch;
  }
});

test("patience for an endpoint that is gone is still bounded", async () => {
  let calls = 0;
  const originalFetch = global.fetch;
  global.fetch = async () => { calls += 1; throw new TypeError("fetch failed"); };
  try {
    await assert.rejects(
      completion({ system: "s", user: "u", model: "m", apiKey: "k",
        baseUrl: "https://example.test/v1", wait: async () => {} }),
      /persona actor call failed after 6 attempt\(s\): fetch failed/);
    assert.equal(calls, UNREACHABLE_ATTEMPTS, "it gives up, it does not retry for ever");
  } finally {
    global.fetch = originalFetch;
  }
});

test("a transport failure says what actually went wrong, not just that it did", async () => {
  // Cycles 20 and 21 each lost two of three personas to "fetch failed" and the
  // record could not say which of four explanations it was -- DNS, a dropped
  // link, an exhausted connection pool, a provider restart. They call for
  // different fixes, and undici puts the answer one level down on error.cause.
  const dns = Object.assign(new Error("getaddrinfo EAI_AGAIN router.example"), { code: "EAI_AGAIN" });
  assert.equal(describeFailure(Object.assign(new TypeError("fetch failed"), { cause: dns })),
    "fetch failed <- getaddrinfo EAI_AGAIN router.example (EAI_AGAIN)");

  // A chain deeper than one link still resolves, and a cycle cannot hang it.
  const looped = new Error("outer");
  looped.cause = looped;
  assert.equal(describeFailure(looped), "outer");

  assert.equal(describeFailure(new Error("plain")), "plain");
  assert.equal(describeFailure(undefined), "");
});

test("the failure a run reports carries the cause with it", async () => {
  const originalFetch = global.fetch;
  global.fetch = async () => {
    throw Object.assign(new TypeError("fetch failed"),
      { cause: Object.assign(new Error("connect ECONNREFUSED 10.0.0.1:443"), { code: "ECONNREFUSED" }) });
  };
  try {
    await assert.rejects(
      completion({ system: "s", user: "u", model: "m", apiKey: "k",
        baseUrl: "https://example.test/v1", wait: async () => {} }),
      /ECONNREFUSED/);
  } finally {
    global.fetch = originalFetch;
  }
});
