"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { PersonaDirector, observationFrom, outcomeEvent } = require("../src/personaDirector");
const { affectInWords, parseDecision, personaInWords, scriptedActor } = require("../src/personaActor");

const JOURNEY = {
  app: { baseUrl: "https://example.test/" },
  tasks: [{ instruction: "Find out what this costs." }],
  passCriteria: [{ id: "tasks-completed" }],
  failCriteria: [{ id: "tasks-blocked" }],
};

/**
 * A driver that records what it was asked to do and answers plausibly.
 *
 * `dead: true` is a page that takes every click and does nothing -- which is what
 * most real frustration is made of, and the case the director has to be able to
 * tell apart from a page that works.
 */
function fakeBrowser({ clickThrows = false, dead = false, url = "https://example.test/", box } = {}) {
  const calls = [];
  let currentUrl = url;
  let revision = 0;
  return {
    calls,
    async open(target) { calls.push(["open", target]); },
    async snapshot() {
      calls.push(["snapshot"]);
      return { stdout: `[e1] link Pricing\n[e2] button Get started\n[rev ${revision}]` };
    },
    async scrollIntoView(target) { calls.push(["scrollIntoView", target]); },
    async click(target) {
      calls.push(["click", target]);
      if (clickThrows) throw new Error("element not found");
      if (!dead) { revision += 1; currentUrl = `${url}page-${revision}`; }
    },
    async scroll(options) {
      calls.push(["scroll", options.direction, options.amount]);
      if (!dead) revision += 1;
    },
    async fill(target, value) {
      calls.push(["fill", target, value]);
      if (!dead) revision += 1;
    },
    async press(key) { calls.push(["press", key]); if (!dead) revision += 1; },
    async getUrl() { return currentUrl; },
    async getElementBox(target) { calls.push(["getElementBox", target]); return { details: box }; },
    async screenshot(options) { calls.push(["screenshot", options.path]); },
  };
}

function fakeRecorder() {
  const events = [];
  return { events, async record(type, summary, data) { events.push({ type, summary, data }); } };
}

const run = (director, browser, recorder) =>
  director.run({ journey: JOURNEY, profile: {}, browser, recorder,
    artifacts: { screenshotsDir: "/tmp/persona-test-shots" } });

const impatient = {
  id: "friedrich_wolf",
  persona: { name: "Friedrich Wolf", occupation: "an architect", goals: ["find the price"],
    constraints: ["vague marketing copy"] },
  behavior: { seed: 7, patience: 0.05, persistence: 0.02, irritability: 0.95, angerReactivity: 0.9,
    angerRecovery: 0.05, impulsivity: 0.5, repeatFailureTolerance: 0.02, exploration: 0.2 },
  abilities: {},
};
const dogged = {
  ...impatient, id: "dogged",
  behavior: { ...impatient.behavior, patience: 0.95, persistence: 0.98, irritability: 0.05,
    angerReactivity: 0.05, angerRecovery: 0.9, repeatFailureTolerance: 0.95 },
};

test("an ACTION becomes driver calls, not tool names", async () => {
  // The whole point of the vocabulary: the persona decides to click a thing, and
  // the translation into scrollIntoView + click is the director's business.
  const browser = fakeBrowser();
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([
      { type: "CLICK", target: "e1", reasoning: "Right, where's the price." },
      { type: "SCROLL", content: "down", target: "600" },
      { type: "TYPE", target: "e9", content: "hello" },
      { type: "DONE", content: "It costs nothing, apparently." },
    ]),
  });
  const verdict = await run(director, browser, fakeRecorder());

  const kinds = browser.calls.map((call) => call[0]);
  assert.ok(kinds.includes("scrollIntoView") && kinds.includes("click"));
  assert.deepEqual(browser.calls.find((call) => call[0] === "scroll"), ["scroll", "down", 600]);
  assert.deepEqual(browser.calls.find((call) => call[0] === "fill"), ["fill", "e9", "hello"]);
  assert.equal(verdict.status, "passed");
});

