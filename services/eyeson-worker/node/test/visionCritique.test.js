"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { critiqueScreenshot, buildPrompt, parseFindings } = require("../src/visionCritique");

test("buildPrompt includes the real element list so findings can reference actual selectors", () => {
  const { user } = buildPrompt({
    url: "https://example.com", task: "Find pricing",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy now", boundingBox: { x: 10, y: 20, width: 80, height: 30 } }],
  });
  assert.match(user, /#buy-button/);
  assert.match(user, /Buy now/);
  assert.match(user, /Find pricing/);
});

test("parseFindings tolerates a markdown-fenced JSON array and rejects malformed entries", () => {
  const content = "```json\n"
    + '[{"category":"accessibility","severity":"high","elementSelector":"#buy-button","title":"Low contrast","description":"Text fails WCAG AA contrast.","recommendation":"Darken the text color."},'
    + '{"category":"nonsense","severity":"unknown"}]'
    + "\n```";
  const findings = parseFindings(content);
  assert.equal(findings.length, 1); // second entry has no title/description, dropped
  assert.equal(findings[0].elementSelector, "#buy-button");
  assert.equal(findings[0].category, "accessibility");
  assert.equal(findings[0].severity, "high");
});

test("critiqueScreenshot matches a finding's elementSelector to the real element's boundingBox and grounds it", async (t) => {
  t.mock.method(global, "fetch", async () => ({
    ok: true,
    json: async () => ({ choices: [{ message: { content: JSON.stringify([
      { category: "accessibility", severity: "medium", elementSelector: "#buy-button",
        title: "Ambiguous button label", description: "The button text does not describe the action clearly.",
        recommendation: "Use a more specific label like 'Complete purchase'." },
    ]) } }] }),
  }));

  const findings = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item",
    elements: [{ selector: "#buy-button", role: "button", text: "Buy", boundingBox: { x: 10, y: 20, width: 80, height: 30 } }],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto" },
  });

  assert.equal(findings.length, 1);
  assert.deepEqual(findings[0].box, { x: 10, y: 20, width: 80, height: 30 });
  assert.ok(findings[0].grounding);
  assert.equal(global.fetch.mock.callCount(), 1);
  const [calledUrl, calledInit] = global.fetch.mock.calls[0].arguments;
  assert.equal(calledUrl, "https://router.invalid/v1/chat/completions");
  const sentBody = JSON.parse(calledInit.body);
  assert.equal(sentBody.messages[1].content[1].image_url.url, "data:image/png;base64,Zm9v");
});

test("critiqueScreenshot retries once on a transient failure then succeeds", async (t) => {
  let calls = 0;
  t.mock.method(global, "fetch", async () => {
    calls += 1;
    if (calls === 1) throw new Error("ECONNRESET");
    return { ok: true, json: async () => ({ choices: [{ message: { content: "[]" } }] }) };
  });
  const findings = await critiqueScreenshot({
    imageBase64: "Zm9v", url: "https://example.com", task: "Buy an item", elements: [],
    options: { apiKey: "test-key", baseUrl: "https://router.invalid/v1", model: "auto", retryWaitMs: 1 },
  });
  assert.deepEqual(findings, []);
  assert.equal(calls, 2);
});

test("critiqueScreenshot requires credentials rather than silently returning fake findings", async () => {
  const originalKey = process.env.OPENAI_API_KEY;
  const originalBlablador = process.env.BLABLADOR_API_KEY;
  delete process.env.OPENAI_API_KEY;
  delete process.env.BLABLADOR_API_KEY;
  try {
    await assert.rejects(
      critiqueScreenshot({ imageBase64: "Zm9v", url: "https://example.com", task: "t", elements: [], options: { baseUrl: "https://router.invalid/v1" } }),
      /OPENAI_API_KEY/,
    );
  } finally {
    if (originalKey !== undefined) process.env.OPENAI_API_KEY = originalKey;
    if (originalBlablador !== undefined) process.env.BLABLADOR_API_KEY = originalBlablador;
  }
});
