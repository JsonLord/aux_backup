"use strict";
/**
 * Who decides what the persona does next.
 *
 * The point of the separation is the vocabulary. A tool-calling agent thinks in
 * `browser_snapshot` and `browser_scroll`; a person thinks "I want to know what
 * this costs" and then does something. So an actor returns an ACTION -- READ,
 * CLICK, SCROLL, TYPE, GO_BACK, GIVE_UP, DONE -- and the director translates it
 * into driver calls. A live run's own thought log showed why this matters: twelve
 * captured thoughts, every one of them narrating plumbing ("Now take snapshot.",
 * "The tool name is browser_scroll not browser_scroll. Let's correct."), and not
 * one of them in the voice of the impatient architect the run was supposed to be.
 *
 * Two actors implement the same call:
 *
 *   - `llmActor` asks a model, in the persona's own terms, with the persona's
 *     current affective state as context. Stage 1.
 *   - `scriptedActor` replays a fixed list. It is what lets the director's loop,
 *     its coping behaviour and its verdicts be tested without a network.
 *
 * A TinyTroupe agent drops in here later behind the same signature, which is why
 * the return shape is already TinyTroupe's: reasoning, an action, and a cognitive
 * state of goals/attention/emotions.
 */

const ACTION_TYPES = ["READ", "CLICK", "SCROLL", "TYPE", "GO_BACK", "GIVE_UP", "DONE"];

/**
 * How well what happened matched what the persona expected, and what that is
 * worth in the terms behavior.js reduces over.
 *
 * Expectation violation is the thing that actually moves people. "I clicked
 * Pricing and got a contact form" is a worse experience than "I clicked Pricing
 * and nothing happened", and mechanically they look identical -- both are a
 * successful click that changed the page. Only the gap between what was expected
 * and what arrived can tell them apart, which is why the persona is made to
 * commit to an expectation before acting.
 */
const MATCH_OUTCOMES = {
  yes: { type: "success", severity: 0, recoveryQuality: 0.7 },
  partly: { type: "ambiguous_feedback", severity: 0.4, attribution: { interface: 0.7 } },
  no: { type: "ambiguous_feedback", severity: 0.7, goalBlocked: true,
    attribution: { interface: 0.8, software: 0.2 } },
};

const ACTION_VOCABULARY = `
READ     - look at something without touching it. target: what you are reading.
CLICK    - click a control. target: its ref from the page list, e.g. "e12".
SCROLL   - move the page. content: "down" or "up". target: optional pixel amount.
TYPE     - type into a field. target: its ref. content: what you type.
GO_BACK  - go back to the previous page.
GIVE_UP  - stop, because this is not worth any more of your time. content: why.
DONE     - stop, because you have what you came for. content: what you concluded.
`.trim();

/**
 * How the persona feels, in words a person would use.
 *
 * The behaviour model keeps frustration, confusion, trust and fatigue as numbers.
 * Handing "frustration: 0.62" to a model invites it to write about the number.
 * Handing it "you are getting properly annoyed" invites it to act.
 */
function affectInWords(state) {
  const bands = (value, low, mid, high, top) => {
    if (value >= 0.75) return top;
    if (value >= 0.5) return high;
    if (value >= 0.25) return mid;
    return low;
  };
  const parts = [
    bands(state.frustration, "You are calm.", "Something is starting to niggle.",
      "You are getting properly annoyed.", "You are fed up."),
    bands(state.confusion, "", "You are not entirely sure where things are.",
      "You are confused about how this works.", "You have lost the thread completely."),
    bands(1 - state.trust, "", "", "You are starting to doubt this site.",
      "You do not trust this site."),
    bands(state.fatigue, "", "", "You are tiring of this.", "You are worn out."),
  ];
  return parts.filter(Boolean).join(" ");
}