test("a page that takes the click and does nothing is what wears a person down", async () => {
  // The director must distinguish "it worked" from "it did nothing", and only the
  // second should cost the persona anything. Asserting that a click changed the
  // page -- rather than looking -- held frustration at 0.00 for an entire live
  // run and made the whole affect model inert.
  const script = () => scriptedActor([
    { type: "CLICK", target: "e1" }, { type: "CLICK", target: "e2" },
    { type: "CLICK", target: "e1" }, { type: "CLICK", target: "e2" },
    { type: "DONE", content: "got there" }]);

  const responsiveRecorder = fakeRecorder();
  const responsive = await run(new PersonaDirector({ profile: impatient, actor: script(),
    sleepFn: async () => {} }), fakeBrowser(), responsiveRecorder);
  assert.equal(responsive.status, "passed");
  const calmest = responsiveRecorder.events.filter((e) => e.type === "persona.affect");
  assert.equal(calmest.at(-1).data.state.frustration, 0);

  const deadRecorder = fakeRecorder();
  const onDeadPage = await run(new PersonaDirector({ profile: impatient, actor: script(),
    sleepFn: async () => {} }), fakeBrowser({ dead: true }), deadRecorder);
  const frustrated = deadRecorder.events.filter((e) => e.type === "persona.affect");
  assert.ok(frustrated.at(-1).data.state.frustration > 0,
    "a page that ignores you has to cost something");
  assert.notEqual(onDeadPage.status, "passed");
});

test("a persona who would walk away actually walks away", async () => {
  // Coping has to be control flow. A synthetic user who would have left and did
  // not is a script, not a user. Same page, same failures, two personas.
  const script = scriptedActor([{ type: "CLICK", target: "e1", reasoning: "Try this." }]);
  const quitter = new PersonaDirector({ profile: impatient, actor: script, sleepFn: async () => {}, maxSteps: 25 });
  const quitterVerdict = await run(quitter, fakeBrowser({ clickThrows: true }), fakeRecorder());
  assert.equal(quitterVerdict.status, "failed");
  assert.match(quitterVerdict.summary, /Walked away|Gave up/);

  const stayer = new PersonaDirector({ profile: dogged, actor: scriptedActor([
    { type: "CLICK", target: "e1" }]), sleepFn: async () => {}, maxSteps: 25 });
  const stayerVerdict = await run(stayer, fakeBrowser({ clickThrows: true }), fakeRecorder());
  assert.equal(stayerVerdict.status, "inconclusive");
  assert.match(stayerVerdict.summary, /Still going after 25 actions/);
});

test("giving up is a verdict, not an absence of one", async () => {
  // The Pi director answered "inconclusive" whenever nothing called
  // journey_finish, which reads as a harness fault when it is usually the page's.
  const director = new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([{ type: "GIVE_UP", content: "no price anywhere, I'm done" }]) });
  const verdict = await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(verdict.status, "failed");
  assert.equal(verdict.criteria.find((c) => c.id === "tasks-completed").result, "not-met");
  assert.equal(verdict.criteria.find((c) => c.id === "tasks-blocked").result, "met");
  assert.equal(verdict.blockers.length, 1);
  assert.match(verdict.blockers[0].description, /frustration/);
  assert.match(verdict.summary, /no price anywhere/);
});

test("the verdict uses the vocabulary the schema actually accepts", async () => {
  // journeytest-core validates criteria against met | not-met | blocked |
  // not-observed, and never names them in its prompt -- which is how a live run
  // lost its whole verdict to "passed"/"failed"/"inconclusive".
  const allowed = new Set(["met", "not-met", "blocked", "not-observed"]);
  for (const profile of [impatient, dogged]) {
    for (const step of [{ type: "DONE", content: "found it" }, { type: "GIVE_UP", content: "nope" }]) {
      const director = new PersonaDirector({ profile, actor: scriptedActor([step]), sleepFn: async () => {} });
      const verdict = await run(director, fakeBrowser(), fakeRecorder());
      assert.ok(["passed", "failed", "blocked", "inconclusive"].includes(verdict.status));
      for (const criterion of verdict.criteria) assert.ok(allowed.has(criterion.result), criterion.result);
    }
  }
});

