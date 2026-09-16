"use strict";
/**
 * The point of moving to tools that declare their own actions is that the two
 * halves can no longer drift: what the persona is told it can do, and what
 * actually happens when it does. So that is what these pin.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const { BrowserTool, Faculty, JourneyTool, browsingFaculty } = require("../src/faculty");
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
