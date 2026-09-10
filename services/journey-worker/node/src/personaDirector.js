"use strict";
/**
 * A director that runs the journey as a person rather than as an agent.
 *
 * journeytest-core takes any `AgentDirector` -- `{name, model?, run(context)}` --
 * so this replaces the Pi director without forking anything, and keeps the
 * browser driver, the event recorder, the artifact directories, the video and the
 * UI-change recording exactly as they are.
 *
 * What it adds is the persona. Two pieces of this repository already model one
 * and neither was ever reachable on a live run: behavior.js keeps frustration,
 * anger, confusion, trust and fatigue and samples a coping strategy from the
 * persona's own traits, and physical.js turns abilities into pointer scatter,
 * working-memory limits and reading time. Both sat below the early `return` in
 * index.js. Here they decide what happens.
 *
 * The consequence that matters is that coping is control flow, not description.
 * When the model says `abandon`, the run stops and the verdict says the persona
 * gave up -- because a synthetic user who would have left and did not is not a
 * synthetic user, it is a script. Where the old director produced an
 * "inconclusive" fallback because nothing called journey_finish, this produces a
 * verdict either way: someone either got what they came for or they did not.
 *
 * Everything the persona thinks and feels goes through `context.recorder`, which
 * already writes events.ndjson and run.json. The experience record therefore
 * ships as a normal run artifact, which is what a later UX-reasoning layer reads
 * alongside the screenshots and the DOM.
 */

const { createHash } = require("node:crypto");
const path = require("node:path");

const { BehaviorController } = require("./behavior");
const { PerceptionClient, lookAtPage, motionFramesFrom } = require("./perception");
const { MATCH_OUTCOMES, affectInWords } = require("./personaActor");
const { filterWorkingMemory, readingDurationMs, simulatePointer } = require("./physical");
const { recentFrames } = require("./viewportStream");

const DEFAULT_MAX_STEPS = 40;

/**
 * How much of the persona's simulated time is actually spent waiting.
 *
 * A slow reader takes a long time over a wordy page, and that has to bear on
 * their patience -- but paying it in real seconds makes a run unusable. Measured
 * on a live run: 83 seconds of real sleep per turn at 260 words per minute, and
 * 180 at 120, which is two hours for a forty-step journey spent doing nothing.
 *
 * So simulated time is *accounted* rather than *slept*: the full duration goes
 * into the behaviour model, where it drives fatigue, elapsed time and wait
 * tolerance exactly as before, while the wall clock advances by this fraction of
 * it. Set AUX_PERSONA_TIME_SCALE to 1 to watch a run in real time.
 */
function timeScale(env = process.env) {
  const configured = Number.parseFloat(String(env.AUX_PERSONA_TIME_SCALE || ""));
  return Number.isFinite(configured) && configured >= 0 ? Math.min(configured, 1) : 0;
}

// Even with time accounted rather than slept, a run should not spin: this is the
// floor between actions, and it is also what keeps a live viewer's frames moving.
const MIN_STEP_MS = 120;
// However slow the reader, no single page is worth this much of the wall clock.
const MAX_REAL_WAIT_MS = 8000;

/**
 * The most time a person spends taking in a page before doing something.
 *
 * readingDurationMs() answers "how long to read this text", which is right for
 * text somebody reads. It is wrong for a page somebody is deciding about: nobody
 * reads a landing page end to end before clicking, they skim. Charged in full it
 * came to 83 seconds per view, which drove fatigue up by 0.138 a turn and had
 * every persona worn out after eight pages regardless of what the page did.
 *
 * Capping it is an approximation of skimming and is meant to be replaced: once a
 * scan path exists, the charge becomes the fixations actually made rather than a
 * guess bounded by a constant.
 */
const MAX_SCAN_MS = 20000;

const sleep = (ms) => new Promise((resolve) => {
  const timer = setTimeout(resolve, Math.max(0, ms));
  if (typeof timer.unref === "function") timer.unref();
});