test("an imprecise pointer misses a small control, and the miss is what happens", async () => {
  // The scatter is a property of the hand, not the target, so an undersized
  // control is genuinely missed -- measured at 72% for a 24px icon at precision
  // 0.2, against 0% for a full-sized button. WCAG 2.5.5 asks for 44x44 for this
  // reason, and a person who misses gets nothing, so neither does the run.
  const profile = { ...impatient, abilities: { motor: { pointerPrecision: 0.0 } } };
  const browser = fakeBrowser({ box: { x: 100, y: 100, width: 16, height: 16 } });
  const recorder = fakeRecorder();
  const director = new PersonaDirector({ profile, sleepFn: async () => {},
    actor: scriptedActor([{ type: "CLICK", target: "e1" }]), maxSteps: 1 });
  await run(director, browser, recorder);

  const pointer = recorder.events.find((event) => event.type === "persona.pointer");
  assert.ok(pointer, "the aim is recorded, because it is evidence");
  assert.equal(pointer.data.missed, true);
  // The click never reached the driver.
  assert.ok(!browser.calls.some((call) => call[0] === "click"));

  // And a precise pointer is not scattered at all.
  const precise = fakeBrowser({ box: { x: 100, y: 100, width: 16, height: 16 } });
  await run(new PersonaDirector({ profile: { ...impatient, abilities: { motor: { pointerPrecision: 1 } } },
    actor: scriptedActor([{ type: "CLICK", target: "e1" }]), sleepFn: async () => {}, maxSteps: 1 }),
    precise, fakeRecorder());
  assert.ok(precise.calls.some((call) => call[0] === "click"));

  // A full-sized button is hit by everyone, however shaky the hand -- the model
  // must find undersized targets, not make every control unusable.
  const big = fakeBrowser({ box: { x: 100, y: 100, width: 200, height: 60 } });
  await run(new PersonaDirector({ profile, actor: scriptedActor([{ type: "CLICK", target: "e1" }]),
    sleepFn: async () => {}, maxSteps: 1 }), big, fakeRecorder());
  assert.ok(big.calls.some((call) => call[0] === "click"));
});

test("the record is see, expect, act, observe, reflect, feel -- in that order", async () => {
  const recorder = fakeRecorder();
  const director = new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([
      { type: "CLICK", target: "e1", visible: "A headline and a Pricing link.",
        expectation: "A page with prices on it.",
        observed: "A contact form.", matched: "no", gap: "No prices, just a form." },
      { type: "DONE", content: "nothing here" }]) });
  await run(director, fakeBrowser(), recorder);

  const order = recorder.events.map((event) => event.type)
    .filter((type) => type.startsWith("persona."));
  assert.deepEqual(order.slice(0, 3),
    ["persona.expectation", "persona.reflection", "persona.affect"]);

  const expectation = recorder.events.find((e) => e.type === "persona.expectation");
  assert.equal(expectation.data.visible, "A headline and a Pricing link.");
  assert.equal(expectation.data.expectation, "A page with prices on it.");

  const reflection = recorder.events.find((e) => e.type === "persona.reflection");
  assert.equal(reflection.data.matched, "no");
  assert.equal(reflection.data.gap, "No prices, just a form.");

  const affect = recorder.events.find((e) => e.type === "persona.affect");
  assert.ok(typeof affect.data.state.frustration === "number");
  assert.ok(affect.data.feeling, "the feeling is also stated in words, for a reader");
});

test("the feeling is derived from the gap, never declared by the actor", async () => {
  // A model asked how it feels narrates a feeling and then acts it out, which is
  // unfalsifiable. Asked only what it expected and what it got, the answer can be
  // wrong -- and the emotion follows from the mismatch.
  const cycle = (matched) => scriptedActor([
    { type: "CLICK", target: "e1", expectation: "prices", matched, observed: "something" },
    { type: "CLICK", target: "e2", expectation: "prices", matched, observed: "something" },
    { type: "DONE", content: "enough" }]);

  const frustrationAfter = async (matched) => {
    const recorder = fakeRecorder();
    await run(new PersonaDirector({ profile: impatient, actor: cycle(matched),
      sleepFn: async () => {} }), fakeBrowser(), recorder);
    return recorder.events.filter((e) => e.type === "persona.affect").at(-1).data.state.frustration;
  };

  // Identical mechanics -- a click that worked and changed the page -- and three
  // very different experiences, told apart only by the expectation.
  assert.equal(await frustrationAfter("yes"), 0);
  assert.ok(await frustrationAfter("partly") > 0);
  assert.ok(await frustrationAfter("no") > await frustrationAfter("partly"));
});

