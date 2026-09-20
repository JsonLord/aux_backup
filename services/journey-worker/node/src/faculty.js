"use strict";
/**
 * Tools that declare their own actions, the way a TinyTroupe agent's do.
 *
 * TinyTroupe gives an agent capabilities as `TinyTool`s, and each tool answers
 * three questions about itself: what actions it offers
 * (`actions_definitions_prompt`), what rules govern them
 * (`actions_constraints_prompt`), and whether it can carry out a given action
 * (`process_action`, true if it handled it). A `TinyToolUse` faculty holds
 * several and concatenates their prompts, so the agent's instructions are
 * assembled from its actual capabilities rather than written out by hand.
 *
 * We had the same two halves in two places that could not check each other. A
 * hardcoded ACTION_VOCABULARY string told the persona what it could do, and a
 * switch in the director decided what actually happened -- so a vocabulary entry
 * with no implementation, or an implementation the prompt never mentioned, were
 * both possible and neither would fail loudly. Here the prompt is generated from
 * the tools that implement it, and an action nothing claims is reported as
 * unhandled instead of quietly doing nothing.
 *
 * The shape is TinyTroupe's, deliberately: an action is `{type, target,
 * content}`, `processAction` returns whether it was handled, and a tool that
 * touches the world outside the simulation says so. A journey does touch it --
 * these clicks land on somebody's live site.
 */

const { travelTo } = require("./cursorKeeper");
const { simulatePointer } = require("./physical");
const { sendViewportInput } = require("./viewportStream");

/** How a tool answers for itself. Mirrors TinyTroupe's TinyTool. */
class Tool {
  constructor({ name, description, realWorldSideEffects = false } = {}) {
    this.name = name;
    this.description = description;
    this.realWorldSideEffects = realWorldSideEffects;
  }

  /** The actions this tool offers, as the persona should be told about them. */
  actionsDefinitionsPrompt() {
    throw new Error(`${this.name} must define its actions`);
  }

  /** The rules about using them. Empty is a legitimate answer. */
  actionsConstraintsPrompt() {
    return "";
  }

  /** The action types this tool claims, so the faculty can route without trying. */
  get actionTypes() {
    return [];
  }

  // eslint-disable-next-line no-unused-vars
  async processAction(action, context) {
    throw new Error(`${this.name} must implement processAction`);
  }
}

/**
 * The browser, as a capability the persona has rather than a thing the director
 * does to them.
 *
 * CLICK goes through the pointer simulation: a person with imprecise pointing
 * does not land dead centre, and on a small target they miss. The driver takes a
 * selector rather than a coordinate, so the scatter is recorded as what it is --
 * where this person's hand actually went -- and a miss outside the element's own
 * box is a failed action rather than something silently corrected.
 */
class BrowserTool extends Tool {
  constructor({ abilities = {}, seed = 1 } = {}) {
    super({ name: "Web browser", description: "Looking at and using a web page",
      // These clicks land on somebody's live site. TinyTroupe asks a tool to
      // declare this and it is not decoration here.
      realWorldSideEffects: true });
    this.abilities = abilities;
    this.seed = seed;
  }

  get actionTypes() {
    return ["READ", "CLICK", "SCROLL", "TYPE", "GO_BACK"];
  }

  actionsDefinitionsPrompt() {
    return [
      "- READ: look at something without touching it. target: what you are reading.",
      '- CLICK: click a control. target: its ref from the page list, e.g. "e12".',
      '- SCROLL: move the page. content: "down" or "up". target: optional pixel amount.',
      "- TYPE: type into a field. target: its ref. content: what you type.",
      "- GO_BACK: go back to the previous page.",
    ].join("\n");
  }

  actionsConstraintsPrompt() {
    return [
      "- You can only CLICK or TYPE into something you can actually see in the list above.",
      "  Anything not in that list is not on the screen as far as you are concerned.",
      "- READ changes nothing on the page. If you have just read something, do something with it.",
    ].join("\n");
  }

