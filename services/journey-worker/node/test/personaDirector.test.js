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

const run = (director, browser, recorder, screenshotsDir = "/tmp/persona-test-shots") =>
  director.run({ journey: JOURNEY, profile: {}, browser, recorder,
    artifacts: { screenshotsDir } });

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
  // Driven by a page that does not answer rather than by hunting for a seed on a
  // contented persona. Feeling like leaving is what frustration produces, so the
  // test produces frustration: a dead page, where nothing a click does changes
  // anything. Searching seeds instead made this depend on how much probability
  // mass "abandon" happened to carry -- it went quiet the moment the coping table
  // learned to say "carry on", which is a correct change to the model and was not
  // a reason for a test about giving up to fail.
  // Someone dogged on a page that does not answer: the exact shape of the thing.
  // Frustration climbs, so "abandon" gets real weight in the distribution and is
  // sampled -- and their tolerance (repeatFailureTolerance 0.95 plus persistence
  // 0.98) is past anything frustration can reach, so they never actually go. That
  // is a page somebody is tolerating rather than enjoying, and it is worth
  // recording.
  const seen = [];
  for (let seed = 1; seed <= 12 && !seen.length; seed += 1) {
    const recorder = fakeRecorder();
    await run(new PersonaDirector({
      profile: { ...dogged, behavior: { ...dogged.behavior, seed } }, sleepFn: async () => {},
      maxSteps: 14, actor: scriptedActor([{ type: "CLICK", target: "e1" }]) }),
      fakeBrowser({ dead: true }), recorder);
    seen.push(...recorder.events.filter((event) => event.type === "persona.nearly_left"));
    // Never actually left: that is what makes it "nearly".
    assert.ok(!recorder.events.some((event) =>
      event.type === "agent.end" && event.data?.type === "abandoned"),
      "this persona's tolerance is past what frustration can reach");
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

test("what the actor is told comes from the pixels, not from the whole tree", async () => {
  // The tree is complete, which is exactly what is wrong with it as a model of
  // seeing: handed all of it, an impatient short-sighted persona reads all of it
  // and behaves like a patient one with perfect vision. Perception is only doing
  // its job if what reaches the actor is *smaller* than what is on the page.
  const seen = [];
  const perception = {
    available: true,
    async perceive({ elements, behavior, abilities }) {
      seen.push({ elements, behavior, abilities });
      return {
        observation: "[e1] link Pricing",
        eyes: { blurPx: 1.95 }, scan: { pattern: "spotted", fixationBudget: 6 },
        counts: { elements: 3, legible: 2, fixated: 1, notPerceived: 1, notLookedAt: 1 },
        notPerceived: [{ selector: "p@0,400", reason: "too little contrast to make anything out" }],
        notLookedAt: [{ selector: "e2" }],
      };
    },
  };
  const actorSaw = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing", box: { x: 0, y: 0, width: 60, height: 20 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0,
    }),
    frames: () => [{ data: "F1" }, { data: "F2" }],
    actor: async ({ observation }) => {
      actorSaw.push(observation);
      return { visible: "a link", expectation: "prices", action: { type: "DONE", content: "found it" } };
    },
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.equal(actorSaw[0], "[e1] link Pricing",
    "the actor gets what was looked at, not the accessibility tree");
  assert.deepEqual(seen[0].behavior, impatient.behavior, "the traits are what choose the scan pattern");

  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.ok(looked, "what was not seen is evidence and has to reach the record");
  assert.equal(looked.data.notPerceived[0].selector, "p@0,400");
  assert.deepEqual(looked.data.notLookedAt, ["e2"]);
});

test("with no perception service the run still sees the page the old way", async () => {
  // Perception makes a run truer; it is never allowed to make a run fail. A
  // service that is absent, broken or slow leaves the tree-based observation
  // exactly as it was.
  const actorSaw = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    perception: { available: true, perceive: async () => null },
    walk: async () => { throw new Error("the browser went away mid-batch"); },
    actor: async ({ observation }) => {
      actorSaw.push(observation);
      return { visible: "", expectation: "", action: { type: "DONE", content: "done" } };
    },
  });
  await run(director, fakeBrowser(), fakeRecorder());

  assert.match(actorSaw[0], /\[e1\] link Pricing/, "the snapshot is still there when the walk is not");
});