test("an unreadable reflection does not invent a disappointment", async () => {
  const { parseReflection } = require("../src/personaActor");
  assert.equal(parseReflection("I think it went fine?"), null);
  assert.equal(parseReflection('{"matched": "sort of"}'), null);
  assert.equal(parseReflection('{"observed":"a form","matched":"NO","gap":"no prices"}').matched, "no");
});

test("a click the page ignores is worse than it looks, and counts", () => {
  // "I clicked and nothing happened" is the shape of most real frustration, and
  // it is invisible if only thrown errors count as failure.
  const ignored = outcomeEvent({ type: "CLICK", target: "e1" }, { failed: false, changed: false });
  assert.equal(ignored.type, "ambiguous_feedback");
  assert.ok(ignored.severity > 0);

  const worked = outcomeEvent({ type: "CLICK", target: "e1" }, { failed: false, changed: true });
  assert.equal(worked.type, "success");

  const broke = outcomeEvent({ type: "CLICK", target: "e1" }, { failed: true, error: "element not found" });
  assert.equal(broke.goalBlocked, true);
});

test("what the persona can hold in mind bounds what they are shown", () => {
  const page = Array.from({ length: 300 }, (_, index) => `[e${index}] link Item ${index}`).join("\n");
  const forgetful = observationFrom(page, { cognition: { workingMemoryItems: 2 } });
  const sharp = observationFrom(page, { cognition: { workingMemoryItems: 12 } });
  assert.ok(forgetful.split("\n").length < sharp.split("\n").length);
  assert.match(forgetful, /and \d+ more things on the page/);
});

test("the persona is described as a person, and feelings as feelings", () => {
  const words = personaInWords(impatient);
  assert.match(words, /Friedrich Wolf/);
  assert.match(words, /very little patience/);
  assert.match(words, /easily irritated/);
  // No trait names, no numbers -- handing a model "frustration: 0.62" invites it
  // to write about the number instead of acting on it.
  assert.doesNotMatch(words, /0\.\d|angerReactivity|irritability:/);

  assert.match(affectInWords({ frustration: 0.8, confusion: 0.1, trust: 1, fatigue: 0 }), /fed up/);
  assert.match(affectInWords({ frustration: 0.1, confusion: 0.6, trust: 1, fatigue: 0 }), /confused/);
  assert.match(affectInWords({ frustration: 0, confusion: 0, trust: 0.1, fatigue: 0 }), /do not trust/);
});

test("an unusable reply from the model does not stall the run", () => {
  assert.equal(parseDecision("I'm not sure what to do here."), null);
  assert.equal(parseDecision('{"action": {"type": "PIROUETTE"}}'), null);
  // Wrapped in a fence, or buried in prose, is still an answer.
  const fenced = parseDecision('```json\n{"visible":"a nav bar","expectation":"a price list",'
    + '"action":{"type":"click","target":"e2"}}\n```');
  assert.equal(fenced.action.type, "CLICK");
  assert.equal(fenced.visible, "a nav bar");
  assert.equal(fenced.expectation, "a price list");
});


