"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const { PersonaDirector, boxOf, nameOf, observationFrom, outcomeEvent } = require("../src/personaDirector");
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
  // Acting records too, now that it can: the hand is aimed between committing to
  // an expectation and reflecting on what happened, which is the "act" this
  // test's own title names. It recorded nothing before only because aim() was
  // calling a driver method that does not exist and swallowing the failure.
  assert.deepEqual(order.slice(0, 4),
    ["persona.expectation", "persona.pointer", "persona.reflection", "persona.affect"]);

  // And a hand that could not be aimed says so rather than passing for one that
  // landed. This fake browser offers no boxes, so this is that case.
  const pointer = recorder.events.find((event) => event.type === "persona.pointer");
  assert.equal(pointer.data.measured, false);
  assert.equal(pointer.data.target, "e1");

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
  // Arriving, changing page, and leaving are all worth remembering -- each as
  // a pair now (JRN-9): a viewport "as seen" shot, taken first, and the
  // full-page one the vision critique reads, taken second.
  assert.ok(shots.length >= 6, `expected paired captures on arrival, navigation and exit, got ${shots.length}`);
  assert.match(shots[0], /001-arrived-viewport\.png$/);
  assert.match(shots[1], /001-arrived\.png$/);
  assert.match(shots.at(-1), /left-done\.png$/);
  assert.match(shots.at(-2), /left-done-viewport\.png$/);
  for (const criterion of verdict.criteria) {
    assert.ok(criterion.evidence?.screenshot, `${criterion.id} cites no screenshot`);
    // JRN-9: "the frame the persona was looking at" is the viewport capture,
    // not the full-page composite -- a real person never saw the composite.
    assert.match(criterion.evidence.screenshot, /-viewport\.png$/,
      "criterion evidence cites the viewport capture, not the full-page one");
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

  // Not order.slice(0, 3): capture() now holds too (its own test below), so a
  // real run's first hold/release pair is the "arrived" screenshot's, not
  // the walk's. What this test actually claims -- the walk happens inside
  // its own hold -- is checked directly, regardless of what else holds
  // around it.
  const walkIndex = order.indexOf("walk");
  assert.ok(walkIndex > 0, "the walk actually happened");
  assert.equal(order[walkIndex - 1], "hold", "the walk happens inside a hold");
  assert.equal(order[walkIndex + 1], "release", "...and the hold is released right after it");
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

// JRN-9: a full-page composite is not what a person ever actually saw --
// verdict()'s own evidence field is documented as "the frame the persona
// was looking at when they stopped", which only a viewport capture is.
// capture() now takes both: a viewport shot, for that field, and the
// full-page one (unchanged) for the vision critique, which does need the
// content below whatever the persona happened to have on screen.
test("capture() takes a viewport shot and a full-page shot, tracked separately", async () => {
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  const calls = [];
  const browser = { screenshot: async (options) => { calls.push(options); } };
  const recorder = fakeRecorder();
  const target = await director.capture(
    browser, { artifacts: { screenshotsDir: "/tmp/persona-test-shots" }, recorder }, "arrived");

  assert.equal(calls.length, 2, "one viewport call, one full-page call");
  assert.equal(calls[0].full, undefined, "the viewport call asks for the viewport, not the full page");
  assert.equal(calls[1].full, true, "the second call is the full-page one");
  assert.equal(calls[1].path, target, "capture()'s own return value is the full-page path, unchanged");
  assert.match(calls[0].path, /001-arrived-viewport\.png$/);
  assert.match(calls[1].path, /001-arrived\.png$/);

  assert.deepEqual(director.shots, [calls[1].path]);
  assert.deepEqual(director.viewportShots, [calls[0].path]);
});

test("a failed viewport shot does not cost the run the full-page one", async () => {
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  const browser = {
    screenshot: async (options) => {
      if (!options.full) throw new Error("viewport capture failed");
    },
  };
  const target = await director.capture(
    browser, { artifacts: { screenshotsDir: "/tmp/persona-test-shots" }, recorder: fakeRecorder() }, "arrived");

  assert.ok(target, "the full-page capture still succeeds and is returned");
  assert.deepEqual(director.viewportShots, [], "no viewport shot was recorded");
  assert.equal(director.shots.length, 1, "the full-page shot was still kept");
});

// A live run against an 11855px-tall page stored a "full page" screenshot
// that was the same ~900px hero band repeated roughly thirteen times down the
// full height: capture() called settle() before the screenshot but held
// nothing across it, so the reveal keeper's own background timer could fire
// again while browser.screenshot({full:true}) was still painting a tall
// document, pulling the live page back toward its start position mid-capture.
// look() already holds the page still for exactly this reason; capture()
// did not.
test("the page is held still for the whole capture, and let go afterwards", async () => {
  const order = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  director.hold = () => { order.push("hold"); return 1; };
  director.release = () => { order.push("release"); return 0; };
  director.settle = async () => { order.push("settle"); };

  const browser = { screenshot: async (options) => { order.push(options.full ? "full-page" : "viewport"); } };
  const recorder = fakeRecorder();
  const target = await director.capture(browser, { artifacts: { screenshotsDir: "/tmp/persona-test-shots" }, recorder }, "arrived");

  assert.ok(target, "a successful capture still returns its path");
  // JRN-9: viewport first (the "as seen" shot, taken before anything about
  // the full-page capture can disturb the page), then the full-page one the
  // vision critique reads -- both inside the same hold as settle().
  assert.deepEqual(order, ["hold", "settle", "viewport", "full-page", "release"],
    "settle and both screenshots happen inside the hold, in order");
});

test("a capture's hold is released even when the screenshot throws", async () => {
  let holds = 0;
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  director.hold = () => { holds += 1; return holds; };
  director.release = () => { holds -= 1; return holds; };
  director.settle = async () => {};

  const browser = { screenshot: async () => { throw new Error("the browser went away mid-capture"); } };
  const recorder = fakeRecorder();
  const target = await director.capture(browser, { artifacts: { screenshotsDir: "/tmp/persona-test-shots" }, recorder }, "arrived");

  assert.equal(target, null, "a capture that fails is not worth ending a journey over");
  assert.equal(holds, 0, "a thrown screenshot must not leave the page frozen for the rest of the run");
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

test("a run says what it learned and how often the gate fired", async () => {
  // "The persona gets better with each action" is a claim about a difference
  // between two runs, and only the start of a run was ever written down -- so
  // there was nothing to compare it against. A live run recorded
  // `episodes: 0, lessons: [], persisted: false` at the start and nothing at all
  // at the end, having been judged eight times in between.
  const judged = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {},
    perception: { available: false },
    actor: Object.assign(
      async () => ({ visible: "a link", expectation: "prices",
        action: { type: "CLICK", target: "e1" } }),
      { judgeAdherence: async () => { judged.push(1); return JSON.stringify({ score: 9, flaw: "" }); } }),
    maxSteps: 2,
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const start = recorder.events.find((event) => event.type === "agent.start");
  const end = recorder.events.find((event) => event.type === "agent.end");
  assert.ok(start.data.memory, "what they knew arriving");
  assert.ok(end.data.memory, "and what they know leaving -- the half that was missing");
  assert.ok(end.data.memory.episodes >= start.data.memory.episodes,
    "a judged action is an episode this run leaves behind");
  // A gate that never fires and a gate that is switched off look identical in a
  // report that does not say which.
  assert.ok(end.data.adherence, "how often an action had to be sent back is part of the record");
  assert.equal(end.data.adherence.judged, judged.length);
  assert.equal(typeof end.data.adherence.regenerated, "number");
});

test("running out of the action budget is not the page blocking anyone", async () => {
  // A live report headlined "The journey was blocked before completion", severity
  // critical, over a run whose own record says "Still going after 16 actions
  // without finishing". Nothing had blocked that person -- the harness's budget
  // ran out while they were still working. "Blocked" is a claim about the page,
  // and only giving up or walking away supports it.
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, maxSteps: 2,
    perception: { available: false },
    actor: async () => ({ visible: "a link", expectation: "prices",
      action: { type: "CLICK", target: "e1" } }),
  });

  const result = await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(result.status, "inconclusive");
  const blocked = result.criteria.find((item) => item.id === "tasks-blocked");
  // Not "met": that is what the report reads as a critical blocker.
  assert.equal(blocked.result, "not-observed");
  assert.match(blocked.explanation, /not established/);
  // The criterion vocabulary is "met" | "not-met" | "blocked" | "not-observed" --
  // the verdict status words are rejected by schema validation and abort the
  // whole journey (see CRITERION_RESULT_VOCABULARY in journeytest.js).
  for (const criterion of result.criteria) {
    assert.ok(["met", "not-met", "blocked", "not-observed"].includes(criterion.result),
      `${criterion.result} is not a criterion result`);
  }
  // What is true is still said: they did not finish.
  assert.equal(result.criteria.find((item) => item.id === "tasks-completed").result, "not-met");
});

test("a persona who walks away did meet the blocked criterion", async () => {
  // The other side of it: giving up or walking away is the page costing somebody
  // the journey, and that is exactly what the criterion is for.
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, maxSteps: 6,
    perception: { available: false },
    actor: async () => ({ visible: "", expectation: "",
      action: { type: "GIVE_UP", content: "not worth it" } }),
  });

  const result = await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(result.status, "failed");
  assert.equal(result.criteria.find((item) => item.id === "tasks-blocked").result, "met");
});