/**
 * How badly an action went, in the terms behavior.js reduces over.
 *
 * A driver call that throws is an outright failure. One that returns but changes
 * nothing is worse than it looks: "I clicked and the page ignored me" is the
 * shape of most real frustration, and it is invisible if only exceptions count.
 */
function outcomeEvent(action, { failed, changed, error, matched }) {
  const repeatKey = `${action.type}:${action.target}`;
  if (failed) {
    return { type: "user_error", severity: 0.75, goalBlocked: true, repeatKey,
      attribution: { software: 0.6, user: 0.4 }, detail: String(error || "").slice(0, 200) };
  }
  // What the persona expected against what arrived. This is the signal that
  // separates "I clicked Pricing and got a contact form" from "I clicked Pricing
  // and got the prices" -- mechanically identical, and about as different as two
  // experiences can be.
  if (matched && MATCH_OUTCOMES[matched]) {
    return { ...MATCH_OUTCOMES[matched], repeatKey };
  }
  // Nothing to compare against -- fall back to whether the page answered at all.
  if ((action.type === "CLICK" || action.type === "TYPE") && !changed) {
    return { type: "ambiguous_feedback", severity: 0.45, goalBlocked: false, repeatKey,
      attribution: { interface: 0.8 } };
  }
  return { type: "success", severity: 0, recoveryQuality: 0.6, repeatKey: action.type };
}

/**
 * A task as words, whatever shape it arrived in.
 *
 * Journeys carry tasks as plain strings, but nothing guarantees that, and
 * `String(task)` on an object yields "[object Object]" -- which would be handed
 * to the persona as the thing they came to do, and would then be what the eye
 * hunts for. Silent nonsense is worse than a missing task, so an object with no
 * text in any of the usual fields becomes nothing at all.
 */
function taskText(task) {
  if (typeof task === "string") return task.trim();
  if (!task || typeof task !== "object") return "";
  for (const field of ["instruction", "description", "task", "text", "goal", "name"]) {
    if (typeof task[field] === "string" && task[field].trim()) return task[field].trim();
  }
  return "";
}

/** What the persona can see of the page, bounded by what they can hold in mind. */
function observationFrom(snapshotText, abilities) {
  const lines = String(snapshotText || "").split("\n").map((line) => line.trim()).filter(Boolean);
  // Working memory is about what a person carries forward, so the newest lines
  // are the ones kept -- but a page list is read top-down, so keep the head.
  const limit = Math.max(8, Math.floor((abilities?.cognition?.workingMemoryItems || 5) * 6));
  const kept = lines.slice(0, limit);
  const dropped = lines.length - kept.length;
  return kept.join("\n") + (dropped > 0 ? `\n... and ${dropped} more things on the page` : "");
}

class PersonaDirector {
  /**
   * @param {object} options
   * @param {function} options.actor       decides the next action (see personaActor.js)
   * @param {object}   options.profile     the simulation profile: {id, persona, behavior, abilities}
   * @param {object}   [options.model]     what to report as the deciding model
   * @param {number}   [options.maxSteps]
   */
  constructor({ actor, profile, model, maxSteps = DEFAULT_MAX_STEPS, sleepFn = sleep,
    scale = timeScale(), perception = new PerceptionClient(), walk = lookAtPage,
    frames = recentFrames } = {}) {
    if (typeof actor !== "function") throw new Error("PersonaDirector requires an actor");
    this.name = "persona";
    this.model = model;
    this.actor = actor;
    this.profile = profile || {};
    this.abilities = this.profile.abilities || {};
    this.maxSteps = maxSteps;
    this.sleep = sleepFn;
    this.scale = scale;
    this.shots = [];
    this.perception = perception;
    this.walk = walk;
    this.frames = frames;
  }

  /** Spend a slice of simulated time on the wall clock, bounded. */
  async spend(simulatedMs) {
    await this.sleep(Math.min(MAX_REAL_WAIT_MS, Math.max(MIN_STEP_MS, simulatedMs * this.scale)));
  }