test("every conclusion can show the page it is about", async () => {
  // The journey contract requires screenshot evidence on each criterion, and a
  // UX layer reading this run afterwards has nothing to reason about without one.
  // A first run of the director took no captures at all and lost its whole
  // verdict to validation.
  const browser = fakeBrowser();
  const recorder = fakeRecorder();
  const verdict = await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([{ type: "CLICK", target: "e1" }, { type: "DONE", content: "found it" }]) }),
    browser, recorder);

  const shots = browser.calls.filter((call) => call[0] === "screenshot").map((call) => call[1]);
  // Arriving, changing page, and leaving are all worth remembering.
  assert.ok(shots.length >= 3, `expected captures on arrival, navigation and exit, got ${shots.length}`);
  assert.match(shots[0], /001-arrived\.png$/);
  assert.match(shots.at(-1), /left-done\.png$/);
  for (const criterion of verdict.criteria) {
    assert.ok(criterion.evidence?.screenshot, `${criterion.id} cites no screenshot`);
  }
  // And the captures are recorded, so they reach the run's artifact list.
  assert.ok(recorder.events.some((event) => event.type === "browser.screenshot"));
});

test("a capture that fails does not end the journey", async () => {
  const browser = fakeBrowser();
  browser.screenshot = async () => { throw new Error("disk full"); };
  const verdict = await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([{ type: "DONE", content: "fine" }]) }), browser, fakeRecorder());
  assert.equal(verdict.status, "passed");
});

test("simulated reading time is charged to the persona, not to the wall clock", async () => {
  // A live run slept 83 real seconds per turn at 260 words per minute -- two
  // hours for a forty-step journey, spent doing nothing. The behaviour model
  // still gets the full duration, so patience and fatigue respond as before.
  const slept = [];
  const wordy = { ...impatient, abilities: { reading: { wordsPerMinute: 60 } } };
  const recorder = fakeRecorder();
  await run(new PersonaDirector({ profile: wordy, scale: 0,
    sleepFn: async (ms) => { slept.push(ms); },
    actor: scriptedActor([{ type: "READ" }, { type: "DONE", content: "done" }]) }),
    fakeBrowser(), recorder);
  assert.ok(Math.max(...slept) <= 200, `slept up to ${Math.max(...slept)}ms of real time`);

  // Turned up, the same run waits in real time -- for watching one live.
  const watched = [];
  await run(new PersonaDirector({ profile: wordy, scale: 1,
    sleepFn: async (ms) => { watched.push(ms); },
    actor: scriptedActor([{ type: "READ" }, { type: "DONE", content: "done" }]) }),
    fakeBrowser(), fakeRecorder());
  assert.ok(Math.max(...watched) > Math.max(...slept));
});


test("walking away needs a reason, not just a dice roll", async () => {
  // Coping is sampled, so "abandon" comes up ~1.4% of the time even for a fresh,
  // contented persona -- over a long journey that is a coin toss on ending the
  // run for nothing, and it did end one after three actions at frustration 0.15.
  const recorder = fakeRecorder();
  const verdict = await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([{ type: "READ" }, { type: "READ" }, { type: "READ" },
      { type: "READ" }, { type: "READ" }, { type: "DONE", content: "seen enough" }]) }),
    fakeBrowser(), recorder);
  // Nothing went wrong on this page, so nobody stormed off.
  assert.equal(verdict.status, "passed");

  // But a page that keeps failing them does earn it.
  const failing = await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    maxSteps: 30, actor: scriptedActor([{ type: "CLICK", target: "e1" }]) }),
    fakeBrowser({ clickThrows: true }), fakeRecorder());
  assert.equal(failing.status, "failed");
  assert.match(failing.summary, /Walked away|Gave up/);
});

test("nearly leaving is recorded, because tolerating a page is not the same as liking it", async () => {
  const seen = [];
  for (let seed = 1; seed <= 12 && !seen.length; seed += 1) {
    const recorder = fakeRecorder();
    await run(new PersonaDirector({
      profile: { ...impatient, behavior: { ...impatient.behavior, seed } }, sleepFn: async () => {},
      maxSteps: 12, actor: scriptedActor([{ type: "READ" }]) }), fakeBrowser(), recorder);
    seen.push(...recorder.events.filter((event) => event.type === "persona.nearly_left"));
  }
  assert.ok(seen.length > 0, "an urge to leave that was not acted on should still be evidence");
});