test("a full-page capture waits for the page's reveals to run", async () => {
  // `full: true` stitches a capture as tall as the page, and everything below the
  // fold on a site that reveals content on scroll is un-revealed the moment a
  // document loads. The first capture of a run is taken straight after open(), so
  // it is mostly blank: measured on a live run, 7,921 of 8,620 rows near-uniform,
  // 92% of the image. The vision critique filed "Massive empty vertical sections
  // ... a major rendering bug", severity critical, as the most serious finding in
  // the report. It was describing our capture, not the site.
  const order = [];
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, maxSteps: 1,
    perception: { available: false },
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  director.settle = async () => { order.push("settle"); };

  const browser = fakeBrowser();
  const shot = browser.screenshot;
  browser.screenshot = async (options) => { order.push(options.full ? "full-page" : "viewport"); return shot(options); };
  await run(director, browser, fakeRecorder());

  assert.ok(order.length >= 3, "the run must have captured something");
  // Every capture is one settle followed by its own pair of screenshots
  // (JRN-9: viewport, then full-page), and none of them is left unpaired.
  assert.equal(order.filter((step) => step === "settle").length,
    order.filter((step) => step === "viewport").length);
  assert.equal(order.filter((step) => step === "viewport").length,
    order.filter((step) => step === "full-page").length);
  for (let index = 0; index < order.length; index += 3) {
    assert.deepEqual(order.slice(index, index + 3), ["settle", "viewport", "full-page"],
      "both pictures have to be of a settled page");
  }
});

test("a reveal pass that fails does not cost the capture", async () => {
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, maxSteps: 1,
    perception: { available: false },
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });
  // settle() swallows its own failures; this asserts the swallow is real by
  // making the underlying pass throw.
  director.settle = PersonaDirector.prototype.settle.bind({
    ...director, });

  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.ok(recorder.events.some((event) => event.type === "browser.screenshot"),
    "a reveal pass is not worth losing the evidence over");
});

/**
 * Reflection asks whether what was expected actually turned up. It was asked that
 * while holding the accessibility tree, when the expectation had been formed from
 * what the persona could see -- two views of one page, and a comparison across
 * them invents gaps. A live run had the monthly prices in front of the persona,
 * reflected against the tree, and concluded three separate times that "the
 * paragraph detailing the £20 per user per month pricing was not present":
 * frustration hit 1.00 and the report led on a fault the page does not have.
 */
test("reflection judges the page this person can see, not the accessibility tree", async () => {
  const reflectedOn = [];
  let walks = 0;
  const perception = {
    available: true,
    async perceive() {
      return {
        observation: `[e18] button Monthly\n[p@1,2] 3-day free trial, then £20 / user / month.`,
        eyes: {}, scan: {},
        counts: { elements: 2, legible: 2, fixated: 2, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [],
        perceived: [{ selector: "e18", name: "Monthly" }],
        notLookedAt: [],
      };
    },
  };
  const actor = scriptedActor([
    { type: "CLICK", target: "e18", visible: "a button", expectation: "the monthly price" },
    { type: "DONE", content: "£20 a month" },
  ]);
  actor.reflect = async (input) => {
    reflectedOn.push(input);
    return { observed: "the monthly price", matched: "yes", gap: "" };
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception, actor,
    walk: async () => {
      walks += 1;
      return { elements: [{ selector: "e18", role: "button", name: "Monthly",
        box: { x: 0, y: 0, width: 60, height: 20 } }],
        viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 };
    },
    frames: () => [],
  });
  await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(reflectedOn.length, 1, "the click is reflected on");
  assert.match(reflectedOn[0].observation, /£20 \/ user \/ month/,
    "reflection is handed what the eyes delivered, so it cannot deny what they saw");
  assert.doesNotMatch(reflectedOn[0].observation, /\[e1\] link Pricing/,
    "and not the accessibility tree the fake browser returns");

  // The walk that answers "what did the click produce?" is the same walk the next
  // turn decides from. Looking twice would describe one page twice and charge a
  // second perception pass for the privilege.
  assert.equal(walks, 2, "one look per step: the post-action walk is carried, not repeated");
});

test("reflection is told what the thing says on it, not its ref", async () => {
  const reflectedOn = [];
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[e18] button Monthly", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "e18", name: "Monthly" }], notLookedAt: [] };
    },
  };
  const actor = scriptedActor([
    { type: "CLICK", target: "e18", visible: "a button", expectation: "the monthly price" },
    { type: "DONE", content: "done" },
  ]);
  actor.reflect = async (input) => { reflectedOn.push(input); return { observed: "", matched: "yes", gap: "" }; };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception, actor,
    walk: async () => ({
      elements: [{ selector: "e18", role: "button", name: "Monthly", box: { x: 0, y: 0, width: 6, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    frames: () => [],
  });
  await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(reflectedOn[0].targetName, "Monthly",
    "the run has always known e18 is the Monthly button and never said so");
});

test("a target nothing looked at keeps its raw name rather than vanishing", () => {
  assert.equal(nameOf("e18", { perceived: [{ selector: "e18", name: "Monthly" }] }), "Monthly");
  assert.equal(nameOf("e18", { perceived: [], notLookedAt: [{ selector: "e18", name: "Monthly" }] }),
    "Monthly", "legible but never fixated is still a thing with a name on it");
  assert.equal(nameOf("e99", { perceived: [{ selector: "e18", name: "Monthly" }] }), "");
  assert.equal(nameOf("e18", null), "", "no perception, no name -- and no crash");
});

test("a walk that failed costs this step, not the next one as well", async () => {
  // A walk taken the instant an action lands can catch the page still moving, and
  // falls back to the tree -- the guard working as designed. Carrying that forward
  // spent the next turn's look too: cycle 15 scrolled three times and four
  // consecutive steps went by with no perception, two of them on a settled page.
  let walks = 0;
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[e1] link Pricing", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [] };
    },
  };
  const actor = scriptedActor([
    { type: "SCROLL", target: "", visible: "a page", expectation: "more of it" },
    { type: "CLICK", target: "e1", visible: "a link", expectation: "prices" },
    { type: "DONE", content: "found it" },
  ]);
  actor.reflect = async () => ({ observed: "", matched: "yes", gap: "" });
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, actor,
    // The walk right after the scroll catches the page mid-motion. Every other
    // walk is clean.
    walk: async () => {
      walks += 1;
      const stillMoving = walks === 2;
      return { elements: [{ selector: "e1", role: "link", name: "Pricing",
        box: { x: 0, y: 0, width: 6, height: 2 } }],
        viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
        refs: {}, snapshot: "", scrollY: 0, moved: stillMoving };
    },
    frames: () => [],
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const looked = recorder.events.filter((event) => event.type === "persona.perception");
  assert.equal(looked.length, 3,
    "the step after the failed walk looks again rather than inheriting the failure");
});

test("the record says which view answered the question", async () => {
  // An expectation formed from perception and tested against the tree is the
  // comparison that invented three price gaps in cycle 14, and nothing anywhere
  // said which view either side came from -- so it read as one measurement
  // disagreeing with itself.
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[e1] link Pricing", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [] };
    },
  };
  const actor = scriptedActor([
    { type: "CLICK", target: "e1", visible: "a link", expectation: "prices" },
    { type: "DONE", content: "found it" },
  ]);
  actor.reflect = async () => ({ observed: "prices", matched: "yes", gap: "" });
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, actor,
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing", box: { x: 0, y: 0, width: 6, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    frames: () => [],
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const reflected = recorder.events.find((event) => event.type === "persona.reflection");
  assert.equal(reflected.data.decidedFrom, "perceived");
  assert.equal(reflected.data.judgedAgainst, "perceived",
    "both sides of the comparison are the same kind of looking");
});