  async run(context) {
    const { journey, browser, recorder } = context;
    const controller = new BehaviorController(this.profile);
    const tasks = (journey.tasks || []).map(taskText).filter(Boolean);
    const history = [];
    let steps = 0;
    let ending = null;              // {type: "done"|"gave_up"|"abandoned"|"exhausted", detail}
    let lastUrl = "";
    let skipAction = false;         // a re-read spends a turn looking, not acting
    let pending = null;             // the page as it was left, reused next turn

    await recorder.record("agent.start", "Persona director started", {
      persona: this.profile.id, behavior: this.profile.behavior, abilities: this.abilities });

    await browser.open(journey.app.baseUrl);
    lastUrl = await browser.getUrl().catch(() => journey.app.baseUrl);
    await this.capture(browser, context, "arrived");

    while (steps < this.maxSteps && !ending) {
      if (context.signal?.aborted) { ending = { type: "abandoned", detail: "the run was cancelled" }; break; }
      steps += 1;

      const page = pending || await this.observe(browser);
      pending = null;
      const { observation, perception } = await this.look(page, tasks);
      if (perception) {
        await recorder.record("persona.perception",
          `looked at ${perception.counts.fixated} of ${perception.counts.elements} things`, {
            scan: perception.scan, eyes: perception.eyes, counts: perception.counts,
            // Present, and nothing legible where it lives. This is a defect in
            // the page, and no check against the DOM can find it.
            notPerceived: perception.notPerceived,
            // Legible, and this person never got to it. Not a defect by itself:
            // it is the answer to "why did they not click the thing that was
            // right there", which is the question a report exists to answer.
            notLookedAt: perception.notLookedAt.map((item) => item.selector),
            // The strongest thing this measurement can say: what they came for
            // was legible, on the screen, and they still did not get to it.
            // Every part of that is measured rather than asserted.
            missedWhatTheyCameFor: perception.notLookedAt
              .filter((item) => Number(item.goalAffinity) >= 0.5)
              .map((item) => ({ selector: item.selector, name: item.name,
                goalAffinity: item.goalAffinity })),
            undeclared: perception.detector?.undeclared || undefined,
          });
      }
      // Taking a page in costs a person time, and how much depends on how fast
      // they read: that is what makes a slow reader run out of patience on a
      // wordy page and a fast one not. The cost is charged to the behaviour
      // model; only a slice of it is spent on the wall clock.
      const readMs = Math.min(MAX_SCAN_MS, readingDurationMs(observation, this.abilities));
      await this.spend(readMs);

      const decision = await this.actor({
        profile: this.profile, tasks, observation,
        // How they feel is given to them, never asked of them: it is derived from
        // what the page has done to them so far.
        affect: affectInWords(controller.state),
        history: filterWorkingMemory(history, this.abilities),
      });

      // What they see and what they expect, before anything happens. Committing
      // to an expectation is what makes the next step falsifiable.
      await recorder.record("persona.expectation",
        decision.expectation || `${decision.action.type}`, {
          visible: decision.visible, expectation: decision.expectation,
          action: decision.action, malformed: decision.malformed || undefined });

      if (skipAction) {
        skipAction = false;
        history.push(`re-read the page`);
        continue;
      }

      const performed = await this.perform(decision.action, browser, context);
      // Whether the page answered is observed, never assumed. Asserting that a
      // click changed something made every action a success, so frustration
      // stayed at 0.00 for a whole live run and the coping model never fired --
      // an affect simulation that cannot be disappointed models nothing.
      const after = performed.acted ? await this.observe(browser) : page;
      const changed = after.url !== page.url || after.digest !== page.digest;
      if (performed.acted) pending = after;
      if (after.url && after.url !== lastUrl) {
        await this.capture(browser, context, `page-${steps}`);
      }
      lastUrl = after.url || lastUrl;
      history.push(`${decision.action.type}${decision.action.target ? ` ${decision.action.target}` : ""}`
        + (performed.failed ? " (it did not work)" : ""));

      if (decision.action.type === "DONE") { ending = { type: "done", detail: decision.action.content }; break; }
      if (decision.action.type === "GIVE_UP") { ending = { type: "gave_up", detail: decision.action.content }; break; }

      // Reflect: did what arrived match what was expected? A separate, factual
      // question, so the answer can be wrong -- which is what makes the feeling
      // that follows it mean something.
      const reflection = decision.expectation && typeof this.actor.reflect === "function"
        ? await this.actor.reflect({ profile: this.profile, expectation: decision.expectation,
            action: decision.action, observation: observationFrom(after.text, this.abilities) })
        : null;
      if (reflection) {
        await recorder.record("persona.reflection",
          reflection.gap || reflection.observed || `expectation ${reflection.matched}`, {
            expected: decision.expectation, observed: reflection.observed,
            matched: reflection.matched, gap: reflection.gap });
      }

      const applied = controller.apply(
        { ...outcomeEvent(decision.action, { ...performed, changed, matched: reflection?.matched }),
          durationMs: readMs },
        { taskImportance: 0.6, progressVisible: changed });
      await recorder.record("persona.affect", `frustration ${applied.after.frustration.toFixed(2)}, `
        + `confusion ${applied.after.confusion.toFixed(2)}, coping ${applied.coping.decision.type}`, {
        state: applied.after, coping: applied.coping.decision, feeling: affectInWords(applied.after),
        probabilities: applied.coping.probabilities, waitToleranceMs: applied.waitTolerance.thresholdMs });

      // Coping is control flow. This is the whole point: a persona who would have
      // walked away has to actually walk away.
      const coping = applied.coping.decision;
      if (coping.type === "abandon" && this.wouldReallyLeave(applied.after)) {
        ending = { type: "abandoned", detail: coping.reason
          || "frustration and effort exceeded what this person will spend" };
      } else if (coping.type === "abandon") {
        // Sampled, but not earned. Coping is drawn from a distribution, so
        // "abandon" comes up occasionally even for someone who is perfectly
        // content -- 1.4% a turn for a fresh persona, which over a long run is a
        // coin toss on whether the journey ends for no reason. A verdict of
        // "walked away" has to be able to point at why. Feeling like leaving and
        // staying anyway is worth recording, though: it is the shape of a page
        // someone is tolerating rather than enjoying.
        await recorder.record("persona.nearly_left",
          "Felt like giving up, but had no real reason to yet", { state: applied.after });
      } else if (coping.type === "wait") {
        await this.spend(coping.durationMs || 0);
      } else if (coping.type === "reread") {
        skipAction = true;
      } else if (coping.type === "impulsive_retry") {
        for (let repeat = 1; repeat < (coping.repetitions || 2) && !ending; repeat += 1) {
          const again = await this.perform(decision.action, browser, context);
          history.push(`${decision.action.type} again${again.failed ? " (still nothing)" : ""}`);
        }
      } else if (coping.type === "backtrack") {
        await browser.press("Alt+ArrowLeft").catch(() => {});
      }
    }

    if (!ending) ending = { type: "exhausted", detail: `stopped after ${steps} actions` };
    // What they were looking at when they stopped -- the single most useful frame
    // in the run, and the one the verdict cites.
    await this.capture(browser, context, `left-${ending.type}`);
    await recorder.record("agent.end", `Persona finished: ${ending.type}`, { ...ending, steps,
      finalState: controller.state });
    return this.verdict(ending, controller, journey, steps, lastUrl);
  }

