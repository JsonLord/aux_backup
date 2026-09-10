"use strict";
/**
 * Perception is the layer that decides what a persona knows about a page, so the
 * failures worth pinning are the ones where it quietly stops mattering: a
 * service that is down and silently returns the whole tree again, a ref that is
 * dropped so nothing can be clicked, a walk whose boxes belong to a different
 * moment than the pixels.
 */
const test = require("node:test");
const assert = require("node:assert/strict");

const {
  PerceptionClient, batchResults, linkRefs, lookAtPage, motionFramesFrom,
} = require("../src/perception");

/** agent-browser's batch envelope, as `batch --json` really returns it. */
function envelope({ refs = {}, walked = {}, snapshot = "- heading \"Hi\" [ref=e1]" } = {}) {
  return {
    ok: true,
    stdout: JSON.stringify([
      { command: ["snapshot"], error: null, success: true,
        result: { refs, snapshot, origin: "https://example.test/" } },
      { command: ["eval"], error: null, success: true, result: { result: JSON.stringify(walked) } },
      { command: ["screenshot"], error: null, success: true, result: {} },
    ]),
  };
}

test("a ref survives the walk, because an element nobody can name cannot be clicked", () => {
  const walked = [
    { kind: "control", tag: "button", role: "", name: "Get started", x: 100, y: 277, width: 240, height: 60 },
    { kind: "text", tag: "p", role: "", name: "Small print about pricing", x: 100, y: 138, width: 520, height: 19 },
  ];
  const linked = linkRefs(walked, { e2: { name: "Get started", role: "button" } });

  assert.equal(linked[0].selector, "e2");
  assert.equal(linked[0].role, "button", "the tree's role wins over the tag: it is what gets announced");
  assert.equal(linked[0].actionable, true);

  // A paragraph gets no ref from agent-browser, and low-contrast body copy is the
  // single most common thing a person cannot read -- so it has to be a candidate
  // anyway, marked as something they can read but not click.
  assert.equal(linked[1].actionable, false);
  assert.match(linked[1].selector, /^p@/);
});

test("one ref is claimed once, so two buttons with the same label are not the same button", () => {
  const walked = [
    { tag: "button", name: "Buy", x: 0, y: 0, width: 80, height: 30 },
    { tag: "button", name: "Buy", x: 0, y: 400, width: 80, height: 30 },
  ];
  const linked = linkRefs(walked, { e1: { name: "Buy", role: "button" }, e2: { name: "Buy", role: "button" } });
  assert.notEqual(linked[0].selector, linked[1].selector);
});

test("a walk and a capture come back from a single batch", async () => {
  let commands;
  const runner = async (sent) => { commands = sent; return envelope({
    refs: { e1: { name: "Hi", role: "heading" } },
    walked: { viewport: { width: 1280, height: 900 }, scrollY: 0,
      elements: [{ tag: "h1", name: "Hi", x: 10, y: 10, width: 100, height: 40 }] },
  }); };

  const page = await lookAtPage(runner, { capture: false });
  assert.deepEqual(commands.map((item) => item[0]), ["snapshot", "eval"]);
  assert.equal(page.elements.length, 1);
  assert.equal(page.elements[0].selector, "e1");
  assert.deepEqual(page.viewport, { width: 1280, height: 900 });
});

test("a batch that fails leaves the caller with nothing rather than half a page", async () => {
  const page = await lookAtPage(async () => ({ ok: false, stderr: "browser is gone" }), { capture: false });
  assert.deepEqual(page.elements, []);
  assert.equal(page.screenshotBase64, "");
});

test("output that is not the envelope we expect is not allowed to throw", () => {
  assert.deepEqual(batchResults("not json at all"), []);
  assert.deepEqual(batchResults(JSON.stringify({ error: "nope" })), []);
});

test("frames arrive as bare base64, with or without a data-url wrapper", () => {
  assert.deepEqual(
    motionFramesFrom([{ data: "data:image/png;base64,AAA" }, { data: "BBB" }, { data: "" }, null]),
    ["AAA", "BBB"]);
});

test("the service being down costs the run nothing, and is not asked twice", async () => {
  let calls = 0;
  const client = new PerceptionClient({
    endpoint: "http://perception.test",
    fetch: async () => { calls += 1; throw new Error("connection refused"); },
  });
  const args = { screenshotBase64: "AAA", elements: [{ selector: "e1", box: {} }] };

  assert.equal(await client.perceive(args), null);
  assert.equal(client.available, false, "one refusal is enough: it will not be there next step either");
  assert.equal(await client.perceive(args), null);
  assert.equal(calls, 1, "forty timeouts would cost a run thirteen minutes");
});

test("an unconfigured endpoint means perception is simply off", async () => {
  const client = new PerceptionClient({ endpoint: "" });
  assert.equal(client.available, false);
  assert.equal(await client.perceive({ screenshotBase64: "A", elements: [{}] }), null);
});

test("an HTTP error is a failure, not a body to believe", async () => {
  const client = new PerceptionClient({
    endpoint: "http://perception.test",
    fetch: async () => ({ ok: false, status: 500, json: async () => ({ observation: "lies" }) }),
  });
  assert.equal(await client.perceive({ screenshotBase64: "A", elements: [{ selector: "e1" }] }), null);
  assert.match(client.lastError, /HTTP 500/);
});
