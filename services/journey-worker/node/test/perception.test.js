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
  PerceptionClient, batchResults, linkRefs, lookAtPage, motionFramesFrom, scrollNumber,
  scrollValue,
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

/**
 * A batch whose eval read-back says where the page ended up. The real envelope
 * puts the eval's value under a nested `result`; `after` of undefined omits the
 * read-back entirely, which is what a build that does not answer looks like.
 */
function capturedAt(scrollBefore, after) {
  const results = [
    { command: ["snapshot"], error: null, success: true,
      result: { refs: { e1: { name: "Home", role: "link" } }, snapshot: "- link \"Home\" [ref=e1]" } },
    { command: ["eval"], error: null, success: true,
      result: { result: JSON.stringify({ viewport: { width: 1280, height: 577 }, scrollY: scrollBefore,
        elements: [{ kind: "control", tag: "a", role: "", name: "Home", x: 483, y: 20,
          width: 43, height: 24, fontPx: 15, fontWeight: 400 }] }) } },
    { command: ["screenshot"], error: null, success: true, result: {} },
  ];
  if (after !== undefined) {
    results.push({ command: ["eval"], error: null, success: true, result: { result: after } });
  }
  return { ok: true, stdout: JSON.stringify(results) };
}

// Every box the walk reports is in viewport coordinates. A scroll between the
// walk and the screenshot leaves the boxes describing where things were and the
// pixels showing where the page is now, and every crop then lands on whatever
// happens to sit at that offset. A live run reported the entire navigation bar as
// failing WCAG AA at 1:1 -- "the region and everything around it are the same
// flat colour" -- for a persona with 0.95 acuity and 0.92 contrast sensitivity,
// because the crops had landed on blank page. The scroller was the reveal keeper,
// firing every 1500ms through a pass that takes longer than that.
test("a capture taken while the page moved is marked, not measured", async () => {
  const seen = await lookAtPage(async () => capturedAt(0, "2400"));

  assert.equal(seen.moved, true);
  assert.equal(seen.scrollCheck, "moved");
  assert.equal(seen.scrolledTo, 2400);
  // The pixels and the boxes are still returned -- the caller decides what to do
  // with a capture it cannot trust, and this one has them fall back to the tree.
  assert.equal(seen.elements.length, 1);
});

test("a capture taken on a still page is cleared to measure", async () => {
  const seen = await lookAtPage(async () => capturedAt(2400, "2400"));

  assert.equal(seen.moved, false);
  assert.equal(seen.scrollCheck, "same");
  assert.equal(seen.scrolledTo, 2400);
});

test("a read-back that cannot be parsed loses the guard, not the feature", async () => {
  // The hold on the reveal keeper is the fix; this read-back is corroboration.
  // Treating an unparseable answer as "moved" would let one unexpected envelope
  // shape switch perception off for a whole run -- a worse failure than the one
  // being guarded against, and a far quieter one.
  for (const answer of [undefined, "", "not a number", "{}"]) {
    const seen = await lookAtPage(async () => capturedAt(0, answer));
    assert.equal(seen.moved, false, `answer ${JSON.stringify(answer)} must not block the capture`);
    assert.equal(seen.scrollCheck, "unavailable");
    assert.equal(seen.scrolledTo, null);
  }
});

test("the scroll read-back is asked for in the same batch as the capture", async () => {
  let asked = null;
  await lookAtPage(async (commands) => { asked = commands; return capturedAt(0, "0"); });

  assert.deepEqual(asked.map((item) => item[0]), ["snapshot", "eval", "screenshot", "eval"]);
  // After the screenshot, or it answers a question nobody asked.
  assert.ok(asked.findIndex((item) => item[0] === "screenshot")
    < asked.length - 1, "the read-back must come after the capture");
});

test("the scroll read-back survives the envelope layers agent-browser adds", () => {
  assert.equal(scrollValue("2400"), "2400");
  assert.equal(scrollValue({ result: "2400" }), "2400");
  assert.equal(scrollValue({ result: { result: " 2400 " } }), "2400");
  assert.equal(scrollValue(undefined), undefined);
});

test("a read-back of nothing is not a read-back of zero", () => {
  // Number("") is 0, so an empty answer used to match a page at the top and
  // report itself as a guard that had run and passed.
  for (const blank of ["", "   ", "{}", "undefined", null, undefined, {}]) {
    assert.ok(Number.isNaN(scrollNumber(blank)), `${JSON.stringify(blank)} is not a position`);
  }
  assert.equal(scrollNumber("0"), 0);
  assert.equal(scrollNumber(" 2400 "), 2400);
  assert.equal(scrollNumber("-12"), -12);
  assert.equal(scrollNumber(2400), 2400);
});