  /**
   * Whether this person has actually been given a reason to leave.
   *
   * The same condition behavior.js uses to enter its "abandoning" mode: it takes
   * more than one failure in a row, and frustration past what this profile will
   * put up with. Someone who is simply bored does not storm off.
   */
  wouldReallyLeave(state) {
    const behavior = this.profile.behavior || {};
    const tolerance = (Number(behavior.repeatFailureTolerance) || 0.5)
      + (Number(behavior.persistence) || 0.5) * 0.35;
    return state.consecutiveFailures > 1 && state.frustration > tolerance;
  }

  /**
   * Take a picture of what the persona is looking at.
   *
   * Evidence is not bookkeeping. journeytest-core requires each criterion to cite
   * a screenshot, and the UX layer that reads this run afterwards has nothing to
   * reason about without one -- so a capture is taken when the persona arrives
   * somewhere new and again at the end, which is when a person would remember
   * what they saw.
   */
  async capture(browser, context, label) {
    const directory = context.artifacts?.screenshotsDir;
    if (!directory) return null;
    const name = `${String(this.shots.length + 1).padStart(3, "0")}-${label}.png`;
    const target = path.join(directory, name);
    try {
      await browser.screenshot({ path: target, full: true });
    } catch {
      return null;      // a capture that fails is not worth ending a journey over
    }
    this.shots.push(target);
    await context.recorder.record("browser.screenshot", `Captured screenshot ${target}`, { path: target });
    return target;
  }