test("a page that cannot be seen the same way twice concludes nothing", async () => {
  // Cycle 16 lost a run to this. Two scrolls whose post-action walk fell back
  // produced "No description of the company's product or target audience is
  // present" -- about a page whose opening paragraph describes exactly that --
  // and three consecutive false failures took the persona past its tolerance.
  let reflected = 0;
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[e1] link Pricing", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [] };
    },
  };
  const actor = scriptedActor([
    { type: "SCROLL", target: "", visible: "a page", expectation: "what they actually sell" },
    { type: "DONE", content: "gave up on that" },
  ]);
  actor.reflect = async () => { reflected += 1; return { observed: "nav links", matched: "no",
    gap: "no description of the product is present" }; };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, actor,
    // Every walk after the first catches the page still moving.
    walk: (() => {
      let n = 0;
      return async () => {
        n += 1;
        return { elements: [{ selector: "e1", role: "link", name: "Pricing",
          box: { x: 0, y: 0, width: 6, height: 2 } }],
          viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
          refs: {}, snapshot: "", scrollY: 0, moved: n > 1 };
      };
    })(),
    frames: () => [],
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.equal(reflected, 0, "no comparable view, so no conclusion drawn from one");
  const said = recorder.events.find((event) => event.type === "persona.reflection_unavailable");
  assert.ok(said, "and the record says why, rather than a step quietly missing its reflection");
  assert.equal(said.data.decidedFrom, "perceived");
  assert.equal(said.data.judgedAgainst, "tree");
  assert.ok(!recorder.events.some((event) => event.type === "persona.reflection"),
    "a gap nobody could observe is not a gap");
});

test("a run with no eyes at all still reflects, because both sides are the tree", async () => {
  // The rule is that the two views match, not that perception is present. A
  // tree-only run compares tree with tree, which is a comparison.
  let reflected = 0;
  const actor = scriptedActor([
    { type: "CLICK", target: "e1", visible: "a link", expectation: "prices" },
    { type: "DONE", content: "found it" },
  ]);
  actor.reflect = async () => { reflected += 1; return { observed: "prices", matched: "yes", gap: "" }; };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, actor,
    perception: { available: false }, frames: () => [],
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.equal(reflected, 1);
  const reflection = recorder.events.find((event) => event.type === "persona.reflection");
  assert.equal(reflection.data.decidedFrom, "tree");
  assert.equal(reflection.data.judgedAgainst, "tree");
});

test("a walk that caught the page mid-scroll is given one more chance", async () => {
  // The thing moving the page is usually a scroll animation that is over in a
  // moment, and a step that scrolled is exactly the step most likely to hit it.
  let walks = 0;
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[e1] link Pricing", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [] };
    },
  };
  const actor = scriptedActor([
    { type: "SCROLL", target: "", visible: "a page", expectation: "more of it" },
    { type: "DONE", content: "found it" },
  ]);
  actor.reflect = async () => ({ observed: "more of it", matched: "yes", gap: "" });
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, actor,
    // Only the walk immediately after the scroll is spoiled.
    walk: (() => {
      let n = 0;
      return async () => {
        n += 1; walks = n;
        return { elements: [{ selector: "e1", role: "link", name: "Pricing",
          box: { x: 0, y: 0, width: 6, height: 2 } }],
          viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
          refs: {}, snapshot: "", scrollY: 0, moved: n === 2 };
      };
    })(),
    frames: () => [],
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.equal(walks, 3, "the spoiled walk is retried once the page has come to rest");
  const reflection = recorder.events.find((event) => event.type === "persona.reflection");
  assert.equal(reflection.data.judgedAgainst, "perceived",
    "and the retry is what makes the comparison possible");
});

test("a walk that cannot be used says which of its reasons stopped it", async () => {
  // Every fallback path returned the same silent object, so a run that lost half
  // its comparisons looked exactly like a run that never tried. Cycle 19 lost six
  // and the record could not say which of five reasons cost them.
  const cases = [
    { walk: async () => { throw new Error("navigation mid-batch"); },
      perceive: async () => ({ observation: "x" }), expect: /the walk failed: navigation mid-batch/ },
    { walk: async () => ({ elements: [], viewport: {}, screenshotBase64: "AAA" }),
      perceive: async () => ({ observation: "x" }), expect: /the walk found nothing on the page/ },
    { walk: async () => ({ elements: [{ selector: "e1", name: "x", box: {} }], viewport: {}, screenshotBase64: "" }),
      perceive: async () => ({ observation: "x" }), expect: /without a picture/ },
    { walk: async () => ({ elements: [{ selector: "e1", name: "x", box: {} }], viewport: {},
        screenshotBase64: "AAA", moved: true }),
      perceive: async () => ({ observation: "x" }), expect: /the page moved under the walk/ },
    { walk: async () => ({ elements: [{ selector: "e1", name: "x", box: {} }], viewport: {}, screenshotBase64: "AAA" }),
      perceive: async () => null, expect: /the perception service returned nothing/ },
  ];
  for (const one of cases) {
    const director = new PersonaDirector({
      profile: dogged, sleepFn: async () => {}, walk: one.walk, frames: () => [],
      perception: { available: true, perceive: one.perceive },
      actor: scriptedActor([{ type: "DONE", content: "done" }]),
    });
    const recorder = fakeRecorder();
    await run(director, fakeBrowser(), recorder);
    const said = recorder.events.find((event) => event.type === "persona.perception_fallback");
    assert.ok(said, `nothing recorded for ${one.expect}`);
    assert.match(said.data.reason, one.expect);
  }
});

