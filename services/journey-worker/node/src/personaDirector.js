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
const { writeFile } = require("node:fs/promises");
const path = require("node:path");

const { AdherenceGate } = require("./adherence");
const { BehaviorController } = require("./behavior");
const { browsingFaculty } = require("./faculty");
const { PersonaMemoryBank } = require("./memoryBank");
const { PerceptionClient, lookAtPage, motionFramesFrom } = require("./perception");
const { MATCH_OUTCOMES, affectInWords } = require("./personaActor");
const { filterWorkingMemory, readingDurationMs, simulatePointer } = require("./physical");
const { holdRevealKeeper, releaseRevealKeeper, revealOnce } = require("./revealKeeper");
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
/**
 * What the thing acted on says on it, according to the eyes that chose it.
 *
 * The perception walk already carries a name for every element it resolved, and
 * the selectors it uses are the same strings the actor targets -- so the run has
 * always known that "e18" is the "Monthly" button and never told anyone.
 */
function nameOf(target, perception) {
  if (!target || !perception) return "";
  const items = [...(perception.perceived || []), ...(perception.notLookedAt || [])];
  const found = items.find((item) => item && item.selector === target);
  return found && typeof found.name === "string" ? found.name.trim() : "";
}

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
    frames = recentFrames, faculty, gate, memory } = {}) {
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
    // What this person has already been told about themselves, kept across runs.
    // Every judged action goes in; recurring criticism is consolidated into
    // standing lessons that reach the next step through the faculty.
    this.memory = memory === undefined
      ? new PersonaMemoryBank({ personaId: this.profile.id,
          // The same small model that judges also puts a recurring criticism
          // into this person's own voice. A raw flaw shown back to the persona
          // measured worse than showing nothing at all.
          rewrite: actor.judgeAdherence,
          // Names only. The full vocabulary carries an example ref, and the
          // rewriter copied it into a lesson verbatim.
          vocabulary: browsingFaculty().actionTypes.join(", ") })
      : memory;
    this.faculty = faculty || browsingFaculty({ abilities: this.abilities,
      seed: Number(this.profile.behavior?.seed) || 1, memory: this.memory || undefined });
    // An action that does not sound like this person is sent back with the
    // reason, TinyTroupe-style. Without a judge the gate is simply off.
    this.gate = gate || new AdherenceGate({ judge: actor.judgeAdherence });
  }

  /** Run the page's scroll-reveals through once and wait for them. A seam, so a
   * test can assert the capture waits for it without a live browser. */
  async settle() {
    try {
      await revealOnce();
    } catch {
      // A reveal pass that fails is not worth losing the capture over; the
      // picture is then of whatever has revealed itself so far, which is what it
      // was before this existed.
    }
  }

  /** Stop the page being scrolled under a measurement. Seams, so a test can
   * assert the hold without a live keeper. */
  hold() { return holdRevealKeeper(); }

  release() { return releaseRevealKeeper(); }

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
    let pendingSeen = null;         // and how it looked through this person's eyes

    await recorder.record("agent.start", "Persona director started", {
      persona: this.profile.id, behavior: this.profile.behavior, abilities: this.abilities,
      // What this person already knew about themselves when they arrived.
      memory: this.memory ? this.memory.describe() : null });

    await browser.open(journey.app.baseUrl);
    lastUrl = await browser.getUrl().catch(() => journey.app.baseUrl);
    await this.capture(browser, context, "arrived");

    let reportedGateFailure = false;
    let reportedPerceptionFailure = false;
    while (steps < this.maxSteps && !ending) {
      if (context.signal?.aborted) { ending = { type: "abandoned", detail: "the run was cancelled" }; break; }
      steps += 1;

      const page = pending || await this.observe(browser);
      pending = null;
      // The walk that followed the last action, when there was one. Looking again
      // here would describe the same page twice and charge a second perception
      // pass for it; the point of carrying it is that reflection and the next
      // decision are then reasoning about one act of seeing rather than two.
      const seen = pendingSeen || await this.look(page, tasks);
      pendingSeen = null;
      const { observation, perception } = seen;
      // One failed call disables the perception client for the rest of the run
      // (perception.js: `this.disabled = true`). That is the right behaviour --
      // retrying a dead service every step would only slow the run down -- but it
      // was silent: the run continued on the accessibility tree, produced a report
      // with no eyesight findings at all, and nothing anywhere said the eyes had
      // stopped working. An absence of findings has to be distinguishable from an
      // absence of measurement.
      if (!perception && !reportedPerceptionFailure && this.perception?.lastError) {
        reportedPerceptionFailure = true;
        await recorder.record("persona.perception_unavailable",
          "Stopped seeing the page through this person's eyes", {
            reason: this.perception.lastError, sinceStep: steps });
      }
      if (perception) {
        const seenImage = await this.keepSeenImage(context, perception, steps);
        await recorder.record("persona.perception",
          `looked at ${perception.counts.fixated} of ${perception.counts.elements} things`, {
            scan: perception.scan, eyes: perception.eyes, counts: perception.counts,
            // Present, and nothing legible where it lives. This is a defect in
            // the page, and no check against the DOM can find it.
            notPerceived: perception.notPerceived,
            // Everything that did resolve on this capture, by selector. Cheap to
            // carry and it settles a question nothing else can: a heading is not
            // drawn black on one step and invisible on the next, so when the same
            // element reads legible on one capture and blank on another, the blank
            // one caught it mid-render. Without this the report had no way to tell
            // a page that never draws something from a capture taken while it was
            // still arriving -- and published "Fails WCAG AA contrast: 'Individual'
            // -- 1.05:1" against a pricing-card heading that is plainly dark.
            legible: [...(perception.perceived || []).map((item) => item.selector),
                      ...(perception.notLookedAt || []).map((item) => item.selector)],
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
            // What this person's eyes actually delivered, when the step found
            // something they could not read.
            seenImage: seenImage || undefined,
          });
      }
      // Taking a page in costs a person time, and how much depends on how fast
      // they read: that is what makes a slow reader run out of patience on a
      // wordy page and a fast one not. The cost is charged to the behaviour
      // model; only a slice of it is spent on the wall clock.
      const readMs = Math.min(MAX_SCAN_MS, readingDurationMs(observation, this.abilities));
      await this.spend(readMs);

      const ask = {
        profile: this.profile, tasks, observation,
        // Everything the persona's capabilities have to say about how to use
        // them -- including what the memory bank has learned about this person.
        constraints: this.faculty.actionsConstraintsPrompt(),
        // How they feel is given to them, never asked of them: it is derived from
        // what the page has done to them so far.
        affect: affectInWords(controller.state),
        history: filterWorkingMemory(history, this.abilities),
      };
      const proposed = await this.actor(ask);
      // Does that sound like this person? TinyTroupe scores the action against
      // the persona and, when it scores badly, hands the criticism back and asks
      // for another. That is what makes a persona a constraint on the output
      // rather than an instruction it may drift away from.
      const settled = await this.gate.settle(this.profile, proposed,
        (flaw) => this.actor(ask, { notLikeYou: flaw }));
      const decision = settled.decision;
      if (this.gate.unavailableReason && !reportedGateFailure) {
        reportedGateFailure = true;
        // Said once, not every step. A run where nothing held the persona to
        // itself looks identical to one where everything passed, and the
        // difference matters more than any single step does.
        await recorder.record("persona.adherence_unavailable",
          "nothing checked whether these actions sound like this person",
          { reason: this.gate.unavailableReason });
      }
      if (settled.adherence && this.memory) {
        // Stored before the action is carried out, so the lesson is available on
        // the very next step rather than only on the next run. That is what
        // makes the persona better with each action instead of each session.
        this.memory.store({ ...settled.adherence, action: decision.action,
          visible: decision.visible, expectation: decision.expectation });
        // Said in their own words before the next step asks for constraints.
        // Cached per lesson, so this costs one call the first time a criticism
        // becomes a standing lesson and nothing on the steps after.
        await this.memory.consolidate();
      }
      if (settled.adherence) {
        await recorder.record("persona.adherence",
          settled.adherence.passed
            ? `that is like them (${settled.adherence.score}/10)`
            : `still not quite like them (${settled.adherence.score}/10)`,
          { ...settled.adherence, threshold: this.gate.threshold });
      }

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
      // Look at what the action produced, now, with the same eyes that chose it.
      // Reflection used to be asked "did what you expected appear?" while holding
      // the accessibility tree, when the expectation had been formed from what
      // this person could actually see -- two different views of one page, and a
      // question that compares across them manufactures gaps. A live run put the
      // monthly prices in front of the persona, reflected against the tree, and
      // concluded three times over that "the paragraph detailing the £20 per user
      // per month pricing was not present". Frustration reached 1.00 and the
      // report led on a fault the page does not have.
      let afterSeen = null;
      if (performed.acted) {
        afterSeen = await this.look(after, tasks);
        pending = after;
        // Only worth carrying if it is worth more than looking again. A walk taken
        // the instant an action lands can catch the page still moving, and then it
        // falls back to the tree -- correctly, that is the guard working. Carrying
        // that forward spent the next turn's look as well: cycle 15 scrolled three
        // times and four consecutive steps went by with no perception at all, two
        // of them on a page that had long since come to rest. A failed look costs
        // this step. It must not cost the next one.
        if (afterSeen.perception) pendingSeen = afterSeen;
      }
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
            action: decision.action, targetName: nameOf(decision.action.target, perception),
            observation: (performed.acted ? afterSeen?.observation : observation)
              || observationFrom(after.text, this.abilities) })
        : null;
      if (reflection) {
        await recorder.record("persona.reflection",
          reflection.gap || reflection.observed || `expectation ${reflection.matched}`, {
            expected: decision.expectation, observed: reflection.observed,
            matched: reflection.matched, gap: reflection.gap,
            // Which view answered the question. An expectation formed from
            // perception and tested against the tree is the comparison that
            // invented three price gaps in cycle 14, and nothing in the record
            // said which view either side came from -- so it read as one
            // measurement disagreeing with itself. Same-kind or not, say so.
            judgedAgainst: (performed.acted ? afterSeen : { perception })?.perception
              ? "perceived" : "tree",
            decidedFrom: perception ? "perceived" : "tree" });
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
          // The page moved after it was carried, so what was carried describes a
          // page that no longer exists. Drop it and let the next turn look.
          if (again.acted) { pending = null; pendingSeen = null; }
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
      finalState: controller.state,
      // What this run leaves behind for the next one. Recorded at the end as well
      // as the start, because "the persona gets better with each action" is a
      // claim about a difference between two runs, and only the start was ever
      // written down -- so there was nothing to compare it against.
      memory: this.memory ? this.memory.describe() : null,
      // How often an action had to be sent back for not sounding like this person.
      // A gate that never fires and a gate that is switched off look identical in
      // a report that does not say which.
      adherence: this.gate?.stats ? { ...this.gate.stats } : null });
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
      // Scroll the whole document through before photographing it. `full: true`
      // stitches a capture as tall as the page, and everything below the fold on a
      // site that reveals content on scroll is still in its un-revealed state the
      // moment a document loads -- so the first capture of a run, taken straight
      // after open(), is mostly blank. Measured on a live run: 7,921 of 8,620 rows
      // near-uniform, 92% of the image. The vision critique looked at it and filed
      // "Massive empty vertical sections ... a major rendering bug", severity
      // critical, as the most serious finding in the report. It was describing our
      // capture, not the site.
      //
      // The reveal keeper does this every 1500ms, which is no help to a capture
      // taken in the first second of a document or to a run that finishes in three
      // actions. Awaited here so the picture is of a settled page.
      await this.settle();
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
    // Hold the page still for the walk and the capture. The reveal keeper scrolls
    // the whole document every 1500ms and a perception pass takes longer than
    // that, so without this the boxes and the pixels describe the page at two
    // different scroll positions -- which is how a live run came to report the
    // entire navigation bar as failing WCAG AA at 1:1 for someone with 0.95
    // acuity: the crops had landed on blank page.
    this.hold();
    try {
      seen = await this.walk();
    } catch {
      // A page walk can fail for reasons that have nothing to do with the run --
      // a navigation mid-batch, a browser still settling. The tree is still there.
      return fallback;
    } finally {
      this.release();
    }
    if (!seen?.elements?.length || !seen.screenshotBase64) return fallback;
    // Something moved the page anyway -- the page's own script, an animation, a
    // navigation landing mid-batch. Boxes from one scroll position against pixels
    // from another measure nothing, and the failure mode is not a gap in the
    // report but a confident false finding. Fall back to the tree for this step.
    if (seen.moved) return fallback;
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
      // The page as this person's eyes delivered it. The honest thing to put
      // beside a finding that says they could not see something -- and until now
      // the service could produce it and nobody ever asked.
      returnSeenImage: true,
    });
    if (!perception?.observation) return fallback;
    return { observation: perception.observation, perception };
  }

  /**
   * Keep the degraded capture, but only when it is evidence of something.
   *
   * Written for a step that found an element present and not perceivable, so a
   * report can show what this person's eyes actually delivered next to the claim
   * that they could not read it. Kept off every other step because a JPEG per
   * step of a forty-step run is a lot of bytes to store for a picture nothing
   * will cite.
   */
  async keepSeenImage(context, perception, step) {
    const directory = context.artifacts?.screenshotsDir;
    if (!directory || !perception?.seenImageBase64) return null;
    if (!(perception.notPerceived || []).length) return null;
    const target = path.join(directory, `${String(step).padStart(3, "0")}-as-they-saw-it.jpg`);
    try {
      await writeFile(target, Buffer.from(perception.seenImageBase64, "base64"));
    } catch {
      return null;      // evidence that cannot be written is not worth ending a run over
    }
    return target;
  }

  /**
   * Carry out one ACTION, by offering it to the tools the persona has.
   *
   * The director used to hold a switch over action types, and the prompt held a
   * separate list of what those types were. TinyTroupe's arrangement is better
   * and this now follows it: each tool declares the actions it offers and
   * carries them out, the vocabulary the persona is given is generated from
   * those declarations, and an action nothing claims comes back unhandled
   * instead of falling through to a silent no-op.
   */
  perform(action, browser, context) {
    return this.faculty.processAction(action, { browser, recorder: context.recorder, context });
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
        // "Blocked" is a claim about the page, and only two of the four endings
        // support it: they gave up, or they walked away. Running out of the
        // harness's own step budget is not one -- a live report headlined "The
        // journey was blocked before completion", severity critical, over a run
        // whose record says "Still going after 16 actions without finishing".
        // Nothing had blocked that person; the budget ran out while they were
        // still working. The pass criterion already says they did not finish,
        // which is true and is what the report should lead with.
        { id: failCriterion, result: ending.type === "exhausted" ? "not-observed"
            : completed ? "not-met" : "met",
          explanation: completed ? "Nothing blocked this person."
            : ending.type === "exhausted"
              ? `${summary} They had not given up when the run's action budget ran out, so `
                + "whether the page would have blocked them is not established."
              : summary,
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

module.exports = { DEFAULT_MAX_STEPS, PersonaDirector, nameOf, observationFrom, outcomeEvent };
