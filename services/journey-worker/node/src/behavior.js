"use strict";

// These coefficients are simulation assumptions, not calibrated human estimates.
const STATE_REDUCER_VERSION = "behavior-state-v1";
const COPING_POLICY_VERSION = "coping-policy-v1";
const WAIT_TOLERANCE_VERSION = "wait-tolerance-v1";

const clamp = (value) => Math.max(0, Math.min(1, value));
const rounded = (value) => Number(clamp(value).toFixed(6));

function seededRandom(seed) {
  let state = (Number(seed) || 1) >>> 0;
  return () => {
    state += 0x6d2b79f5;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function initialState() {
  return {
    step: 0, elapsedMs: 0, frustration: 0, anger: 0, confusion: 0,
    trust: 1, confidence: 1, cognitiveEffort: 0, physicalEffort: 0,
    fatigue: 0, perceivedProgress: 0, consecutiveFailures: 0,
    repeatedEventCounts: {}, recentElementIds: [], rememberedFacts: [],
    copingMode: "normal", abandoned: false,
  };
}

function reduceState(previous, event, profile) {
  const state = { ...previous, repeatedEventCounts: { ...previous.repeatedEventCounts } };
  const severity = clamp(event.severity ?? (event.type === "success" ? 0 : 0.5));
  const durationMs = Math.max(0, Number(event.durationMs) || 0);
  const repeatKey = event.repeatKey || event.type;
  const repeatCount = (state.repeatedEventCounts[repeatKey] || 0) + 1;
  state.repeatedEventCounts[repeatKey] = repeatCount;
  state.step += 1;
  state.elapsedMs += durationMs;
  const successful = ["success", "recovery", "progress"].includes(event.type);
  const waiting = event.type === "waiting";

  if (successful) {
    const recovery = clamp(event.recoveryQuality ?? 0.5);
    state.consecutiveFailures = 0;
    state.frustration = rounded(state.frustration - (0.08 + profile.angerRecovery * 0.18) * recovery);
    state.anger = rounded(state.anger - (0.1 + profile.angerRecovery * 0.25) * recovery);
    state.confusion = rounded(state.confusion - 0.2 * recovery);
    state.trust = rounded(state.trust + 0.08 * recovery);
    state.confidence = rounded(state.confidence + 0.06 * recovery);
    state.perceivedProgress = rounded(state.perceivedProgress + (event.type === "success" ? 0.35 : 0.15));
  } else {
    state.consecutiveFailures += waiting && event.progressVisible ? 0 : 1;
    const repetition = 1 + 0.18 * Math.max(0, repeatCount - 1) ** 1.35;
    const blocked = event.goalBlocked ? 1.25 : 1;
    const momentum = 1 + state.frustration * 0.35;
    const impact = severity * repetition * blocked * momentum;
    state.frustration = rounded(state.frustration + impact * (0.12 + profile.irritability * 0.13));
    state.anger = rounded(state.anger + impact * profile.angerReactivity * 0.16);
    state.confusion = rounded(state.confusion + impact * (["ambiguous_feedback", "user_error", "perception_failure"].includes(event.type) ? 0.24 : 0.08));
    state.trust = rounded(state.trust - impact * 0.1 * (event.attribution?.software || event.attribution?.interface || 0.5));
    state.confidence = rounded(state.confidence - impact * 0.08 * (event.attribution?.user || event.attribution?.capability || 0.5));
    state.perceivedProgress = rounded(state.perceivedProgress - impact * 0.06);
  }
  state.cognitiveEffort = rounded(state.cognitiveEffort + severity * (waiting ? 0.03 : 0.1));
  state.fatigue = rounded(state.fatigue + severity * 0.04 + durationMs / 600000);
  return state;
}

function computeWaitTolerance(profile, state, context = {}) {
  const baselineMs = Math.max(1000, Number(context.baselineMs) || 8000);
  const multiplier = 0.45 + profile.patience * 1.1 + state.trust * 0.3
    + (context.progressVisible ? 0.65 : 0) + clamp(context.taskImportance ?? 0.5) * 0.3
    - state.frustration * 0.55 - clamp(context.timePressure ?? 0) * 0.5
    + clamp(context.expectedComplexity ?? 0.5) * 0.25;
  return { thresholdMs: Math.round(baselineMs * Math.max(0.2, multiplier)), version: WAIT_TOLERANCE_VERSION,
    factors: { progressVisible: Boolean(context.progressVisible), taskImportance: clamp(context.taskImportance ?? 0.5), timePressure: clamp(context.timePressure ?? 0), expectedComplexity: clamp(context.expectedComplexity ?? 0.5) } };
}

// JRN-1: how much frustration this profile tolerates, sustained across more
// than one failure in a row, before abandoning has to become reachable --
// persistence raises it, the same way it already raises `retry`'s own score.
// Shared by copingScores below and by whoever needs to know the threshold
// itself (previously computed a second time in BehaviorController.apply,
// only to set a copingMode label that the very next lines overwrote
// unconditionally -- the label was dead code with a plausible name; this is
// the same arithmetic, kept, now the one place it does something).
function abandonTolerance(profile) {
  return profile.repeatFailureTolerance + profile.persistence * 0.35;
}

function copingScores(profile, state, context = {}) {
  const pressure = clamp(context.timePressure ?? 0);
  const importance = clamp(context.taskImportance ?? 0.5);
  const scores = {
    // Getting on with it. Coping is what a person does when something has gone
    // wrong, and every other entry here is a form of that -- so without this one
    // the model had no way to express "that worked, next thing", and made a calm
    // persona whose expectation had just been met retry the action that worked
    // (60.3%), re-read the page (13.5%) or click the same thing two or three more
    // times (9.3%). Coping is control flow in the director, so those were real
    // wasted steps: a live run spent a quarter of its budget on them and clicked
    // one link twice.
    //
    // It dominates while things are going well and collapses as they stop: the
    // negative terms are weighted above the positive ones on purpose, so a person
    // who is confused or frustrated reaches for a coping behaviour rather than
    // ploughing on, which is the behaviour the rest of this table exists to model.
    continue: 1.4 + state.perceivedProgress * 1.2 + profile.selfEfficacy * 0.5
      - state.confusion * 1.6 - state.frustration * 1.6 - state.anger * 1.4
      - state.consecutiveFailures * 0.5,
    retry: 0.2 + profile.persistence * 1.1 + profile.selfEfficacy * 0.7 - state.fatigue * 0.5,
    reread: 0.1 + profile.verificationTendency * 1.0 + state.confusion * 1.1,
    wait: 0.1 + profile.patience * 1.0 + state.perceivedProgress * 0.8 - pressure * 0.6,
    explore: 0.1 + profile.exploration * 0.9 + state.confusion * 0.4,
    seek_help: profile.helpSeeking * 1.1 + state.confusion * 0.8 - profile.selfEfficacy * 0.2,
    backtrack: state.confusion * 0.7 + state.consecutiveFailures * 0.18,
    impulsive_retry: profile.impulsivity * 0.9 + profile.irritability * 0.4 + state.anger * 0.9,
    abandon: state.frustration * 1.3 + state.fatigue * 0.8 + pressure * 0.7 - profile.persistence * 0.9 - importance * 0.5,
  };
  // JRN-1: abandon's own score above competes on the same footing as every
  // other entry, and loses -- measured on a real run that reached
  // frustration 1.00 with six failures in a row: reread scored 1.90,
  // backtrack 1.78, retry 1.37, abandon only 0.77, so p(abandon) peaked at
  // 0.033 (softmax at this file's *2 temperature never closes a gap that
  // size with the terms above alone) and the run left only when its step
  // budget ran out, never because the persona chose to leave. Boosted here,
  // and only once this profile's own persistence-adjusted tolerance for
  // repeated failure is actually exceeded -- a run below it is completely
  // unaffected -- scaled by how far over: +1 the moment it is crossed,
  // growing with the excess. On that same real trajectory this makes
  // abandoning reachable rather than certain: p(abandon) 0.01 pre-tolerance,
  // 0.33 the step tolerance is first crossed, 0.62 (the new leader) at
  // frustration 1.00 -- a strong majority outcome, not a coin flip forced
  // every time, so a profile built to be unusually persistent can still
  // occasionally push through.
  if (state.consecutiveFailures > 1 && state.frustration > abandonTolerance(profile)) {
    scores.abandon += 1 + clamp(state.frustration - abandonTolerance(profile)) * 4;
  }
  // JRN-2: the same control again, or two controls alternating, told apart from
  // a bigger version of whatever is already winning. `retry`/`continue`/
  // `impulsive_retry` are exactly the options that produced the loop in the
  // first place -- boosting `explore`/`backtrack` alone still let `reread`
  // (which does not touch what happens next) lead on a real run's own
  // recorded states at the point a loop first became visible, so this
  // suppresses the repeat-reinforcing three rather than only lifting their
  // replacements. `abandon` gets a smaller share of the same boost: a loop is
  // itself a reason to leave, not only a reason to try something else, and
  // without its own share here the flat lift to `explore`/`backtrack` diluted
  // it under softmax renormalisation exactly where JRN-1 had just made it
  // competitive -- measured on the same real run this profile's tolerance
  // check (0.78) is calibrated against: at frustration 1.00 with a real
  // alternation resolving into a third repeat of the same control,
  // unboosted p(abandon) 0.615 fell to 0.284 with only explore/backtrack
  // lifted, and holds at 0.617 with this smaller abandon share included.
  // Below tolerance the same run shows the boost doing the other job: at
  // frustration 0.55, two clicks into an A/B alternation and nowhere near
  // this profile's tolerance, reread led at 0.416 and abandon barely moved
  // (0.010 to 0.015) while explore took over at 0.412 -- a nudge toward
  // trying something else, not a push toward leaving before there is
  // reason to.
  const looping = Boolean(context.loopAlternating) || Number(context.loopRepeatCount || 0) > 0;
  if (looping) {
    scores.explore += 1.1;
    scores.backtrack += 1.1;
    scores.abandon += 0.7;
    scores.continue -= 0.8;
    scores.retry -= 0.8;
    scores.impulsive_retry -= 0.6;
  }
  return scores;
}

function probabilities(scores) {
  const entries = Object.entries(scores);
  const max = Math.max(...entries.map(([, score]) => score));
  const weights = entries.map(([type, score]) => [type, Math.exp((score - max) * 2)]);
  const total = weights.reduce((sum, [, weight]) => sum + weight, 0);
  return Object.fromEntries(weights.map(([type, weight]) => [type, Number((weight / total).toFixed(8))]));
}

function sampleCoping(profile, state, context, random) {
  const distribution = probabilities(copingScores(profile, state, context));
  let cursor = random();
  // If floating-point drift leaves the cursor above the sum of every probability,
  // the loop ends on the last entry anyway; this is only the value used when the
  // distribution is somehow empty. Getting on with it is the harmless default --
  // "retry" meant a malformed distribution silently repeated the last action.
  let selected = "continue";
  for (const [type, probability] of Object.entries(distribution)) {
    selected = type;
    cursor -= probability;
    if (cursor <= 0) break;
  }
  const decision = selected === "reread" || selected === "wait"
    ? { type: selected, durationMs: selected === "wait" ? computeWaitTolerance(profile, state, context).thresholdMs : 1500 }
    : selected === "impulsive_retry" ? { type: selected, repetitions: 2 + Math.floor(profile.impulsivity * 2) }
      : selected === "abandon" ? { type: selected, reason: "frustration and effort exceeded this profile's tolerance" } : { type: selected };
  return { decision, probabilities: distribution, policyVersion: COPING_POLICY_VERSION };
}

function normalizedProfile(profile) {
  const defaults = { seed: 1, patience: .5, persistence: .5, irritability: .5, angerReactivity: .5,
    angerRecovery: .5, impulsivity: .5, ambiguityTolerance: .5, failureTolerance: .5,
    repeatFailureTolerance: .5, selfEfficacy: .5, digitalConfidence: .5, helpSeeking: .5,
    exploration: .5, verificationTendency: .5, riskTolerance: .5 };
  return Object.fromEntries(Object.entries({ ...defaults, ...profile }).map(([key, value]) => [key, key === "seed" ? Number(value) || 1 : clamp(Number(value))]));
}

class BehaviorController {
  constructor(simulationProfile) {
    this.simulationProfile = simulationProfile;
    this.profile = normalizedProfile(simulationProfile.behavior);
    this.state = initialState();
    this.random = seededRandom(this.profile.seed);
  }

  apply(event, context = {}) {
    const before = this.state;
    this.state = reduceState(before, event, this.profile);
    // JRN-1: the tolerance check itself, and what it should do about it, now
    // live in copingScores -- where it can actually change the sampled
    // outcome, rather than here, where it only ever set a label the next
    // three lines threw away.
    const coping = sampleCoping(this.profile, this.state, context, this.random);
    this.state.abandoned = coping.decision.type === "abandon";
    this.state.copingMode = ({ retry: "persistent", reread: "cautious", wait: "cautious",
      seek_help: "help_seeking", impulsive_retry: "impulsive", abandon: "abandoning" })[coping.decision.type] || "normal";
    const waitTolerance = computeWaitTolerance(this.profile, this.state, { ...context, progressVisible: event.progressVisible });
    return { before, after: { ...this.state }, event, coping, waitTolerance, reducerVersion: STATE_REDUCER_VERSION };
  }
}

module.exports = { BehaviorController, initialState, reduceState, computeWaitTolerance, copingScores,
  abandonTolerance, probabilities, sampleCoping, seededRandom, STATE_REDUCER_VERSION, COPING_POLICY_VERSION,
  WAIT_TOLERANCE_VERSION };