  /**
   * What the page is right now: its address, its contents, and a digest of them.
   *
   * The digest is what makes "did anything happen?" answerable. A person knows
   * whether the page responded; a run that assumes it did cannot tell a working
   * control from a dead one, which is the single most common real complaint.
   */
  async observe(browser) {
    const snapshot = await browser.snapshot({ compact: false }).catch(() => ({ stdout: "" }));
    const text = String(snapshot.stdout || snapshot.summary || "");
    const url = await browser.getUrl().catch(() => "");
    return { url, text, digest: createHash("sha1").update(url + "\n" + text).digest("hex") };
  }

  /**
   * What this person took in, as opposed to what is on the page.
   *
   * The accessibility tree is complete, which is exactly what is wrong with it
   * as a model of seeing: handed all of it, every persona reads all of it, and a
   * short-sighted one in a hurry behaves identically to a patient one with
   * perfect vision. The perception service answers the narrower question --
   * these pixels, these eyes, this way of scanning -- and returns only what was
   * actually looked at.
   *
   * When it is not configured or not reachable the tree-based observation stands.
   * Perception is meant to make a run truer, not to make a run fail.
   */
  async look(page, tasks = []) {
    const fallback = { observation: observationFrom(page.text, this.abilities), perception: null };
    if (!this.perception?.available) return fallback;
    let seen;
    try {
      seen = await this.walk();
    } catch {
      // A page walk can fail for reasons that have nothing to do with the run --
      // a navigation mid-batch, a browser still settling. The tree is still there.
      return fallback;
    }
    if (!seen?.elements?.length || !seen.screenshotBase64) return fallback;
    const perception = await this.perception.perceive({
      screenshotBase64: seen.screenshotBase64,
      elements: seen.elements,
      abilities: this.abilities,
      behavior: this.profile.behavior,
      motionFrames: motionFramesFrom(this.frames()),
      viewport: seen.viewport,
      // What they came for pulls the eye harder than anything else on a page,
      // which is why an impatient visitor finds a price and reads nothing else.
      goal: (this.profile.persona?.goals || []).concat(tasks).join(". "),
    });
    if (!perception?.observation) return fallback;
    return { observation: perception.observation, perception };
  }

  /**
   * Turn one ACTION into driver calls.
   *
   * CLICK goes through the pointer simulation: a person with imprecise pointing
   * does not land dead centre, and on a small target they miss. The driver takes
   * a selector rather than a coordinate, so the scatter is recorded as what it
   * is -- where this person's hand actually went -- and a miss outside the
   * element's own box is reported as a failed action rather than silently
   * corrected.
   */
  async perform(action, browser, context) {
    const result = { failed: false, acted: false, url: "", error: "" };
    try {
      switch (action.type) {
        case "READ":
          result.acted = false;      // looking changes nothing, so nothing is re-observed
          break;
        case "CLICK": {
          const aim = await this.aimFor(action.target, browser, context);
          if (aim && aim.missed) {
            // The hand went outside the control. Nothing happens, which is
            // exactly what happens to a person who misses.
            result.failed = true;
            result.error = "the click landed outside the control";
            break;
          }
          await browser.scrollIntoView(action.target).catch(() => {});
          await browser.click(action.target);
          result.acted = true;
          break;
        }
        case "SCROLL":
          await browser.scroll({ direction: /up/i.test(action.content) ? "up" : "down",
            amount: Number.parseInt(action.target, 10) || 800 });
          result.acted = true;
          break;
        case "TYPE":
          await browser.fill(action.target, action.content);
          result.acted = true;
          break;
        case "GO_BACK":
          await browser.press("Alt+ArrowLeft");
          result.acted = true;
          break;
        default:
          break;      // DONE and GIVE_UP touch nothing
      }
    } catch (error) {
      result.failed = true;
      result.acted = true;    // the reach happened even though it came to nothing
      result.error = String(error?.message || error);
    }
    result.url = await browser.getUrl().catch(() => "");
    return result;
  }

