"use strict";
/**
 * Whether an action sounds like the person who is supposed to be taking it.
 *
 * This is TinyTroupe's ActionGenerator, which is the piece that makes a persona
 * more than a prompt. Telling a model "you are impatient and want concrete
 * pricing" and hoping is roleplay; what TinyTroupe does instead is generate the
 * action, score it against the persona specification, and if it scores badly,
 * hand the criticism back and make the agent produce another one. The persona
 * becomes a constraint the output has to satisfy rather than an instruction it
 * may drift away from.
 *
 * The numbers are TinyTroupe's own: two attempts, a threshold of 7 out of 10,
 * and a deliberately harsh judge -- their proposition text says to subtract 20%
 * of the score for any flaw found "regardless of its severity ... to be very
 * harsh and avoid any ambiguity". A lenient judge passes everything and the gate
 * does nothing at all.
 *
 * Two behaviours are theirs and both matter. When no attempt passes, the last
 * one is used rather than the first: it has been through the most criticism.
 * And the judge is told to consider only the persona and the proposed action --
 * not whether the action is a good idea, which is a different question and one a
 * usability test must not answer on the persona's behalf. A confused person
 * doing a confused thing is the finding, not an error to correct.
 */

const DEFAULT_MAX_ATTEMPTS = 2;
const DEFAULT_THRESHOLD = 7;

/** The judge's brief. TinyTroupe's hard_action_persona_adherence, in our terms. */
const ADHERENCE_SYSTEM = `You judge whether one proposed action fits one specific person.

You are given a person and the next thing they propose to do. Score from 0 to 10
how completely that action adheres to who they are: not whether it is clever, not
whether it will work, only whether it is what this person would do.

Be harsh. Subtract 2 points for any flaw you find, regardless of how small.

Judge only the person and the proposed action. Do not consider whether the action
is a good idea -- a confused person doing a confused thing adheres perfectly.
Do not imagine a better action; judge the one you were given.

Answer as JSON and nothing else:
{"score": 0-10, "flaw": "the single clearest way it does not fit, or empty"}`;

function personaBrief(profile) {
  const persona = profile?.persona || {};
  const behavior = profile?.behavior || {};
  const traits = Object.entries(behavior)
    .filter(([name, value]) => name !== "seed" && typeof value === "number")
    .map(([name, value]) => `${name} ${Number(value).toFixed(2)}`)
    .join(", ");
  return [
    `Name: ${persona.name || "someone"}`,
    persona.occupation ? `Occupation: ${persona.occupation}` : "",
    (persona.goals || []).length ? `Wants: ${(persona.goals || []).join("; ")}` : "",
    // Not "impatient with": a constraint is often already written as a whole
    // sentence about the person, and prefixing one produces "Impatient with:
    // Impatient with vague marketing copy".
    (persona.constraints || []).length ? `True of them: ${(persona.constraints || []).join("; ")}` : "",
    traits ? `Traits, 0 to 1: ${traits}` : "",
  ].filter(Boolean).join("\n");
}

function parseScore(text) {
  const match = String(text || "").match(/\{[\s\S]*\}/);
  if (!match) return null;
  try {
    const parsed = JSON.parse(match[0]);
    const score = Number(parsed.score);
    if (!Number.isFinite(score)) return null;
    return { score: Math.max(0, Math.min(10, score)), flaw: String(parsed.flaw || "").slice(0, 300) };
  } catch {
    return null;
  }
}

/** One action, as the judge sees it. */
function actionBrief(decision) {
  const action = decision?.action || {};
  return [
    `They say they can see: ${decision?.visible || "(nothing stated)"}`,
    `They expect: ${decision?.expectation || "(nothing stated)"}`,
    `They will: ${action.type}${action.target ? ` ${action.target}` : ""}`
      + `${action.content ? ` -- "${action.content}"` : ""}`,
  ].join("\n");
}

class AdherenceGate {
  /**
   * @param {object} [options]
   * @param {number} [options.maxAttempts]  TinyTroupe's max_attempts
   * @param {number} [options.threshold]    TinyTroupe's quality_threshold, out of 10
   * @param {function} [options.judge]      async ({system, user}) => text
   */
  constructor({ maxAttempts = DEFAULT_MAX_ATTEMPTS, threshold = DEFAULT_THRESHOLD,
    judge, enabled } = {}) {
    this.maxAttempts = Math.max(1, maxAttempts);
    this.threshold = threshold;
    this.judge = judge;
    this.enabled = enabled ?? Boolean(judge);
    // TinyTroupe keeps these on the generator; they are what tells you whether
    // the gate is doing anything or just costing a call per step.
    this.stats = { judged: 0, passedFirst: 0, regenerated: 0, keptDespiteFailing: 0, scores: [] };
  }

  /**
   * Score one proposed action, or null when there is nothing to judge with.
   *
   * A judge that fails is not a failing action. The gate is an improvement on
   * the persona, not a dependency of the run: an unreachable judge means the
   * action stands, exactly as it would have without any of this.
   */
  async score(profile, decision) {
    if (!this.enabled || !this.judge) return null;
    let text;
    try {
      text = await this.judge({
        system: ADHERENCE_SYSTEM,
        user: `THE PERSON:\n${personaBrief(profile)}\n\nTHE PROPOSED NEXT ACTION:\n${actionBrief(decision)}`,
      });
    } catch {
      return null;
    }
    const parsed = parseScore(text);
    if (!parsed) return null;
    this.stats.judged += 1;
    this.stats.scores.push(parsed.score);
    return parsed;
  }

  /**
   * The action this person would actually take.
   *
   * `regenerate(feedback)` asks for another one, told what was wrong with the
   * last. When nothing clears the bar the final attempt is what stands, because
   * it is the one that has been criticised the most -- TinyTroupe's choice, and
   * the right one: refusing to act is not something a person does.
   */
  async settle(profile, decision, regenerate) {
    let current = decision;
    let judged = await this.score(profile, current);
    if (!judged) return { decision: current, adherence: null };
    if (judged.score >= this.threshold) {
      this.stats.passedFirst += 1;
      return { decision: current, adherence: { ...judged, attempts: 1, passed: true } };
    }

    const history = [judged];
    for (let attempt = 2; attempt <= this.maxAttempts; attempt += 1) {
      let next;
      try {
        next = await regenerate(judged.flaw);
      } catch {
        break;
      }
      if (!next?.action) break;
      this.stats.regenerated += 1;
      current = next;
      judged = await this.score(profile, current);
      if (!judged) return { decision: current, adherence: null };
      history.push(judged);
      if (judged.score >= this.threshold) {
        return { decision: current,
          adherence: { ...judged, attempts: attempt, passed: true, history } };
      }
    }
    this.stats.keptDespiteFailing += 1;
    return { decision: current,
      adherence: { ...judged, attempts: history.length, passed: false, history } };
  }
}

module.exports = { ADHERENCE_SYSTEM, AdherenceGate, DEFAULT_MAX_ATTEMPTS, DEFAULT_THRESHOLD,
  actionBrief, parseScore, personaBrief };