test("a task that is not a plain string still reaches the persona as words", async () => {
  // String(task) on an object is "[object Object]", which would become the thing
  // the persona came to do -- and, once perception is goal-directed, the thing
  // their eye hunts for on every page.
  const seen = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: async ({ tasks }) => {
      seen.push(tasks);
      return { visible: "", expectation: "", action: { type: "DONE", content: "done" } };
    },
  });
  await director.run({
    journey: { app: { baseUrl: "https://example.test/" },
      tasks: ["Find the price.", { description: "Then decide if it is worth it." }, { nothing: true }] },
    profile: {}, browser: fakeBrowser(), recorder: fakeRecorder(),
    artifacts: { screenshotsDir: "/tmp/persona-test-shots" },
  });

  assert.deepEqual(seen[0], ["Find the price.", "Then decide if it is worth it."],
    "a task with no text in it is dropped rather than turned into a string that means nothing");
});

test("the thing they came for, on the screen, and missed", async () => {
  // The strongest finding perception can produce, and the one a usability report
  // cannot currently make: not "the page is confusing" but "the price was
  // legible, in the viewport, and this person's patience ran out first".
  const perception = {
    available: true,
    async perceive() {
      return {
        observation: "[e1] heading Everything in one place",
        eyes: {}, scan: { pattern: "spotted", fixationBudget: 6, why: [] },
        counts: { elements: 3, legible: 3, fixated: 1, notPerceived: 0, notLookedAt: 2 },
        notPerceived: [],
        notLookedAt: [
          { selector: "price", name: "From EUR 49 per month", goalAffinity: 0.85 },
          { selector: "f4", name: "Everything you need for step 4", goalAffinity: 0 },
        ],
      };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({ elements: [{ selector: "e1", box: { x: 0, y: 0, width: 10, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA" }),
    frames: () => [],
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.deepEqual(looked.data.missedWhatTheyCameFor,
    [{ selector: "price", name: "From EUR 49 per month", goalAffinity: 0.85 }]);
});

test("an action that is not like this person is sent back before it reaches the page", async () => {
  // The whole point of the gate: the persona is a constraint on what happens,
  // not an instruction the model may drift away from. A patient, thorough action
  // from an impatient persona should never get as far as the browser.
  const asked = [];
  const actor = async (input, options = {}) => {
    asked.push(options.notLikeYou || "");
    return asked.length === 1
      ? { visible: "marketing copy", expectation: "eventually a price",
          action: { type: "READ", target: "the manifesto" } }
      : { visible: "marketing copy", expectation: "there is no price here",
          action: { type: "GIVE_UP", content: "No prices. Done wasting time." } };
  };
  actor.judgeAdherence = async ({ user }) =>
    /READ/.test(user)
      ? '{"score": 2, "flaw": "someone this impatient would not settle in for a fourth page of copy"}'
      : '{"score": 9, "flaw": ""}';

  const browser = fakeBrowser();
  const recorder = fakeRecorder();
  const verdict = await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {}, actor }),
    browser, recorder);

  assert.equal(asked.length, 2, "the first action was rejected and another asked for");
  assert.match(asked[1], /impatient/, "and the criticism went back with the request");
  const scored = recorder.events.find((event) => event.type === "persona.adherence");
  assert.equal(scored.data.passed, true);
  assert.equal(scored.data.attempts, 2);
  assert.equal(verdict.status, "failed", "they gave up, which is what that persona does");
});

test("with no judge available the persona acts exactly as before", async () => {
  // The gate improves a persona; a run must not depend on it. scriptedActor has
  // no judge at all, which is the same situation as an unreachable one.
  const browser = fakeBrowser();
  const recorder = fakeRecorder();
  await run(new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: scriptedActor([{ type: "CLICK", target: "e1" }, { type: "DONE", content: "fine" }]),
  }), browser, recorder);

  assert.ok(browser.calls.some((call) => call[0] === "click"));
  assert.equal(recorder.events.find((event) => event.type === "persona.adherence"), undefined);
});

test("what the second step is told includes what the first two steps got wrong", async () => {
  // The claim: better with each action, not each session. A criticism that has
  // come back twice is a standing lesson by the next step, without waiting for
  // an offline compile or even for this run to end.
  const { PersonaMemoryBank } = require("../src/memoryBank");
  const memory = new PersonaMemoryBank({});
  const constraintsSeen = [];

  const flaws = [
    "Low patience makes such lengthy rereading unlikely",
    "His extreme impatience makes reading more vague copy improbable",
    "",
  ];
  let step = 0;
  const actor = async ({ constraints }) => {
    constraintsSeen.push(constraints || "");
    step += 1;
    return step >= 3
      ? { visible: "copy", expectation: "no price", action: { type: "GIVE_UP", content: "Enough." } }
      : { visible: "copy", expectation: "a price", action: { type: "READ", target: "the copy" } };
  };
  // A judge that criticises the first two actions and passes the third.
  actor.judgeAdherence = async () => {
    const flaw = flaws[Math.min(step - 1, flaws.length - 1)];
    return flaw ? `{"score": 2, "flaw": "${flaw}"}` : '{"score": 10, "flaw": ""}';
  };

  await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {}, actor, memory,
    // No regeneration, so each step's own judgement is the only thing stored.
    gate: new (require("../src/adherence").AdherenceGate)({ judge: actor.judgeAdherence, maxAttempts: 1 }),
  }), fakeBrowser(), fakeRecorder());

  assert.equal(constraintsSeen[0].includes("know about yourself"), false,
    "they arrive knowing nothing about themselves");
  assert.match(constraintsSeen[2], /What you already know about yourself/,
    "and by the third step the repeated criticism is a standing lesson");
  assert.match(constraintsSeen[2], /rereading/);
});