  /** Where this persona's pointer actually lands, and whether that is on target. */
  async aimFor(target, browser, context) {
    const precision = this.abilities?.motor?.pointerPrecision;
    if (precision === undefined || precision >= 0.99 || !target) return null;
    let box;
    try {
      box = (await browser.getElementBox(target))?.details;
    } catch {
      return null;
    }
    if (!box || !box.width || !box.height) return null;
    const aim = simulatePointer(box, this.abilities, Number(this.profile.behavior?.seed) || 1);
    const missed = aim.x < box.x || aim.x > box.x + box.width
      || aim.y < box.y || aim.y > box.y + box.height;
    await context.recorder.record("persona.pointer",
      `aimed at ${Math.round(aim.x)}, ${Math.round(aim.y)}${missed ? " and missed" : ""}`,
      { target, box, aim, missed });
    return { ...aim, missed };
  }

  /**
   * What happened, as a verdict.
   *
   * A person who gave up is a result, not an absence of one. The old fallback
   * reported "inconclusive" whenever nothing called journey_finish, which read as
   * a harness problem when it was often the product's.
   */
  verdict(ending, controller, journey, steps, url = "") {
    const passCriterion = (journey.passCriteria || [])[0]?.id || "tasks-completed";
    const failCriterion = (journey.failCriteria || [])[0]?.id || "tasks-blocked";
    const state = controller.state;
    const completed = ending.type === "done";
    const evidence = this.shots.at(-1) || this.shots[0] || undefined;
    const summary = {
      done: `Completed what they came to do. ${ending.detail || ""}`.trim(),
      gave_up: `Gave up: ${ending.detail || "not worth any more time"}.`,
      abandoned: `Walked away after ${steps} actions -- ${ending.detail}.`,
      exhausted: `Still going after ${steps} actions without finishing.`,
    }[ending.type];

    return {
      status: completed ? "passed" : ending.type === "exhausted" ? "inconclusive" : "failed",
      confidence: ending.type === "exhausted" ? "low" : "high",
      summary: `${summary} Frustration ended at ${state.frustration.toFixed(2)}, `
        + `confusion at ${state.confusion.toFixed(2)}, trust at ${state.trust.toFixed(2)}.`,
      // Each criterion cites the frame the persona was looking at when they
      // stopped: the journey contract requires screenshot evidence, and a
      // conclusion about a page should be able to show the page.
      criteria: [
        { id: passCriterion, result: completed ? "met" : "not-met",
          explanation: completed ? summary : `${summary} The tasks were not completed.`,
          evidence: { screenshot: evidence, url, observation: summary } },
        { id: failCriterion, result: completed ? "not-met" : "met",
          explanation: completed ? "Nothing blocked this person." : summary,
          evidence: { screenshot: evidence, url, observation: summary } },
      ],
      blockers: completed ? [] : [{
        id: "persona-stopped", severity: ending.type === "exhausted" ? "minor" : "major",
        category: "blocker", title: `The visitor ${ending.type === "gave_up" ? "gave up" : "did not get there"}`,
        evidence: { screenshot: evidence, url },
        description: `${summary} This is what the page cost this particular person: `
          + `frustration ${state.frustration.toFixed(2)}, confusion ${state.confusion.toFixed(2)}, `
          + `${steps} actions, ${state.consecutiveFailures} of them in a row that went nowhere.`,
      }],
      uxFindings: [], suggestedImprovements: [],
    };
  }
}

module.exports = { DEFAULT_MAX_STEPS, PersonaDirector, observationFrom, outcomeEvent };
