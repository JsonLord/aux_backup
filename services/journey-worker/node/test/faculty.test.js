"use strict";
/**
 * The point of moving to tools that declare their own actions is that the two
 * halves can no longer drift: what the persona is told it can do, and what
 * actually happens when it does. So that is what these pin.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const { BrowserTool, Faculty, JourneyTool, Tool, browsingFaculty,
  facultyWith, registerFaculty, FACULTY_REGISTRY } = require("../src/faculty");
const { ACTION_TYPES, ACTION_VOCABULARY } = require("../src/personaActor");

function fakeBrowser({ box, clickThrows = false } = {}) {
  const calls = [];
  return {
    calls,
    async scrollIntoView(target) { calls.push(["scrollIntoView", target]); },
    async click(target) { calls.push(["click", target]); if (clickThrows) throw new Error("element not found"); },
    async fill(target, value) { calls.push(["fill", target, value]); },
    async scroll(options) { calls.push(["scroll", options.direction, options.amount]); },
    async press(key) { calls.push(["press", key]); },
    async getElementBox(target) { calls.push(["getElementBox", target]); return { details: box }; },
    async getUrl() { return "https://example.test/"; },
  };
}

const context = (browser) => ({ browser, recorder: { async record() {} } });

test("every action the persona is offered is one some tool can carry out", async () => {
  // The failure this replaces: a vocabulary line with no implementation, or an
  // implementation the prompt never mentioned, and neither failing loudly.
  const faculty = browsingFaculty();
  const offered = ACTION_VOCABULARY.split("\n")
    .map((line) => (line.match(/^-\s*([A-Z_]+):/) || [])[1]).filter(Boolean);

  assert.ok(offered.length >= 7);
  assert.deepEqual(new Set(offered), new Set(faculty.actionTypes));
  assert.deepEqual(new Set(offered), new Set(ACTION_TYPES));
});

test("an action nothing claims is reported, not silently ignored", async () => {
  // An action the persona believes it took and that never happened is the
  // hardest kind of wrong to see afterwards.
  const outcome = await browsingFaculty().processAction({ type: "TELEPORT" }, context(fakeBrowser()));
  assert.equal(outcome.handled, false);
  assert.equal(outcome.failed, true);
  assert.match(outcome.error, /TELEPORT/);
});

test("a click is aimed by the hand that is doing it, and can miss", async () => {
  const precise = new BrowserTool({ abilities: { motor: { pointerPrecision: 1 } }, seed: 3 });
  const browser = fakeBrowser({ box: { x: 100, y: 100, width: 16, height: 16 } });
  const landed = await precise.processAction({ type: "CLICK", target: "e1" }, context(browser));
  assert.equal(landed.failed, false);
  assert.ok(browser.calls.some((call) => call[0] === "click"));

  // A small target and an unsteady hand: the click goes outside the control, and
  // is reported as a failure rather than quietly corrected onto it. Correcting
  // it is what makes a 16px target look usable to a simulation and unusable to
  // a person.
  const unsteady = new BrowserTool({ abilities: { motor: { pointerPrecision: 0.1 } }, seed: 3 });
  const second = fakeBrowser({ box: { x: 100, y: 100, width: 16, height: 16 } });
  const missed = await unsteady.processAction({ type: "CLICK", target: "e1" }, context(second));
  assert.equal(missed.failed, true);
  assert.match(missed.error, /outside the control/);
  assert.ok(!second.calls.some((call) => call[0] === "click"), "a miss does not click anything");
});

test("the element is brought into view before its position is read", async () => {
  // The other order reads coordinates for something still below the fold, so the
  // recorded aim is nowhere near where the click lands.
  const browser = fakeBrowser({ box: { x: 10, y: 10, width: 200, height: 60 } });
  await new BrowserTool().processAction({ type: "CLICK", target: "e5" }, context(browser));
  const kinds = browser.calls.map((call) => call[0]);
  assert.ok(kinds.indexOf("scrollIntoView") < kinds.indexOf("getElementBox"));
});

test("a click that throws still counts as having happened", async () => {
  // The reach happened even though it came to nothing, and it may have navigated
  // anyway -- so the page has to be looked at again.
  const browser = fakeBrowser({ box: { x: 0, y: 0, width: 200, height: 60 }, clickThrows: true });
  const outcome = await new BrowserTool().processAction({ type: "CLICK", target: "e1" }, context(browser));
  assert.equal(outcome.failed, true);
  assert.equal(outcome.acted, true);
});

test("reading changes nothing, so nothing is re-observed", async () => {
  const browser = fakeBrowser();
  const outcome = await new BrowserTool().processAction({ type: "READ", target: "the headline" }, context(browser));
  assert.equal(outcome.acted, false);
  assert.equal(outcome.failed, false);
  assert.deepEqual(browser.calls, []);
});

test("scrolling and going back reach the driver the way they always did", async () => {
  const browser = fakeBrowser();
  await new BrowserTool().processAction({ type: "SCROLL", content: "down" }, context(browser));
  await new BrowserTool().processAction({ type: "SCROLL", content: "up", target: "300" }, context(browser));
  await new BrowserTool().processAction({ type: "GO_BACK" }, context(browser));
  assert.deepEqual(browser.calls, [
    ["scroll", "down", 800], ["scroll", "up", 300], ["press", "Alt+ArrowLeft"]]);
});

test("clicking nothing is a failure rather than a click on the empty string", async () => {
  const browser = fakeBrowser();
  const outcome = await new BrowserTool().processAction({ type: "CLICK", target: "" }, context(browser));
  assert.equal(outcome.failed, true);
  assert.deepEqual(browser.calls, []);
});

test("stopping is claimed by a tool, so nothing tries to run it as a browser command", async () => {
  const browser = fakeBrowser();
  const outcome = await browsingFaculty().processAction(
    { type: "GIVE_UP", content: "no prices anywhere" }, context(browser));
  assert.equal(outcome.handled, true);
  assert.equal(outcome.ends, "GIVE_UP");
  assert.deepEqual(browser.calls, [], "giving up does not touch the page");
});

test("a journey says out loud that it touches somebody's real website", () => {
  // TinyTroupe asks a tool to declare real-world side effects. It is not
  // decoration here: these clicks land on a live site.
  assert.equal(browsingFaculty().realWorldSideEffects, true);
  assert.equal(new Faculty([new JourneyTool()]).realWorldSideEffects, false);
});

test("the constraints reach the persona alongside the actions", () => {
  const faculty = browsingFaculty();
  assert.match(faculty.actionsConstraintsPrompt(), /only CLICK or TYPE into something you can actually see/);
  assert.match(faculty.actionsConstraintsPrompt(), /Not finding it is GIVE_UP/);
});

test("the hand is aimed from the measurement the walk already made", async () => {
  // The driver has no getElementBox. The call threw on every click of every run,
  // the catch swallowed it, and aim() returned null before recording anything --
  // so the hand, the scatter and the miss were all modelled and none of them ever
  // ran: 62 clicks in one live run, 62 silent nulls, no pointer in the record.
  // The walk measures every element on screen anyway.
  const recorder = { events: [], async record(type, summary, data) {
    this.events.push({ type, summary, data }); } };
  const faculty = browsingFaculty({ abilities: {}, seed: 1 });
  // Exactly as the real driver behaves: getElementBox is not there at all.
  const browser = { scrollIntoView: async () => {}, click: async () => {},
    getUrl: async () => "https://example.test/" };

  const result = await faculty.processAction({ type: "CLICK", target: "e7" }, {
    browser, recorder, boxes: { e7: { x: 100, y: 200, width: 120, height: 40 } } });

  assert.equal(result.acted, true, "a click with a box behind it goes through");
  const pointer = recorder.events.find((event) => event.type === "persona.pointer");
  assert.ok(pointer, "and the hand is on the record");
  assert.deepEqual(pointer.data.box, { x: 100, y: 200, width: 120, height: 40 });
  assert.ok(pointer.data.aim, "with where it actually landed");
});

test("a hand that could not be aimed says so instead of returning nothing", async () => {
  const recorder = { events: [], async record(type, summary, data) {
    this.events.push({ type, summary, data }); } };
  const faculty = browsingFaculty({ abilities: {}, seed: 1 });
  const browser = { scrollIntoView: async () => {}, click: async () => {},
    getUrl: async () => "https://example.test/" };

  await faculty.processAction({ type: "CLICK", target: "e7" }, { browser, recorder, boxes: {} });

  const pointer = recorder.events.find((event) => event.type === "persona.pointer");
  assert.ok(pointer, "a measurement this run did not make is still a thing to record");
  assert.equal(pointer.data.measured, false);
});

// --- CAP-2: the hat registry is additive only -----------------------------------

test("facultyWith no extras is exactly what browsingFaculty would have built", () => {
  const faculty = facultyWith([], { abilities: {}, seed: 1 });

  assert.equal(faculty.tools.length, 2, "BrowserTool and JourneyTool, nothing else");
  assert.deepEqual(faculty.actionTypes, browsingFaculty({ abilities: {}, seed: 1 }).actionTypes);
  assert.ok(faculty.tools[0] instanceof BrowserTool, "browsing keeps first claim");
  assert.ok(faculty.tools[1] instanceof JourneyTool);
});

test("a name nothing registered is refused, not silently skipped", () => {
  assert.throws(() => facultyWith(["nonexistent-hat"], { abilities: {} }), /no faculty registered/);
});

test("an extra faculty is appended, never prepended or replacing browsing", () => {
  class FakeDeveloperTool extends Tool {
    constructor() { super({ name: "developer", realWorldSideEffects: true }); }
    actionsDefinitionsPrompt() { return "- FETCH: download a file"; }
    get actionTypes() { return ["FETCH"]; }
    async processAction() { return { handled: true, acted: true }; }
  }
  registerFaculty("test-developer", () => new FakeDeveloperTool());

  const faculty = facultyWith(["test-developer"], { abilities: {}, seed: 1 });

  assert.equal(faculty.tools.length, 3);
  assert.ok(faculty.tools[0] instanceof BrowserTool, "browsing still claims the first slot");
  assert.ok(faculty.tools[1] instanceof JourneyTool);
  assert.ok(faculty.tools[2] instanceof FakeDeveloperTool, "the extra is appended last");
  assert.ok(faculty.actionTypes.includes("FETCH"));
  assert.ok(faculty.actionTypes.includes("CLICK"), "browsing's own actions are still all present");

  FACULTY_REGISTRY.delete("test-developer");
});

test("an appended tool cannot shadow a browsing action even if it tries to claim one", async () => {
  class ClaimsEverythingTool extends Tool {
    constructor() { super({ name: "greedy" }); }
    actionsDefinitionsPrompt() { return ""; }
    get actionTypes() { return ["CLICK"]; }
    async processAction() { return { handled: true, acted: true, url: "greedy-tool-handled-it" }; }
  }
  registerFaculty("test-greedy", () => new ClaimsEverythingTool());
  const faculty = facultyWith(["test-greedy"], { abilities: {}, seed: 1 });
  const browser = { scrollIntoView: async () => {}, click: async () => {},
    getUrl: async () => "https://real-browser-handled-it.test/" };

  const result = await faculty.processAction({ type: "CLICK", target: "e1" },
    { browser, recorder: { async record() {} }, boxes: {} });

  assert.equal(result.url, "https://real-browser-handled-it.test/",
    "BrowserTool answered first, so the appended tool never even saw a CLICK");

  FACULTY_REGISTRY.delete("test-greedy");
});