  async processAction(action, { browser, recorder, boxes }) {
    const context = { boxes };
    if (!this.actionTypes.includes(action.type)) return { handled: false };
    const result = { handled: true, failed: false, acted: false, url: "", error: "" };
    const target = String(action.target || "").trim();
    try {
      switch (action.type) {
        case "READ":
          result.acted = false;      // looking changes nothing, so nothing is re-observed
          break;
        case "CLICK": {
          if (!target) { result.failed = true; result.error = "no target"; break; }
          // Into view first, then read the box. The other order reads
          // coordinates for an element that is still below the fold, so the
          // recorded aim is nowhere near where the click actually lands. It does
          // not change whether the click misses -- the scatter is measured
          // against the element's own width and height -- only whether the
          // recorded position means anything.
          await browser.scrollIntoView(target).catch(() => {});
          const aim = await this.aim(target, browser, recorder, context?.boxes);
          if (aim?.missed) {
            // The hand went outside the control. Nothing happens, which is
            // exactly what happens to a person who misses.
            result.failed = true;
            result.error = "the click landed outside the control";
            break;
          }
          await browser.click(target);
          result.acted = true;
          break;
        }
        case "TYPE":
          if (!target) { result.failed = true; result.error = "no target"; break; }
          await browser.fill(target, String(action.content ?? ""));
          result.acted = true;
          break;
        case "SCROLL": {
          const direction = /up/i.test(String(action.content || "")) ? "up" : "down";
          const amount = Number.parseInt(String(action.target || ""), 10);
          await browser.scroll({ direction, amount: Number.isFinite(amount) && amount ? amount : 800 });
          result.acted = true;
          break;
        }
        case "GO_BACK":
          await browser.press("Alt+ArrowLeft");
          result.acted = true;
          break;
        default:
          return { handled: false };
      }
    } catch (error) {
      result.failed = true;
      // The reach happened even though it came to nothing, so the page is
      // re-observed: a click that throws may still have navigated.
      result.acted = true;
      result.error = String(error?.message || error);
    }
    result.url = await browser.getUrl().catch(() => "");
    return result;
  }

  /** Where this person's hand actually went, and whether it landed. */
  async aim(target, browser, recorder, boxes) {
    // The walk's own measurement first. The driver has no getElementBox: the call
    // threw on every click of every run, the catch swallowed it, and aim()
    // returned null before it recorded anything -- so the hand, the scatter and
    // the miss were all modelled and none of them ever ran. 62 clicks in one
    // live run, 62 silent nulls, no pointer event in the record at all.
    let box = boxes?.[target];
    if (!box || !box.width || !box.height) {
      try {
        box = (await browser.getElementBox(target))?.details;
      } catch {
        box = null;
      }
    }
    if (!box || !box.width || !box.height) {
      // Said out loud. A hand that could not be aimed is a measurement this run
      // did not make, and it has to be distinguishable from a hand that landed.
      await recorder?.record("persona.pointer", "could not tell where the control is",
        { target, measured: false });
      return null;
    }
    const aim = simulatePointer(box, this.abilities, this.seed);
    const missed = aim.x < box.x || aim.x > box.x + box.width
      || aim.y < box.y || aim.y > box.y + box.height;
    // Get there by moving, not by appearing. A pointer that jumps from one
    // control to the next crosses nothing on the way, so a menu that opens on
    // hover never opens and a tooltip never shows -- and a review of a page
    // whose navigation works that way would report navigation that does not
    // work. The travel happens whether or not the aim is going to land: a hand
    // that misses still moved.
    const travelled = await travelTo(aim, { send: this.sendInput || sendViewportInput })
      .catch(() => null);
    await recorder?.record("persona.pointer",
      missed ? "the click landed outside the control" : "clicked",
      { target, box, aim, missed,
        // How it got there, so a reader can tell a run whose hover states fired
        // from one whose did not.
        travel: travelled || undefined });
    return { ...aim, missed };
  }
}

/**
 * Stopping, which is an action like any other and the most important one.
 *
 * A synthetic user who would have left and did not is not a synthetic user, it
 * is a script -- so leaving has to be something the persona can choose, with the
 * same standing as clicking.
 */
class JourneyTool extends Tool {
  constructor() {
    super({ name: "Deciding you are finished", description: "Ending the visit" });
  }

  get actionTypes() {
    return ["DONE", "GIVE_UP"];
  }

  actionsDefinitionsPrompt() {
    return [
      "- GIVE_UP: stop, because this is not worth any more of your time. content: why.",
      "- DONE: stop, because you have what you came for. content: what you concluded.",
    ].join("\n");
  }

  actionsConstraintsPrompt() {
    return "- Only say DONE if you actually found what you came for. Not finding it is GIVE_UP.";
  }

  async processAction(action) {
    if (!this.actionTypes.includes(action.type)) return { handled: false };
    // Ending is the director's to carry out; the tool's job is to claim the
    // action so nothing else tries to run it as a browser command.
    return { handled: true, ends: action.type, acted: false, failed: false, url: "", error: "" };
  }
}

/**
 * Everything the persona can do, as one thing to ask.
 *
 * TinyTroupe's TinyToolUse: hold the tools, concatenate what they say about
 * themselves, and offer each of them an action until one takes it.
 */
class Faculty {
  constructor(tools = []) {
    this.name = "Tool Use";
    this.tools = tools;
  }

