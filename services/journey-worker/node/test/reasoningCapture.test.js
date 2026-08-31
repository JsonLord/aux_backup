"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { startRunCapture, takeRunReasoning, parseStreamedReasoning,
  parseWholeBodyReasoning } = require("../src/reasoningCapture");

// The three field names pi-ai reads, in its own precedence order
// (@earendil-works/pi-ai dist/api/openai-completions.js).
const REASONING_FIELDS = ["reasoning_content", "reasoning", "reasoning_text"];

function sse(frames) {
  return frames.map((frame) => `data: ${JSON.stringify(frame)}`).join("\n\n") + "\n\ndata: [DONE]\n\n";
}

test("streamed reasoning deltas are reassembled into the model's whole thought", () => {
  const body = sse([
    { model: "auto", choices: [{ delta: { reasoning_content: "The header says " } }] },
    { choices: [{ delta: { reasoning_content: "'SyncUsers', which " } }] },
    { choices: [{ delta: { reasoning_content: "I do not recognise." } }] },
    { choices: [{ delta: { content: "Clicking the header." } }] },
  ]);

  assert.deepEqual(parseStreamedReasoning(body), {
    reasoning: "The header says 'SyncUsers', which I do not recognise.",
    model: "auto",
  });
});

test("every reasoning field an OpenAI-compatible endpoint may use is read", () => {
  for (const field of REASONING_FIELDS) {
    const streamed = parseStreamedReasoning(sse([{ choices: [{ delta: { [field]: "thought" } }] }]));
    assert.equal(streamed.reasoning, "thought", `streamed ${field}`);
    const whole = parseWholeBodyReasoning(JSON.stringify({ choices: [{ message: { [field]: "thought" } }] }));
    assert.equal(whole.reasoning, "thought", `non-streamed ${field}`);
  }
});

test("a response that carries no reasoning yields nothing rather than an empty thought", () => {
  assert.equal(parseStreamedReasoning(sse([{ choices: [{ delta: { content: "hi" } }] }])).reasoning, "");
  assert.equal(parseWholeBodyReasoning("not json").reasoning, "");
});

test("a partial SSE frame at a chunk boundary does not lose the frames around it", () => {
  const body = `data: ${JSON.stringify({ choices: [{ delta: { reasoning_content: "before " } }] })}\n\n`
    + 'data: {"choices":[{"delta":{"reasoning_con\n\n'
    + `data: ${JSON.stringify({ choices: [{ delta: { reasoning_content: "after" } }] })}\n\n`;
  assert.equal(parseStreamedReasoning(body).reasoning, "before after");
});

test("capturing never changes what the caller receives", async () => {
  const body = sse([{ choices: [{ delta: { reasoning_content: "Looking for the sign-in link." } }] }]);
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(body, { status: 200 });
  try {
    startRunCapture("run-1");
    const response = await globalThis.fetch("https://router.test/v1/chat/completions", { method: "POST" });
    assert.equal(await response.text(), body, "the caller must get the whole, untouched stream");
    await new Promise((resolve) => setTimeout(resolve, 50));
    const thoughts = takeRunReasoning("run-1");
    assert.equal(thoughts.length, 1);
    assert.equal(thoughts[0].text, "Looking for the sign-in link.");
    assert.ok(Number.isFinite(thoughts[0].elapsedMs));
  } finally {
    globalThis.fetch = original;
  }
});

test("only completion calls are inspected, and a finished run is not re-reported", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(
    sse([{ choices: [{ delta: { reasoning_content: "thought" } }] }]), { status: 200 });
  try {
    startRunCapture("run-2");
    await globalThis.fetch("https://router.test/v1/models");
    await new Promise((resolve) => setTimeout(resolve, 30));
    assert.deepEqual(takeRunReasoning("run-2"), [], "a non-completions URL contributes nothing");
    assert.deepEqual(takeRunReasoning("run-2"), [], "taking a run twice yields nothing the second time");
  } finally {
    globalThis.fetch = original;
  }
});