test("a run with no perception configured does not complain every step", async () => {
  // A run with no perception service is a deliberate mode, not a failure, and it
  // is already described by the absence of perception events. Saying so every
  // step would bury the runs where the walk really did fail -- and it broke the
  // see-expect-act-observe-reflect-feel order the record is read in.
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: { available: false }, frames: () => [],
    actor: scriptedActor([{ type: "CLICK", target: "e1", expectation: "prices" },
                          { type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);
  assert.deepEqual(
    recorder.events.filter((event) => event.type === "persona.perception_fallback"), [],
    "nothing was lost, so nothing is reported lost");
});

test("the look before acting gets a second chance too", async () => {
  // Cycle 24 lost the walk on the scroll that revealed the prices and again on
  // the step after it, and the run concluded -- and the report published -- that
  // the page does not state a cost. Three earlier runs read "£200 / user / year"
  // off that same page. A view this person could not obtain is not evidence of
  // what is not on the page.
  let asked = 0;
  const perception = {
    available: true,
    async perceive() {
      asked += 1;
      // The service answers, but with nothing usable, on the first try.
      if (asked === 1) return null;
      return { observation: "[p@1,2] £200 / user / year", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "p@1,2", name: "£200 / user / year" }],
        notLookedAt: [] };
    },
  };
  const seenByActor = [];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, frames: () => [],
    walk: async () => ({
      elements: [{ selector: "p@1,2", role: "paragraph", name: "£200 / user / year",
        box: { x: 0, y: 0, width: 6, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    actor: async ({ observation }) => {
      seenByActor.push(observation);
      return { visible: "a price", expectation: "done", action: { type: "DONE", content: "£200" } };
    },
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.match(seenByActor[0], /£200 \/ user \/ year/,
    "the retry is what puts the price in front of the persona at all");
  assert.ok(recorder.events.some((event) => event.type === "persona.perception"),
    "and the step is recorded as a perceived one, not a lost one");
});

test("a person who took nothing in keeps their evidence", async () => {
  // observation_text joined an empty list into "", the caller tested it for
  // truthiness, and the whole measurement went in the bin -- the counts, the
  // notPerceived list, every legibility finding on the capture. So the runs
  // where somebody could read nothing at all, which is the strongest finding
  // this service can produce, were exactly the runs whose evidence was lost.
  const perception = {
    available: true,
    async perceive() {
      return { observation: "", eyes: {}, scan: {},
        counts: { elements: 7, legible: 0, fixated: 0, notPerceived: 7, notLookedAt: 0 },
        notPerceived: [{ selector: "p@0,400", reason: "too little contrast to make anything out" }],
        perceived: [], notLookedAt: [] };
    },
  };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, frames: () => [],
    walk: async () => ({
      elements: [{ selector: "p@0,400", role: "paragraph", name: "x", box: { x: 0, y: 0, width: 6, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "nothing to see" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.ok(looked, "the measurement is kept, not discarded as a failure");
  assert.equal(looked.data.notPerceived[0].selector, "p@0,400");
  assert.equal(looked.data.counts.notPerceived, 7);
  assert.ok(!recorder.events.some((event) => event.type === "persona.perception_fallback"),
    "and it is not reported as the service having returned nothing");
});

test("a service that really returned nothing is still a fallback", async () => {
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, frames: () => [],
    perception: { available: true, perceive: async () => ({ counts: {} }) },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "x", box: { x: 0, y: 0, width: 6, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const said = recorder.events.find((event) => event.type === "persona.perception_fallback");
  assert.ok(said, "no observation field at all is a failure and still says so");
  assert.match(said.data.reason, /returned nothing/);
});

test("the expectation event carries where the control was, not just what it said", async () => {
  // The report crops its evidence to the element a finding is about -- but only when
  // the finding knows the box, and the one finding built from what a person actually
  // did carried none. So the best-evidenced finding in the report illustrated itself
  // with a whole-page screenshot captioned "page context".
  const box = { x: 320, y: 540, width: 210, height: 48 };
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[e22] button Start 3-day free trial", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], notLookedAt: [],
        perceived: [{ selector: "e22", name: "Start 3-day free trial", box }] };
    },
  };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, frames: () => [],
    walk: async () => ({
      elements: [{ selector: "e22", role: "button", name: "Start 3-day free trial", box }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([
      { type: "CLICK", target: "e22", visible: "a trial button", expectation: "the price" },
      { type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const said = recorder.events.find((event) => event.type === "persona.expectation");
  assert.equal(said.data.targetName, "Start 3-day free trial");
  assert.deepEqual(said.data.targetBox, box);
});

test("a box nobody measured is left undefined rather than guessed", () => {
  const perception = { perceived: [{ selector: "e1", name: "Pricing", box: { x: 1, y: 2, width: 3, height: 4 } }] };
  assert.deepEqual(boxOf("e1", perception), { x: 1, y: 2, width: 3, height: 4 });
  assert.equal(boxOf("e9", perception), null);
  assert.equal(boxOf("e1", null), null);
  // A box without usable dimensions is no box: cropping to it would produce an
  // empty image and a slide that looks broken.
  assert.equal(boxOf("e2", { perceived: [{ selector: "e2", name: "x", box: { x: 0, y: 0 } }] }), null);
  assert.equal(boxOf("e3", { notLookedAt: [{ selector: "e3", name: "x", box: { x: 5, y: 6, width: 7, height: 8 } }] }).width, 7,
    "legible but never fixated still has a place on the page");
});

test("a capture the service does not believe is not evidence about the page", async () => {
  // Cycle 30 ended three journeys with "the page is unreadable" -- 104 regions
  // measuring as flat colour with no ink in them at all, on a page two earlier
  // cycles had read prices off. The perception service already said the capture
  // could not be trusted; nobody asked, so the run took the empty view at face
  // value and the persona reported the instrument's failure as the site's.
  const perception = {
    available: true,
    async perceive() {
      return { observation: "", eyes: {}, scan: {},
        counts: { elements: 31, legible: 0, fixated: 0, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [], notLookedAt: [],
        capture: { trustworthy: false, measured: 31, blankShare: 1.0,
                   reason: "31 of 31 regions the tree says hold something had no ink in them at all" } };
    },
  };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, frames: () => [],
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing", box: { x: 0, y: 0, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const said = recorder.events.find((event) => event.type === "persona.perception_fallback");
  assert.ok(said, "the step is recorded as a lost measurement");
  assert.match(said.data.reason, /did not describe the page/);
  assert.match(said.data.reason, /no ink in them at all/, "and carries the service's own reason");
  assert.ok(!recorder.events.some((event) => event.type === "persona.perception"),
    "it is not recorded as something this person saw");
});

test("a trustworthy capture with nothing legible is still the strongest finding", async () => {
  // The distinction that matters: this person looked at a page that is really
  // there and could read none of it. That is not a failed measurement.
  const perception = {
    available: true,
    async perceive() {
      return { observation: "", eyes: {}, scan: {},
        counts: { elements: 7, legible: 0, fixated: 0, notPerceived: 7, notLookedAt: 0 },
        notPerceived: [{ selector: "p@0,400", reason: "too little contrast to make anything out" }],
        perceived: [], notLookedAt: [],
        capture: { trustworthy: true, measured: 7, blankShare: 0.0, reason: "" } };
    },
  };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, frames: () => [],
    walk: async () => ({
      elements: [{ selector: "p@0,400", role: "paragraph", name: "x", box: { x: 0, y: 0, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.ok(looked, "the measurement is kept");
  assert.equal(looked.data.counts.notPerceived, 7);
  assert.ok(!recorder.events.some((event) => event.type === "persona.perception_fallback"));
});

test("a window pointing past the end of the page is scrolled back, not spent blind", async () => {
  // Cycle 33 lost 22 captures to this: the persona scrolled down a tall page,
  // the page re-rendered into a short one, and the position it had been left at
  // no longer existed -- so the capture was of blank space below the content.
  // Nothing is wrong with the page and nothing is wrong with the eyes.
  let looks = 0;
  const scrolls = [];
  const perception = {
    available: true,
    async perceive() {
      looks += 1;
      if (looks === 1) {
        return { observation: "", eyes: {}, scan: {},
          counts: { elements: 25, legible: 0, fixated: 0, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [], notLookedAt: [],
          capture: { trustworthy: false, measured: 25, blankShare: 1,
                     reason: "25 of 25 regions the tree says hold something had no ink in them" } };
      }
      return { observation: "[e1] link Pricing", eyes: {}, scan: {},
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
        capture: { trustworthy: true, measured: 1, reason: "" } };
    },
  };
  const browser = fakeBrowser();
  browser.eval = async (script) => { scrolls.push(script); return { stdout: "565" }; };

  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception, frames: () => [],
    // The walk reports a viewport starting below the last pixel of the document:
    // 800 into a 1465px page shown through a 900px window stops at 565.
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing", box: { x: 0, y: 0, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 800,
      standing: { y: 800, known: true, viewportHeight: 900, documentHeight: 1465,
                  painted: true, pastTheEnd: true } }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, browser, recorder);

  assert.ok(scrolls.some((script) => script.includes("scrollTo(0, 565)")),
    "it scrolls back to the furthest position the document actually has");
  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.ok(looked, "and the step is recovered rather than lost");
  assert.ok(!recorder.events.some((event) => event.type === "persona.perception_fallback"));
});

test("a journey that never reached the page says so instead of reviewing it", async () => {
  // Cycle 36 sent a persona to a tab with nothing in it: the tree was empty,
  // the walk found no elements, and it spent all sixteen steps scrolling --
  // 800, 800, 1000 -- reporting "the visible area appears empty" each time. The
  // report called that inconclusive *about the site*, which is the same mistake
  // as calling a blank capture an unreadable page.
  let decisions = 0;
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: { available: false }, frames: () => [],
    actor: async () => {
      decisions += 1;
      return { visible: "", expectation: "", action: { type: "SCROLL", target: "800" } };
    },
  });
  const browser = fakeBrowser();
  browser.snapshot = async () => ({ stdout: "   \n  " });
  const recorder = fakeRecorder();
  const result = await run(director, browser, recorder);

  assert.equal(decisions, 0, "a persona is not asked to browse a page that is not there");
  const said = recorder.events.find((event) => event.type === "journey.page_never_arrived");
  assert.ok(said, "and the run says why it stopped, in the record");
  assert.equal(said.data.url, JOURNEY.app.baseUrl);
  const ended = recorder.events.find((event) => event.type === "agent.end");
  assert.equal(ended.data.type, "abandoned");
  assert.match(ended.data.detail, /nothing was ever on the page/);
  assert.ok(result, "the run still returns a verdict rather than throwing");
});

test("a page that did arrive is browsed as usual", async () => {
  // The guard must not fire on a page that is simply quiet.
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: { available: false }, frames: () => [],
    actor: scriptedActor([{ type: "DONE", content: "found it" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.ok(!recorder.events.some((event) => event.type === "journey.page_never_arrived"));
  const ended = recorder.events.find((event) => event.type === "agent.end");
  assert.equal(ended.data.type, "done");
});

test("the perception walk waits for the page's reveals, the same as the camera does", async () => {
  // Cycle 37 lost thirty-two steps to captures the perception service refused,
  // and the record said why in a number nobody read: every one of them was taken
  // while the document measured 1444-1465px, on a page that measures 8620px in
  // the same cycle once it has revealed itself. capture() had settled the page
  // before photographing it since the reveal pass existed. look() never did --
  // so the walk found boxes for sections that had not faded in yet, and no ink
  // where they were.
  const order = [];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    perception: {
      available: true,
      async perceive() {
        order.push("perceive");
        return { observation: "[e1] link Pricing", eyes: {}, scan: {},
          counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
          capture: { trustworthy: true, measured: 1, reason: "" } };
      },
    },
    walk: async () => {
      order.push("walk");
      return { elements: [{ selector: "e1", role: "link", name: "Pricing",
                            box: { x: 0, y: 0, width: 9, height: 2 } }],
        viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
        refs: {}, snapshot: "", scrollY: 0 };
    },
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  director.settle = async () => { order.push("settle"); };
  await run(director, fakeBrowser(), fakeRecorder());

  const walked = order.indexOf("walk");
  assert.ok(walked > 0, "the run must have walked the page");
  assert.equal(order[walked - 1], "settle",
    "the boxes have to come from a page that has finished showing itself");
});

test("a capture the service will not stand behind is taken again, not published", async () => {
  // A failed capture is not a fact about the page; it is the absence of one, and
  // publishing it as one is how a working site came to be described as
  // unreadable. Nothing about the first attempt is an answer, so the page is
  // asked again.
  let looks = 0;
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    perception: {
      available: true,
      async perceive() {
        looks += 1;
        if (looks === 1) {
          return { observation: "", eyes: {}, scan: {},
            counts: { elements: 25, legible: 0, fixated: 0, notPerceived: 25, notLookedAt: 0 },
            notPerceived: [], perceived: [], notLookedAt: [],
            capture: { trustworthy: false, measured: 25, blankShare: 1,
                       reason: "25 of 25 regions the tree says hold something had no ink in them" } };
        }
        return { observation: "[e1] link Pricing", eyes: {}, scan: {},
          counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
          capture: { trustworthy: true, measured: 1, reason: "" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 0, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
      refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.ok(looks >= 2, "the blank capture has to be taken again");
  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.ok(looked, "and the second one is what the step reports");
  assert.ok(!recorder.events.some((event) => event.type === "persona.perception_fallback"),
    "a step that resolved on the second attempt is not a step that lost its measurement");
});

test("a page that will not resolve says how many times it was asked", async () => {
  // "It could not be measured" and "it could not be measured three times over"
  // are different claims about a page, and only the second one is this one.
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    perception: {
      available: true,
      async perceive() {
        return { observation: "", eyes: {}, scan: {},
          counts: { elements: 25, legible: 0, fixated: 0, notPerceived: 25, notLookedAt: 0 },
          notPerceived: [], perceived: [], notLookedAt: [],
          capture: { trustworthy: false, measured: 25, blankShare: 1,
                     reason: "25 of 25 regions the tree says hold something had no ink in them" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 0, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
      refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const fell = recorder.events.find((event) => event.type === "persona.perception_fallback");
  assert.ok(fell, "a page that never resolved still has to say so");
  assert.match(String(fell.data?.reason || ""), /after 3 attempts/,
    "and has to say it was asked more than once");
});

test("the capture the service would not stand behind is kept, not dropped", async () => {
  // Every other picture a run writes is one it believes. This is the only one
  // that is evidence about the measurement rather than about the page, and it
  // was the one thrown away -- so five cycles of hypotheses about renderers,
  // scroll positions and machine capacity were argued from log lines while the
  // image that settles them was decoded, judged and dropped every step.
  const fs = require("node:fs/promises");
  const os = require("node:os");
  const shots = await fs.mkdtemp(require("node:path").join(os.tmpdir(), "refused-"));
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    perception: {
      available: true,
      async perceive() {
        return { observation: "", eyes: {}, scan: {},
          counts: { elements: 25, legible: 0, fixated: 0, notPerceived: 25, notLookedAt: 0 },
          notPerceived: [], perceived: [], notLookedAt: [],
          capture: { trustworthy: false, measured: 25, blankShare: 1,
                     reason: "25 of 25 regions the tree says hold something had no ink in them" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 0, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 900 },
      // A one-pixel PNG stands in for the picture nobody ever looked at.
      screenshotBase64: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
      refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder, shots);

  const fell = recorder.events.find((event) => event.type === "persona.perception_fallback");
  assert.ok(fell?.data?.capture, "the refusal has to say where the picture it refused was kept");
  const written = await fs.readFile(fell.data.capture);
  assert.ok(written.length > 0, "and the picture has to be there");
});

test("the frame is measured when there is no screenshot to be had", async () => {
  // Both sources are the viewport now -- the screenshot because the walk shifts
  // the document into the camera, the frame because a frame is one by
  // definition. The screenshot goes first because it is never blank; the frame is
  // what is left when the walk came back without a picture at all.
  const measured = [];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    frame: () => ({ data: "data:image/jpeg;base64,VIEWPORTFRAME", receivedAt: Date.now() }),
    perception: {
      available: true,
      async perceive(request) {
        measured.push(request);
        return { observation: "[e1] link Pricing", eyes: {}, scan: {},
          counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
          capture: { trustworthy: true, measured: 1, reason: "" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 40, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 577 }, screenshotBase64: "", shiftedBy: 600,
      refs: {}, snapshot: "", scrollY: 600 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  // A walk with no picture is retried, and the frame is what the middle attempt
  // reaches for.
  assert.ok(measured.some((request) => request.screenshotBase64 === "VIEWPORTFRAME"),
    "the frame is measured when the walk brought no picture back");
  const fromFrame = measured.find((request) => request.screenshotBase64 === "VIEWPORTFRAME");
  assert.equal(fromFrame.elements[0].box.y, 40,
    "a frame is the viewport, so its boxes are already where they belong");
});

test("with no frame the screenshot is used, and the boxes are moved to meet it", async () => {
  const measured = [];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    frame: () => null,
    perception: {
      available: true,
      async perceive(request) {
        measured.push(request);
        return { observation: "[e1] link Pricing", eyes: {}, scan: {},
          counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
          capture: { trustworthy: true, measured: 1, reason: "" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 40, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 577 }, screenshotBase64: "PAGESCREENSHOT",
      refs: {}, snapshot: "", scrollY: 600 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  await run(director, fakeBrowser(), fakeRecorder());

  assert.equal(measured[0].screenshotBase64, "PAGESCREENSHOT");
  assert.equal(measured[0].elements[0].box.y, 640,
    "an unshifted screenshot is the document, so 40 in the viewport is 640 in it");
});

test("when one picture is refused the other one is asked, not the same one again", async () => {
  // Each source is wrong in its own way. The frame is what the person is looking
  // at and is whatever the compositor last emitted -- after a navigation that can
  // be the blank first paint with nothing since to replace it, and cycle 45 kept
  // four such frames, 1280x577 of a single colour. The screenshot is never blank
  // and is of the wrong part of the page once scrolled.
  const shown = [];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    frame: () => ({ data: "data:image/jpeg;base64,BLANKFRAME", receivedAt: Date.now() }),
    perception: {
      available: true,
      async perceive(request) {
        shown.push(request.screenshotBase64);
        if (request.screenshotBase64 === "BLANKFRAME") {
          return { observation: "", eyes: {}, scan: {},
            counts: { elements: 9, legible: 0, fixated: 0, notPerceived: 9, notLookedAt: 0 },
            notPerceived: [], perceived: [], notLookedAt: [],
            capture: { trustworthy: false, measured: 9, blankShare: 1,
                       reason: "9 of 9 regions the tree says hold something had no ink in them" } };
        }
        return { observation: "[e1] link Pricing", eyes: {}, scan: {},
          counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
          capture: { trustworthy: true, measured: 1, reason: "" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 40, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 577 }, screenshotBase64: "PAGESCREENSHOT",
      refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.deepEqual(shown.slice(0, 1), ["PAGESCREENSHOT"],
    "the source that is never blank is asked first");
  const looked = recorder.events.find((event) => event.type === "persona.perception");
  assert.equal(looked.data.capturedFrom, "page screenshot");
});

test("the hand is aimed even on a step whose capture was refused", async () => {
  // The walk measures every element on screen whether or not the picture of it
  // can be trusted. Taking the boxes from perception instead meant a refused
  // capture also cost the hand its aim: cycle 45 recorded 42 pointer events and
  // 34 of them had nothing to aim at, on a run with 72 refusals.
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [], frame: () => null,
    perception: {
      available: true,
      async perceive() {
        return { observation: "", eyes: {}, scan: {},
          counts: { elements: 9, legible: 0, fixated: 0, notPerceived: 9, notLookedAt: 0 },
          notPerceived: [], perceived: [], notLookedAt: [],
          capture: { trustworthy: false, measured: 9, blankShare: 1,
                     reason: "9 of 9 regions the tree says hold something had no ink in them" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 10, y: 40, width: 80, height: 24 } }],
      viewport: { width: 1280, height: 577 }, screenshotBase64: "PAGESCREENSHOT",
      refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "CLICK", target: "e1" }, { type: "DONE", content: "done" }]),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const pointer = recorder.events.find((event) => event.type === "persona.pointer");
  assert.ok(pointer, "the hand still had to go somewhere");
  assert.deepEqual(pointer.data.box, { x: 10, y: 40, width: 80, height: 24 },
    "and it is aimed from what the walk measured, not from a capture nobody trusts");
});

test("a frame older than the measurement is not the measurement's frame", async () => {
  // The screencast emits when the compositor produces a frame, and a settled page
  // produces none -- so the newest frame can be the blank first paint after a
  // navigation with nothing since to replace it. Cycle 45 measured four of those:
  // 1280x577 of a single colour, on a page elementFromPoint showed fully drawn.
  // The walk nudges the page a pixel to make a frame happen, so a frame older
  // than the walk is one from before that nudge.
  const shown = [];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, maxSteps: 1, frames: () => [],
    frame: () => ({ data: "data:image/jpeg;base64,STALEFRAME",
                    receivedAt: Date.now() - 60_000 }),
    perception: {
      available: true,
      async perceive(request) {
        shown.push(request.screenshotBase64);
        return { observation: "[e1] link Pricing", eyes: {}, scan: {},
          counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
          notPerceived: [], perceived: [{ selector: "e1", name: "Pricing" }], notLookedAt: [],
          capture: { trustworthy: true, measured: 1, reason: "" } };
      },
    },
    walk: async () => ({
      elements: [{ selector: "e1", role: "link", name: "Pricing",
                   box: { x: 0, y: 40, width: 9, height: 2 } }],
      viewport: { width: 1280, height: 577 }, screenshotBase64: "PAGESCREENSHOT",
      refs: {}, snapshot: "", scrollY: 0 }),
    actor: scriptedActor([{ type: "DONE", content: "done" }]),
  });
  await run(director, fakeBrowser(), fakeRecorder());

  assert.ok(shown.every((item) => item === "PAGESCREENSHOT"),
    "a frame that cannot be shown to be fresh is not used at all");
});

// --- CAP-0: the scan accumulates a memory across steps ------------------------
//
// PersonaDirector.everSeen is the run's own memory of what has been fixated --
// distinct from PersonaMemoryBank, which is standing lessons about the person
// across runs. This must grow across successive look()s and be sent as
// alreadySeen on each perceive() call, so the perception service can
// deprioritise re-fixating the same elements every step.

test("what was fixated on one look is sent as alreadySeen on the next", async () => {
  const calls = [];
  let step = 0;
  const perception = {
    available: true,
    async perceive(options) {
      calls.push(options.alreadySeen);
      step += 1;
      // A different element "wins" each step, as memory-aware scanning would
      // produce -- the test only needs the accumulation, not real scoring.
      return {
        observation: `step ${step}`, eyes: {}, scan: { pattern: "spotted", fixationBudget: 1 },
        counts: { elements: 3, legible: 3, fixated: 1, notPerceived: 0, notLookedAt: 2 },
        notPerceived: [],
        perceived: [{ selector: `e${step}`, role: "link", name: `Row ${step}`,
                     box: { x: 0, y: 0, width: 10, height: 10 } }],
        notLookedAt: [],
      };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({
      elements: [{ selector: "e1", box: { x: 0, y: 0, width: 10, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
    }),
    frames: () => [],
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });

  await director.look({ text: "" }, ["find the price"]);
  await director.look({ text: "" }, ["find the price"]);
  await director.look({ text: "" }, ["find the price"]);

  assert.deepEqual(calls[0], [], "nothing has been seen before the first look");
  assert.deepEqual(calls[1], ["e1"], "what step one fixated is memory going into step two");
  assert.deepEqual(new Set(calls[2]), new Set(["e1", "e2"]), "and it keeps accumulating");
});

test("a capture the service itself distrusts is never folded into the memory", async () => {
  // The step is retried whole when the capture is not trusted, and everSeen is
  // instance state that outlives one attempt -- folding in a discarded
  // measurement's selectors would decay elements this person has never actually
  // seen, permanently, from data the run itself threw away.
  const calls = [];
  const perception = {
    available: true,
    async perceive(options) {
      calls.push(options.alreadySeen);
      return {
        observation: "", eyes: {}, scan: { pattern: "spotted", fixationBudget: 1 },
        counts: { elements: 1, legible: 1, fixated: 1, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [],
        perceived: [{ selector: "untrustworthy-element", role: "link", name: "x",
                     box: { x: 0, y: 0, width: 10, height: 10 } }],
        notLookedAt: [],
        capture: { trustworthy: false, reason: "boxes and pixels disagree" },
      };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({
      elements: [{ selector: "e1", box: { x: 0, y: 0, width: 10, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
    }),
    frames: () => [],
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });

  await director.look({ text: "" }, ["find the price"]);
  await director.look({ text: "" }, ["find the price"]);

  assert.deepEqual(calls[0], []);
  assert.deepEqual(calls[1], [], "the untrustworthy capture's fixation never joined the memory");
});

// --- CAP-4: elements are redacted once, right after the walk ------------------

test("an account menu named as a redact selector never leaves this process", async () => {
  const sent = [];
  const perception = {
    available: true,
    async perceive(options) {
      sent.push(options.elements);
      return { observation: "", eyes: {}, scan: { pattern: "spotted", fixationBudget: 1 },
        counts: { elements: 2, legible: 2, fixated: 1, notPerceived: 0, notLookedAt: 1 },
        notPerceived: [], perceived: [], notLookedAt: [] };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    redactSelectors: [".account-menu"],
    walk: async () => ({
      elements: [
        { selector: ".account-menu", role: "button", name: "Signed in as jane.doe@example.com",
          box: { x: 0, y: 0, width: 10, height: 10 } },
        { selector: "#buy-button", role: "button", name: "Buy now",
          box: { x: 20, y: 0, width: 10, height: 10 } },
      ],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
    }),
    frames: () => [],
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });

  const result = await director.look({ text: "" }, ["find the price"]);

  assert.equal(sent[0][0].name, "[REDACTED]", "sent to the perception service already redacted");
  assert.equal(sent[0][1].name, "Buy now");
  // And what the step itself records -- the same list, once, redacted the same
  // way, because it is the same array both paths were handed.
  assert.equal(result.elements[0].name, "[REDACTED]");
});

test("with no redactSelectors, an unmarked element is unaffected", async () => {
  const sent = [];
  const perception = {
    available: true,
    async perceive(options) {
      sent.push(options.elements);
      return { observation: "", eyes: {}, scan: { pattern: "spotted", fixationBudget: 1 },
        counts: { elements: 1, legible: 1, fixated: 0, notPerceived: 0, notLookedAt: 1 },
        notPerceived: [], perceived: [], notLookedAt: [] };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({
      elements: [{ selector: "#buy-button", role: "button", name: "Buy now",
                  box: { x: 0, y: 0, width: 10, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
    }),
    frames: () => [],
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }),
  });

  await director.look({ text: "" }, ["find the price"]);

  assert.equal(sent[0][0].name, "Buy now");
});

// --- CAP-4: mid-run session expiry ---------------------------------------------

test("a session that stops reading as signed in ends the run as a diagnostic, not a finding", async () => {
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[signin] link Sign in", eyes: {}, scan: { pattern: "spotted", fixationBudget: 1 },
        counts: { elements: 1, legible: 1, fixated: 0, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [], notLookedAt: [] };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception, authenticatedSession: true,
    walk: async () => ({
      elements: [{ selector: "#signin", role: "link", name: "Sign in", box: { x: 0, y: 0, width: 40, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
    }),
    frames: () => [],
    actor: async () => { throw new Error("the run must end before the actor is ever asked"); },
  });
  const recorder = fakeRecorder();
  const verdict = await run(director, fakeBrowser(), recorder);

  assert.equal(verdict.status, "inconclusive");
  assert.deepEqual(verdict.blockers, [], "a run-harness condition is not a claim about the page");
  assert.ok(verdict.criteria.every((criterion) => criterion.result === "not-observed"),
    "neither criterion is a claim this run is positioned to make");
  const expired = recorder.events.find((event) => event.type === "journey.session_expired");
  assert.ok(expired, "the expiry is recorded so the report can tell a reader why nothing else was measured");
  assert.match(expired.data.reason, /Sign in/);
});

test("the same page with no authenticated session is read as ordinary, not an expiry", async () => {
  const perception = {
    available: true,
    async perceive() {
      return { observation: "[signin] link Sign in", eyes: {}, scan: { pattern: "spotted", fixationBudget: 1 },
        counts: { elements: 1, legible: 1, fixated: 0, notPerceived: 0, notLookedAt: 0 },
        notPerceived: [], perceived: [], notLookedAt: [] };
    },
  };
  const director = new PersonaDirector({
    profile: impatient, sleepFn: async () => {}, perception,
    walk: async () => ({
      elements: [{ selector: "#signin", role: "link", name: "Sign in", box: { x: 0, y: 0, width: 40, height: 10 } }],
      viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA",
    }),
    frames: () => [],
    actor: async () => ({ visible: "a sign-in link", expectation: "nothing",
      action: { type: "DONE", content: "looked around" } }),
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  assert.equal(recorder.events.find((event) => event.type === "journey.session_expired"), undefined,
    "a signed-out run seeing an ordinary sign-in link has no session to lose");
});

// --- CAP-2: hatExtras reaches the faculty, additive only -----------------------

test("hatExtras is appended to the browsing faculty, never in place of it", () => {
  const { registerFaculty, FACULTY_REGISTRY, Tool } = require("../src/faculty");
  class FakeTool extends Tool {
    constructor() { super({ name: "test-cap2-tool" }); }
    actionsDefinitionsPrompt() { return "- PING: does nothing"; }
    get actionTypes() { return ["PING"]; }
    async processAction() { return { handled: true, acted: false }; }
  }
  registerFaculty("test-cap2-extra", () => new FakeTool());
  try {
    const director = new PersonaDirector({ profile: impatient, sleepFn: async () => {},
      hatExtras: ["test-cap2-extra"],
      actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }) });

    assert.ok(director.faculty.actionTypes.includes("PING"), "the hat's extra capability is present");
    assert.ok(director.faculty.actionTypes.includes("CLICK"), "browsing is still there underneath it");
  } finally {
    FACULTY_REGISTRY.delete("test-cap2-extra");
  }
});

test("with no hatExtras, the faculty is unchanged from before CAP-2", () => {
  const director = new PersonaDirector({ profile: impatient, sleepFn: async () => {},
    actor: async () => ({ visible: "", expectation: "", action: { type: "DONE", content: "done" } }) });

  assert.ok(director.faculty.actionTypes.includes("CLICK"));
  assert.ok(!director.faculty.actionTypes.includes("PING"));
});

// --- JRN-2: loops recognised by label, not by ref -------------------------

test("the outcome event's repeat key is the label, and falls back to the ref exactly as before", () => {
  // A label, when the caller has one: this is the whole fix. "Pricing" clicked
  // under three different refs is now three occurrences of one key, where
  // before it was three keys used once each.
  const named = outcomeEvent({ type: "CLICK", target: "e367" }, { failed: false, changed: false }, "Pricing");
  assert.equal(named.repeatKey, "CLICK:Pricing");

  // No third argument -- every caller before this one -- is unchanged: the ref
  // is still the key.
  const unnamed = outcomeEvent({ type: "CLICK", target: "e367" }, { failed: false, changed: false });
  assert.equal(unnamed.repeatKey, "CLICK:e367");
});

/** A perception mock that resolves a fixed set of selectors to fixed names,
 * regardless of what was walked or captured -- enough for nameOf() to work,
 * which is all these tests need from it. */
function namingPerception(named) {
  const box = { x: 0, y: 0, width: 40, height: 10 };
  return { available: true, async perceive() {
    return { observation: "a page", eyes: {}, scan: {},
      counts: { elements: named.length, legible: named.length, fixated: named.length,
        notPerceived: 0, notLookedAt: 0 },
      notPerceived: [], notLookedAt: [],
      perceived: named.map(([selector, name]) => ({ selector, name, box })) };
  } };
}
function namingWalk(named) {
  const box = { x: 0, y: 0, width: 40, height: 10 };
  return async () => ({
    elements: named.map(([selector, name]) => ({ selector, role: "link", name, box })),
    viewport: { width: 1280, height: 900 }, screenshotBase64: "AAA", refs: {}, snapshot: "", scrollY: 0 });
}

test("the same control clicked under three different refs is one repeat, not three tries at different things", async () => {
  // The real defect this lane was built to close: a live run clicked "Pricing"
  // under e153, e27 and e367, and repeatedEventCounts -- keyed by ref before
  // this fix -- never saw a repeat at all.
  const named = [["e1", "Pricing"], ["e2", "Pricing"], ["e4", "Pricing"]];
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: namingPerception(named),
    frames: () => [], walk: namingWalk(named),
    actor: scriptedActor([
      { type: "CLICK", target: "e1" }, { type: "CLICK", target: "e2" }, { type: "CLICK", target: "e4" },
      { type: "DONE", content: "gave up" },
    ]),
  });
  const recorder = fakeRecorder();
  // A page that takes the click and does nothing -- like the real run this is
  // built against, where "Pricing" kept landing back on itself. Only matters
  // here so the outcome is "ambiguous_feedback" rather than "success", which
  // is what makes outcomeEvent's label-aware repeatKey the one that runs;
  // either way the loop is tracked by what was clicked, not by what happened.
  await run(director, fakeBrowser({ dead: true }), recorder);

  const loop = recorder.events.find((event) => event.type === "persona.loop");
  assert.ok(loop, "three tries at the same control, by label, is reported as a loop");
  assert.equal(loop.data.repeated, 3);
  assert.equal(loop.data.label, "Pricing");
  assert.equal(loop.data.action.target, "e4", "the ref of the click that completed the pattern");
  assert.equal(loop.data.alternating, undefined, "three tries at one thing is not two things alternating");

  // And the escalating-impact math already in reduceState(), which needs a
  // repeat to see one, now does: the label fix is not only the new explicit
  // event, it is the old counter finally counting correctly.
  const ended = recorder.events.find((event) => event.type === "agent.end");
  assert.equal(ended.data.finalState.repeatedEventCounts["CLICK:Pricing"], 3);
});

test("two controls alternated four times, by label and across refs, is told back to the persona as a loop", async () => {
  const named = [["e1", "Pricing"], ["e2", "Pricing"], ["e3", "Start free for 30 days"]];
  const seenHistory = [];
  let index = 0;
  const script = [
    { type: "CLICK", target: "e1" },   // Pricing
    { type: "CLICK", target: "e3" },   // Start free
    { type: "CLICK", target: "e2" },   // Pricing again, a different ref
    { type: "CLICK", target: "e3" },   // Start free -- A, B, A, B by label: the loop
    { type: "DONE", content: "gave up" },
  ];
  const actor = async (ask) => {
    seenHistory.push((ask.history || []).slice());
    const step = script[Math.min(index, script.length - 1)];
    index += 1;
    return { visible: "", expectation: "", action: { type: step.type, target: step.target || "",
      content: step.content || "" } };
  };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: namingPerception(named),
    frames: () => [], walk: namingWalk(named), actor,
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const loop = recorder.events.find((event) => event.type === "persona.loop");
  assert.ok(loop, "an A/B alternation across refs is reported as a loop");
  assert.deepEqual(loop.data.alternating, { a: "Pricing", b: "Start free for 30 days" });
  assert.equal(loop.summary,
    'You keep going back and forth between "Pricing" and "Start free for 30 days" without getting anywhere.');

  // Told back to them: the very next decision -- the DONE that ends this run --
  // was asked for with this in its own history, not only recorded for a report
  // nobody in the run itself ever reads.
  assert.ok(seenHistory.at(-1).some((line) => line.includes("going back and forth")),
    "the next actor call is shown the loop, not only the recorder");
});

// --- JRN-3: the gate blocks what it rejects, and tells the judge what it's looking at --------

/** A judge that passes anything naming "Pricing" and rejects everything else --
 * exactly the shape needed to let one action through and exhaust another. */
function passesOnlyPricing() {
  return async ({ user }) => (user.includes('"Pricing"')
    ? '{"score": 9, "flaw": ""}' : '{"score": 2, "flaw": "not them"}');
}

test("a rejected action is never performed once the gate exhausts its attempts, and the persona is told so", async () => {
  // Before this fix, `settled.decision` -- the last, still-rejected attempt --
  // was performed unconditionally. A live run confirmed it live: two of three
  // actions scored 3 and 4 out of 10 were carried out anyway, by their own
  // pointer events.
  const named = [["e1", "Pricing"], ["e2", "Contact"]];
  const seenHistory = [];
  let freshCalls = 0;
  const script = [{ type: "CLICK", target: "e1" }, { type: "CLICK", target: "e2" }, { type: "DONE", content: "done" }];
  const actor = async (ask, opts = {}) => {
    seenHistory.push((ask.history || []).slice());
    if (!opts.notLikeYou) freshCalls += 1;
    const step = script[Math.min(freshCalls - 1, script.length - 1)];
    return { visible: "", expectation: "", action: { type: step.type, target: step.target || "",
      content: step.content || "" } };
  };
  actor.judgeAdherence = passesOnlyPricing();
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: namingPerception(named),
    frames: () => [], walk: namingWalk(named), actor,
  });
  const recorder = fakeRecorder();
  const browser = fakeBrowser();
  const verdict = await run(director, browser, recorder);

  assert.equal(verdict.status, "passed", "the run still reaches DONE afterward, not trapped");
  assert.ok(!browser.calls.some((call) => call[0] === "click" && call[1] === "e2"),
    "the rejected click on Contact never reaches the browser");
  assert.ok(!recorder.events.some((event) => event.type === "persona.pointer" && event.data.target === "e2"),
    "no hand was ever aimed at the rejected control either");

  const rejected = recorder.events.find((event) => event.type === "persona.adherence" && event.data.passed === false);
  assert.ok(rejected, "the rejection itself is still on the record");
  assert.equal(rejected.data.targetLabel, "Contact");
  assert.deepEqual(rejected.data.targetBox, { x: 0, y: 0, width: 40, height: 10 });

  // And the persona is told, not only the recorder -- read on the very next
  // actor call, the same channel JRN-2's loop notices use.
  assert.ok(seenHistory.some((entry) => entry.some((line) => line.includes("did not sound like you"))),
    "a later actor call is shown that the last proposal did not go ahead");
});

test("the judge is told what the control says on it, and a passed action is judged normally", async () => {
  // judgeAdherence has to be on the actor *before* the director is
  // constructed: the constructor reads it once, there and then, to decide
  // whether to build a real gate at all (`this.gate = gate || new
  // AdherenceGate({ judge: actor.judgeAdherence })`) -- setting it afterward
  // leaves that gate permanently disabled, which every test below is careful
  // not to do.
  const named = [["e1", "Pricing"]];
  const actor = scriptedActor([{ type: "CLICK", target: "e1" }, { type: "DONE", content: "done" }]);
  actor.judgeAdherence = async ({ user }) => {
    assert.match(user, /the "Pricing"/);
    assert.doesNotMatch(user, /\be1\b/, "the ref itself is never shown to the judge once a label resolves");
    return '{"score": 9, "flaw": ""}';
  };
  const director = new PersonaDirector({
    profile: dogged, sleepFn: async () => {}, perception: namingPerception(named),
    frames: () => [], walk: namingWalk(named), actor,
  });
  const recorder = fakeRecorder();
  await run(director, fakeBrowser(), recorder);

  const passed = recorder.events.find((event) => event.type === "persona.adherence");
  assert.ok(passed, "the judge was actually reached");
  assert.equal(passed.data.passed, true);
  assert.equal(passed.data.targetLabel, "Pricing");
});

test("DONE and GIVE_UP never reach the gate, so a harsh judge cannot trap a persona who has already decided to leave", async () => {
  let judged = 0;
  // A judge that rejects literally everything -- proof this is never asked,
  // not merely one that happens to pass DONE.
  const doneActor = scriptedActor([{ type: "DONE", content: "found the price" }]);
  doneActor.judgeAdherence = async () => { judged += 1; return '{"score": 0, "flaw": "not them at all"}'; };
  const director = new PersonaDirector({ profile: dogged, sleepFn: async () => {}, actor: doneActor });
  const recorder = fakeRecorder();
  const verdict = await run(director, fakeBrowser(), recorder);

  assert.equal(judged, 0, "ending the journey is never sent to the gate");
  assert.equal(verdict.status, "passed");
  assert.equal(recorder.events.some((event) => event.type === "persona.adherence"), false);

  // Same for giving up: not just the happy path.
  const giveUpActor = scriptedActor([{ type: "GIVE_UP", content: "not worth it" }]);
  giveUpActor.judgeAdherence = async () => '{"score": 0, "flaw": "not them at all"}';
  const givingUp = new PersonaDirector({ profile: dogged, sleepFn: async () => {}, actor: giveUpActor });
  const secondVerdict = await run(givingUp, fakeBrowser(), fakeRecorder());
  assert.equal(secondVerdict.status, "failed");
  assert.equal(secondVerdict.summary.includes("Gave up"), true);
});

test("a coping type sampled from this person's own current state, not the rejected click, is what happens next", async () => {
  // Deterministic, not a probability check, the same way JRN-1's own seed-8
  // test is: seed 5 on this profile, after one real failing click builds
  // real confusion and a consecutive failure, samples "backtrack" the moment
  // a second action is rejected outright -- found empirically, the same way
  // every seed-pinned test in this session was, by running the real sampler
  // against the real state it will actually see.
  const named = [["e1", "Pricing"], ["e2", "Contact"]];
  const behavior = { seed: 5, patience: .3, persistence: .3, irritability: .6, angerReactivity: .5,
    angerRecovery: .3, impulsivity: .3, repeatFailureTolerance: .9, selfEfficacy: .3,
    verificationTendency: .2, exploration: .1, helpSeeking: .1 };
  const profile = { id: "p_backtrack", persona: {}, behavior, abilities: {} };
  const script = [{ type: "CLICK", target: "e1" }, { type: "CLICK", target: "e2" }, { type: "DONE", content: "done" }];
  let freshCalls = 0;
  const actor = async (ask, opts = {}) => {
    if (!opts.notLikeYou) freshCalls += 1;
    const step = script[Math.min(freshCalls - 1, script.length - 1)];
    return { visible: "", expectation: "", action: { type: step.type, target: step.target || "",
      content: step.content || "" } };
  };
  actor.judgeAdherence = passesOnlyPricing();
  const director = new PersonaDirector({
    profile, sleepFn: async () => {}, perception: namingPerception(named),
    frames: () => [], walk: namingWalk(named), actor,
  });
  const browser = fakeBrowser({ clickThrows: true });
  const verdict = await run(director, browser, fakeRecorder());

  // Not an exact call list -- fakeBrowser's own snapshot/screenshot/
  // scrollIntoView calls surround these -- only what this fix actually
  // controls: Contact is never clicked, and the press this person's own
  // sampled coping produced is.
  assert.ok(browser.calls.some((call) => call[0] === "click" && call[1] === "e1"), "the passed click still happens");
  assert.ok(!browser.calls.some((call) => call[0] === "click" && call[1] === "e2"),
    "the rejected click on Contact is replaced by this person's own sampled coping, not performed");
  assert.ok(browser.calls.some((call) => call[0] === "press" && call[1] === "Alt+ArrowLeft"),
    "sampled here from real state: this profile, this seed, one real failure in");
  assert.equal(verdict.status, "passed", "and the run still reaches its DONE afterward");
});