  /** The action vocabulary, assembled from the tools that implement it. */
  actionsDefinitionsPrompt() {
    return this.tools.map((tool) => tool.actionsDefinitionsPrompt()).filter(Boolean).join("\n");
  }

  actionsConstraintsPrompt() {
    return this.tools.map((tool) => tool.actionsConstraintsPrompt()).filter(Boolean).join("\n");
  }

  /** Every action type anything here can carry out. */
  get actionTypes() {
    return this.tools.flatMap((tool) => tool.actionTypes);
  }

  /** True if any tool here touches the world outside the simulation. */
  get realWorldSideEffects() {
    return this.tools.some((tool) => tool.realWorldSideEffects);
  }

  async processAction(action, context) {
    for (const tool of this.tools) {
      const outcome = await tool.processAction(action, context);
      if (outcome?.handled) return outcome;
    }
    // Nothing claimed it. Said out loud rather than treated as a no-op, because
    // an action the persona believes it took and that never happened is the
    // hardest kind of wrong to see afterwards.
    return { handled: false, failed: true, acted: false, url: "",
      error: `nothing here can do "${action.type}"` };
  }
}

/**
 * The faculty a journey runs with.
 *
 * `memory` is a PersonaMemoryBank when the run has one. It carries out no
 * actions -- it steers them, by answering the constraints question with what
 * this person has already learned about themselves. Passing it here rather than
 * threading it through the prompt separately is the point: TinyTroupe makes
 * memory a mental faculty for exactly this reason.
 */
function browsingFaculty({ abilities, seed, memory } = {}) {
  const tools = [new BrowserTool({ abilities, seed }), new JourneyTool()];
  if (memory) tools.push(memory);
  return new Faculty(tools);
}

/**
 * CAP-2: where a hat's extra capabilities come from, by name -- "developer",
 * eventually a docs search, whatever a later hat adds. Empty today: nothing
 * has registered a second faculty yet (CAP-5's developer mode is what would
 * be the first). A name with nothing registered for it is refused rather than
 * silently producing a hat with fewer capabilities than it claims -- see
 * facultyWith.
 */
const FACULTY_REGISTRY = new Map();

/** Register a named extra faculty's tool factory, so facultyWith can add it by
 * name. `factory` receives the same options facultyWith itself was called
 * with (abilities, seed, memory, plus whatever a hat's own `grants` supply)
 * and returns a Tool. Re-registering a name replaces it -- last one wins,
 * which is only ever exercised by tests reaching into the same registry a
 * real deployment would use once. */
function registerFaculty(name, factory) {
  FACULTY_REGISTRY.set(name, factory);
}

/**
 * CAP-2: the hat registry's other half. `browsingFaculty()` does not change
 * and is not renamed -- it is the floor every hat stands on, not one option
 * among several, and this function's whole job is to make that structural
 * rather than a convention someone could forget. It always calls
 * browsingFaculty() first and only ever appends: there is no parameter here
 * that removes a tool, because a hat's own record (`adds`, never
 * `removes`/`replaces`) has no field to express one with. `Faculty.
 * processAction()` offers an action to each tool in order until one claims
 * it, so appending -- never prepending, never reordering -- means
 * BrowserTool and JourneyTool keep first claim on every action they already
 * handle; nothing appended here can shadow browsing even by accident.
 *
 * `extras` is a list of names from the registry above, resolved and appended
 * in order. A name nothing has registered throws rather than being skipped:
 * a hat that claims a capability and silently does not have it is a worse
 * failure than a job that never starts, because the gap would not show up
 * until a persona tried to use it and found no tool would.
 *
 * With no extras, this returns exactly what browsingFaculty() would have --
 * "a hat with no extras is byte-for-byte today's faculty" is provable by
 * construction, not merely intended, because this is the only code path that
 * builds either.
 */
function facultyWith(extras = [], options = {}) {
  const faculty = browsingFaculty(options);
  for (const name of extras) {
    const factory = FACULTY_REGISTRY.get(name);
    if (!factory) {
      throw new Error(`no faculty registered for "${name}" -- a hat cannot claim a capability nothing implements`);
    }
    // CAP-5's own rail: "off unless the run asks, or facultyForHat does not
    // mount the tool at all". A factory that finds nothing to configure it
    // with (no allowCommands, say) returns a falsy value here rather than a
    // Tool that exists only to refuse everything -- mounted-then-guarded is
    // one bug from ungated, and this is how a factory stays not-mounted
    // instead.
    const tool = factory(options);
    if (tool) faculty.tools.push(tool);
  }
  return faculty;
}

module.exports = { BrowserTool, Faculty, JourneyTool, Tool, browsingFaculty,
  facultyWith, registerFaculty, FACULTY_REGISTRY };