test("the run says what the persona already knew when they arrived", async () => {
  const { PersonaMemoryBank } = require("../src/memoryBank");
  const memory = new PersonaMemoryBank({});
  for (const flaw of ["Low patience makes lengthy rereading unlikely",
    "Extreme impatience makes rereading vague copy improbable"]) {
    memory.store({ action: { type: "READ" }, score: 2, flaw, passed: false });
  }
  const recorder = fakeRecorder();
  await run(new PersonaDirector({ profile: impatient, sleepFn: async () => {}, memory,
    actor: scriptedActor([{ type: "DONE", content: "fine" }]) }), fakeBrowser(), recorder);

  const started = recorder.events.find((event) => event.type === "agent.start");
  assert.equal(started.data.memory.episodes, 2);
  assert.equal(started.data.memory.lessons.length, 1);
});

test("the page as they saw it is kept, but only when it is evidence of something", async () => {
  // A clean screenshot beside "they could not read this" invites the reader to
  // disagree, correctly. The degraded capture is the only honest image -- and the
  // service could produce it from the start while nothing ever asked.
  const { mkdtempSync, readdirSync } = require("node:fs");
  const { tmpdir } = require("node:os");
  const shots = mkdtempSync(require("node:path").join(tmpdir(), "aux-seen-"));

  const asked = [];
  const unreadable = [{ selector: "p.fine", name: "Prices exclude VAT", reason: "too little contrast" }];
  let step = 0;
  const perception = {
    available: true,
    async perceive(request) {
      asked.push(request.returnSeenImage);
      step += 1;
      return {
        observation: "[e1] heading Plans",
        eyes: { acuity: 0.35, blurPx: 1.95 }, scan: { pattern: "f", fixationBudget: 12, why: [] },
        counts: { elements: 3, fixated: 1, notPerceived: 1, notLookedAt: 0 },
        // Something unreadable on the first step only.
        notPerceived: step === 1 ? unreadable : [],
        notLookedAt: [],
        // A one-pixel JPEG is enough to prove the bytes get written.
        seenImageBase64: "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsL"
          + "DBkSEw8UHRofGh0aHBwcJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAQAA"
          + "AAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AmAA=",
      };
    },
  };
  await run(new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({ elements: [{ selector: "e1", box: { x: 0, y: 0, width: 10, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA" }),
    frames: () => [],
    actor: scriptedActor([{ type: "SCROLL", content: "down" }, { type: "DONE", content: "seen" }]),
  }), fakeBrowser(), fakeRecorder(), shots);

  assert.deepEqual(asked, [true, true], "the degraded capture is always requested");
  const kept = readdirSync(shots).filter((name) => name.endsWith("-as-they-saw-it.jpg"));
  assert.equal(kept.length, 1,
    "written for the step that found something unreadable, and not for the other");
});

// Perception measures pixels against boxes, and both are only comparable while
// the page holds still. The reveal keeper scrolls the whole document every
// 1500ms, through a pass that takes longer than that. A live run published
// "Fails WCAG AA contrast: 'Talent Augmentation OS'" at 1:1 as its headline
// finding, for a persona with 0.95 acuity and 0.92 contrast sensitivity, on a
// navigation bar the same run clicked twice -- the crops had landed on blank
// page. The report was confidently wrong, which is worse than a report with a
// gap in it.
test("the page is held still for the whole look, and let go afterwards", async () => {
  const order = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    perception: { available: true, perceive: async () => { order.push("perceive"); return null; } },
    walk: async () => {
      order.push("walk");
      return { elements: [{ selector: "e1", box: { x: 0, y: 0, width: 10, height: 10 } }],
        viewport: { width: 1280, height: 577 }, screenshotBase64: "AAA", refs: {}, snapshot: "",
        scrollY: 0, moved: false };
    },
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  director.hold = () => { order.push("hold"); return 1; };
  director.release = () => { order.push("release"); return 0; };

  await run(director, fakeBrowser(), fakeRecorder());

  assert.deepEqual(order.slice(0, 3), ["hold", "walk", "release"],
    "the walk happens inside the hold");
  assert.equal(order.filter((step) => step === "hold").length,
    order.filter((step) => step === "release").length,
    "every hold is released, or the page never scrolls again for the rest of the run");
});

test("a hold is released even when the walk throws", async () => {
  let holds = 0;
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    perception: { available: true, perceive: async () => null },
    walk: async () => { throw new Error("the browser went away mid-batch"); },
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  director.hold = () => { holds += 1; return holds; };
  director.release = () => { holds -= 1; return holds; };

  await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(holds, 0, "a thrown walk must not leave the page frozen for the rest of the run");
});

test("a capture taken while the page moved is not measured at all", async () => {
  // Boxes from one scroll position against pixels from another measure nothing,
  // and the failure is not a missing finding but a confident false one. The tree
  // is still there, so the step falls back to it rather than guessing.
  let perceived = 0;
  const actorSaw = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    perception: { available: true, perceive: async () => { perceived += 1; return {
      observation: "[e1] link Pricing", counts: {}, scan: {}, eyes: {},
      notPerceived: [], notLookedAt: [] }; } },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing", box: { x: 0, y: 0, width: 60, height: 20 } }],
      viewport: { width: 1280, height: 577 }, screenshotBase64: "AAA", refs: {}, snapshot: "",
      scrollY: 0, moved: true, scrollCheck: "moved", scrolledTo: 2400,
    }),
    actor: async ({ observation }) => {
      actorSaw.push(observation);
      return { visible: "", expectation: "", action: { type: "DONE", content: "done" } };
    },
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.equal(perceived, 0, "a capture the boxes do not match is never sent to be measured");
  assert.ok(!recorder.events.some((event) => event.type === "persona.perception"),
    "and nothing is recorded as having been seen");
  assert.notEqual(actorSaw[0], "[e1] link Pricing",
    "the step falls back to the accessibility tree");
});