/** The persona as a person, not as a parameter vector. */
function personaInWords(profile) {
  const persona = profile.persona || {};
  const behavior = profile.behavior || {};
  const traits = [];
  if (behavior.patience <= 0.35) traits.push("You have very little patience.");
  if (behavior.patience >= 0.7) traits.push("You are patient.");
  if (behavior.irritability >= 0.65) traits.push("You are easily irritated.");
  if (behavior.exploration >= 0.65) traits.push("You like poking around a site.");
  if (behavior.exploration <= 0.35) traits.push("You do not wander; you go for what you came for.");
  if (behavior.verificationTendency >= 0.65) traits.push("You double-check things before believing them.");
  if (behavior.digitalConfidence <= 0.35) traits.push("You are not confident with unfamiliar interfaces.");
  if (behavior.persistence >= 0.7) traits.push("You keep at something once you have started.");
  if (behavior.persistence <= 0.3) traits.push("You give up on things quickly.");
  const lines = [
    `You are ${persona.name || profile.id || "a visitor"}${persona.occupation ? `, ${persona.occupation}` : ""}.`,
    ...traits,
  ];
  if (Array.isArray(persona.goals) && persona.goals.length) {
    lines.push(`What you care about: ${persona.goals.join("; ")}.`);
  }
  if (Array.isArray(persona.constraints) && persona.constraints.length) {
    lines.push(`What puts you off: ${persona.constraints.join("; ")}.`);
  }
  return lines.join("\n");
}

function buildPrompt({ profile, tasks, observation, affect, history }) {
  const system = [
    personaInWords(profile),
    "",
    "You are looking at a website. Answer as yourself, in the first person. Never mention",
    "tools, snapshots, refs or automation; those are how your actions reach the page, not",
    "how you think about them.",
    "",
    "Say three things, in order:",
    "  1. what you can see -- just what is there, plainly",
    "  2. what you expect will happen, specifically, if you do the thing you are about to do",
    "  3. the one action you are taking",
    "",
    "Be specific about the expectation: name what you think you will get. You will be",
    "shown afterwards what actually happened, and a vague expectation cannot be wrong.",
    "",
    "Do NOT describe how you feel. Your feelings are not yours to report here; they",
    "follow from what happens next.",
    "",
    "Choose ONE action:",
    ACTION_VOCABULARY,
    "",
    'Reply as JSON only: {"visible": "...", "expectation": "...",',
    '"action": {"type": "...", "target": "...", "content": "..."}}',
  ].join("\n");

  const user = [
    `What you are here to do: ${tasks.join(" Then: ")}`,
    "",
    affect ? `How you feel right now: ${affect}` : "",
    "",
    history.length ? `What you have done so far:\n${history.map((item) => `- ${item}`).join("\n")}` : "You have just arrived.",
    "",
    "What is in front of you:",
    observation,
  ].filter((part) => part !== "").join("\n");

  return { system, user };
}