test("taking in a page is skimming, not reading every word", async () => {
  // Charged in full, one page view came to 83 seconds and drove fatigue up 0.138
  // a turn -- every persona exhausted after eight pages regardless of the page.
  const slept = [];
  const slowReader = { ...impatient, abilities: { reading: { wordsPerMinute: 30 } } };
  await run(new PersonaDirector({ profile: slowReader, scale: 1,
    sleepFn: async (ms) => { slept.push(ms); },
    actor: scriptedActor([{ type: "READ" }, { type: "DONE", content: "done" }]) }),
    fakeBrowser(), fakeRecorder());
  assert.ok(Math.max(...slept) <= 20000, `charged ${Math.max(...slept)}ms for one page view`);
});

test("deciding and reflecting can run on different models", async () => {
  // The persona's voice is worth the better model; the expectation comparison is
  // a factual question a cheap one answers as well, and it runs every turn.
  const { llmActor } = require("../src/personaActor");
  const asked = [];
  const complete = async ({ model, system }) => {
    asked.push({ model, kind: /Compare what you expected/.test(system) ? "reflect" : "decide" });
    return /Compare what you expected/.test(system)
      ? '{"observed":"a form","matched":"no","gap":"no prices"}'
      : '{"visible":"a nav","expectation":"prices","action":{"type":"CLICK","target":"e1"}}';
  };
  const actor = llmActor({ model: "big-model", reflectModel: "alias-fast", complete });
  assert.equal(actor.reflectModel, "alias-fast");

  await actor({ profile: impatient, tasks: ["find the price"], observation: "[e1] Pricing",
    affect: "", history: [] });
  await actor.reflect({ profile: impatient, expectation: "prices",
    action: { type: "CLICK", target: "e1" }, observation: "[e2] Contact form" });

  assert.deepEqual(asked, [{ model: "big-model", kind: "decide" },
    { model: "alias-fast", kind: "reflect" }]);

  // Unset, reflection stays on the acting model: a model id only means something
  // against the endpoint serving it.
  assert.equal(llmActor({ model: "only-model", complete }).reflectModel, "only-model");
});

test("a stumble on the way to the model does not lose the run", async () => {
  // A router that picks the model for you can hand a request to something briefly
  // unavailable -- the first call of a session took 45s against an endpoint that
  // then answered in 3. Every turn depends on this call, so losing a whole
  // journey to one transient 502 is the wrong trade.
  const { completion } = require("../src/personaActor");
  let calls = 0;
  const flaky = async () => {
    calls += 1;
    if (calls < 3) { const e = new Error("upstream hiccup"); e.status = 502; throw e; }
    return { ok: true, async json() { return { choices: [{ message: { content: "third time" } }] }; } };
  };
  const originalFetch = globalThis.fetch;
  globalThis.fetch = flaky;
  try {
    const waited = [];
    const answer = await completion({ system: "s", user: "u", model: "auto", apiKey: "k",
      baseUrl: "https://example.test/v1", wait: async (ms) => { waited.push(ms); } });
    assert.equal(answer, "third time");
    assert.equal(calls, 3);
    assert.deepEqual(waited, [1500, 3000], "the pause grows between attempts");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("a request that can never succeed is not retried", async () => {
  // A bad key or a model the endpoint does not serve is rejected identically
  // every time; retrying burns the budget and buries the real cause.
  const { completion } = require("../src/personaActor");
  let calls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    calls += 1;
    return { ok: false, status: 401, async text() { return "Invalid API key"; } };
  };
  try {
    await assert.rejects(() => completion({ system: "s", user: "u", model: "auto", apiKey: "bad",
      baseUrl: "https://example.test/v1", wait: async () => {} }), /Invalid API key/);
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("an empty completion counts as a failure worth retrying", async () => {
  // The caller cannot act on it, and a router that just picked a different model
  // often can do better on the next attempt.
  const { completion } = require("../src/personaActor");
  let calls = 0;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => {
    calls += 1;
    return { ok: true, async json() {
      return { choices: [{ message: { content: calls < 2 ? "   " : "an answer" } }] }; } };
  };
  try {
    assert.equal(await completion({ system: "s", user: "u", model: "auto", apiKey: "k",
      baseUrl: "https://example.test/v1", wait: async () => {} }), "an answer");
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
