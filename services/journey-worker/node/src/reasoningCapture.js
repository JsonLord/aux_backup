"use strict";
/**
 * Capture the director model's real reasoning tokens.
 *
 * journeytest-core records an assistant turn into the timeline as
 * `agent.message.end` with only the `text` content blocks kept
 * (dist/directors/pi/piSdkDirector.js filters `content.type === "text"`). A
 * reasoning model emits its actual thinking as separate `thinking` blocks, so
 * everything the model genuinely thought while driving the browser was dropped
 * before it ever reached the run artifacts -- the event keeps `contentTypes`,
 * which is how the loss is visible (12 `thinking` entries, no text), but not the
 * thinking itself.
 *
 * The report then had nothing but the agent's end-of-run verdict prose to quote,
 * which reads as generic UX commentary written after the fact ("...use technical
 * jargon that may not immediately convey what the product does") rather than the
 * model's live thought while it was looking at the page.
 *
 * pi-ai already parses this off the wire: its openai-completions API reads the
 * first non-empty of `reasoning_content` / `reasoning` / `reasoning_text` from
 * each streamed delta and accumulates it into a `thinking` block
 * (@earendil-works/pi-ai dist/api/openai-completions.js). This module reads the
 * same fields from the same responses, one layer lower, where nothing can
 * discard them: it wraps `fetch`, tees the response body so the real consumer is
 * untouched, and accumulates the reasoning per completion call.
 *
 * What is captured is the provider's own reasoning output for that request --
 * not a summary, not a re-ask, and not inferred from anything.
 */

const CHAT_COMPLETIONS = /\/(chat\/completions|responses)(\?|$)/;
const REASONING_FIELDS = ["reasoning_content", "reasoning", "reasoning_text"];

let installed = false;
/** runId -> { startedAt, thoughts: [{elapsedMs, text, model}] } */
const captures = new Map();
let activeRunId = null;

function firstReasoningDelta(payload) {
  for (const field of REASONING_FIELDS) {
    const value = payload?.[field];
    if (typeof value === "string" && value.length > 0) return value;
  }
  return "";
}

/**
 * Pull the reasoning out of one streamed chunk or one whole JSON body. Handles
 * both shapes because an OpenAI-compatible endpoint may or may not stream, and
 * the same fields carry reasoning either way (`delta` while streaming,
 * `message` when not).
 */
function reasoningFromChoice(choice) {
  if (!choice || typeof choice !== "object") return "";
  return firstReasoningDelta(choice.delta) || firstReasoningDelta(choice.message) || "";
}

function parseStreamedReasoning(body) {
  let reasoning = "";
  let model = "";
  for (const line of body.split("\n")) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("data:")) continue;
    const data = trimmed.slice(5).trim();
    if (!data || data === "[DONE]") continue;
    let parsed;
    try {
      parsed = JSON.parse(data);
    } catch {
      continue; // a partial frame at a chunk boundary; the next read completes it
    }
    if (parsed.model && !model) model = String(parsed.model);
    for (const choice of parsed.choices || []) reasoning += reasoningFromChoice(choice);
  }
  return { reasoning, model };
}

function parseWholeBodyReasoning(body) {
  let parsed;
  try {
    parsed = JSON.parse(body);
  } catch {
    return { reasoning: "", model: "" };
  }
  let reasoning = "";
  for (const choice of parsed.choices || []) reasoning += reasoningFromChoice(choice);
  return { reasoning, model: parsed.model ? String(parsed.model) : "" };
}

function record(runId, startedAt, text, model) {
  const capture = captures.get(runId);
  if (!capture || !text.trim()) return;
  capture.thoughts.push({
    elapsedMs: Math.max(0, startedAt - capture.startedAt),
    text: text.trim(),
    ...(model ? { model } : {}),
  });
}

async function drain(stream, runId, startedAt) {
  // Read the mirrored half of the tee to completion. Failures here must never
  // affect the run: this is observation, not part of the journey.
  try {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let body = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      body += decoder.decode(value, { stream: true });
    }
    body += decoder.decode();
    const streamed = body.includes("data:");
    const { reasoning, model } = streamed ? parseStreamedReasoning(body) : parseWholeBodyReasoning(body);
    record(runId, startedAt, reasoning, model);
  } catch {
    /* observation only */
  }
}

/**
 * Wrap `fetch` once for the life of the process. Idempotent, so repeated calls
 * (one per run) do not stack wrappers.
 */
function installReasoningCapture() {
  if (installed) return;
  const original = globalThis.fetch;
  if (typeof original !== "function") return;
  installed = true;
  globalThis.fetch = async function capturingFetch(input, init) {
    const response = await original.call(this, input, init);
    const runId = activeRunId;
    if (!runId || !captures.has(runId)) return response;
    const url = typeof input === "string" ? input : input?.url || "";
    if (!CHAT_COMPLETIONS.test(url) || !response.ok || !response.body) return response;
    // tee() rather than clone(): the caller keeps a stream it can consume at its
    // own pace, and reading our copy never blocks or buffers theirs.
    const [forCaller, forCapture] = response.body.tee();
    void drain(forCapture, runId, Date.now());
    return new Response(forCaller, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers,
    });
  };
}

function startRunCapture(runId) {
  installReasoningCapture();
  captures.set(runId, { startedAt: Date.now(), thoughts: [] });
  activeRunId = runId;
}

/** The reasoning captured for a run, in the order the model produced it. */
function takeRunReasoning(runId) {
  const capture = captures.get(runId);
  captures.delete(runId);
  if (activeRunId === runId) activeRunId = null;
  if (!capture) return [];
  return capture.thoughts.sort((left, right) => left.elapsedMs - right.elapsedMs);
}

module.exports = {
  installReasoningCapture,
  startRunCapture,
  takeRunReasoning,
  parseStreamedReasoning,
  parseWholeBodyReasoning,
};