/** Pull the first JSON object out of a completion, however the model wrapped it. */
function parseDecision(content) {
  let text = String(content || "").trim();
  if (text.startsWith("```")) {
    text = text.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n?```\s*$/, "").trim();
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) return null;
    try {
      parsed = JSON.parse(match[0]);
    } catch {
      return null;
    }
  }
  const action = parsed?.action || {};
  const type = String(action.type || "").toUpperCase().trim();
  if (!ACTION_TYPES.includes(type)) return null;
  return {
    visible: String(parsed.visible || "").trim(),
    expectation: String(parsed.expectation || "").trim(),
    action: { type, target: String(action.target ?? "").trim(), content: String(action.content ?? "").trim() },
  };
}

/**
 * What the persona makes of what just happened.
 *
 * Deliberately a separate, factual question. Asked in the same breath as "what
 * next", a model narrates its feelings and then acts them out, which is
 * self-fulfilling and unfalsifiable. Asked on its own -- you expected this, you
 * got that, did it match -- the answer is checkable, and the feeling is derived
 * from it rather than declared.
 */
function parseReflection(content) {
  let text = String(content || "").trim();
  if (text.startsWith("```")) {
    text = text.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n?```\s*$/, "").trim();
  }
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) return null;
    try {
      parsed = JSON.parse(match[0]);
    } catch {
      return null;
    }
  }
  const matched = String(parsed?.matched || "").toLowerCase().trim();
  if (!Object.hasOwn(MATCH_OUTCOMES, matched)) return null;
  return {
    observed: String(parsed.observed || "").trim(),
    matched,
    gap: String(parsed.gap || "").trim(),
  };
}

function buildReflectionPrompt({ profile, expectation, action, observation }) {
  const system = [
    personaInWords(profile),
    "",
    "You just did something on a website. Compare what you expected with what you got.",
    "Answer factually -- what is there, and whether it is what you were expecting. Do not",
    "say how you feel about it.",
    "",
    'Reply as JSON only: {"observed": "...", "matched": "yes" | "partly" | "no", "gap": "..."}',
    '"matched" is about your expectation, not about whether the click worked:',
    '  yes    - you got what you expected',
    '  partly - you got something related, but not what you were after',
    '  no     - this is not what you expected at all, or nothing happened',
    '"gap" is what was different, in one sentence. Empty if it matched.',
  ].join("\n");

  const user = [
    `What you did: ${action.type}${action.target ? ` ${action.target}` : ""}`
      + `${action.content ? ` (${action.content})` : ""}`,
    `What you expected: ${expectation || "(you did not say)"}`,
    "",
    "What is in front of you now:",
    observation,
  ].join("\n");

  return { system, user };
}

async function completion({ system, user, model, apiKey, baseUrl, timeoutMs = 120000 }) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${String(baseUrl).replace(/\/$/, "")}/chat/completions`, {
      method: "POST", signal: controller.signal,
      headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
      body: JSON.stringify({ model, temperature: 0.7, max_tokens: 800,
        messages: [{ role: "system", content: system }, { role: "user", content: user }] }),
    });
    if (!response.ok) {
      throw new Error(`persona actor endpoint returned HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
    }
    const data = await response.json();
    return data.choices?.[0]?.message?.content || "";
  } finally {
    clearTimeout(timer);
  }
}

/**
 * An actor backed by a model.
 *
 * A reply that is not a usable action is retried once with the failure named,
 * because a malformed answer is the model's mistake and not the persona's --
 * and then, rather than stalling, it becomes a READ, which is the one action
 * that changes nothing.
 */
/**
 * An actor backed by a model, with a second, smaller one for reflection.
 *
 * Deciding is where the persona's voice lives and is worth the better model.
 * Reflecting is a factual comparison -- you expected this, you got that, did it
 * match -- which a cheap fast model does as well and answers in a fraction of the
 * time. Since reflection happens on every acting turn, that halves what the cycle
 * costs. JOURNEY_REFLECT_MODEL picks it; unset, reflection uses the acting model,
 * because a model id only means something against the endpoint it is served from.
 */
function llmActor({ model, reflectModel, apiKey, baseUrl, complete = completion, attempts = 2 } = {}) {
  const judge = reflectModel || model;
  async function decide(input) {
    const { system, user } = buildPrompt(input);
    let lastText = "";
    for (let attempt = 0; attempt < attempts; attempt += 1) {
      const ask = attempt === 0 ? user
        : `${user}\n\nYour last reply could not be read as one of the listed actions. Reply with JSON only.`;
      lastText = await complete({ system, user: ask, model, apiKey, baseUrl });
      const decision = parseDecision(lastText);
      if (decision) return decision;
    }
    return { visible: "", expectation: "", malformed: true,
      action: { type: "READ", target: "", content: "" }, raw: String(lastText).slice(0, 400) };
  }

  decide.reflect = async function reflect(input) {
    const { system, user } = buildReflectionPrompt(input);
    const text = await complete({ system, user, model: judge, apiKey, baseUrl });
    // An unreadable reflection must not invent a violation: "partly" would say
    // the page disappointed someone on no evidence at all.
    return parseReflection(text) || { observed: "", matched: "yes", gap: "", malformed: true };
  };
  decide.reflectModel = judge;
  return decide;
}

/** An actor that replays a fixed list -- the director's loop under test. */
function scriptedActor(script) {
  let index = 0;
  function decide() {
    const step = script[Math.min(index, script.length - 1)];
    index += 1;
    return Promise.resolve({
      visible: step.visible || "", expectation: step.expectation || "",
      action: { type: step.type, target: step.target || "", content: step.content || "" },
    });
  }
  decide.reflect = ({ expectation } = {}) => {
    const step = script[Math.min(Math.max(index - 1, 0), script.length - 1)];
    return Promise.resolve({ observed: step.observed || "", matched: step.matched || "yes",
      gap: step.gap || "", expectation });
  };
  return decide;
}

module.exports = { ACTION_TYPES, ACTION_VOCABULARY, MATCH_OUTCOMES, affectInWords, buildPrompt,
  buildReflectionPrompt, completion, llmActor, parseDecision, parseReflection, personaInWords,
  scriptedActor };
