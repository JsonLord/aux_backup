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
  PerceptionClient, WALK, batchResults, intoCaptureSpace, linkRefs, lookAtPage, motionFramesFrom,
  scrollNumber,
  scrollValue,
  pageStanding} = require("../src/perception");

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
 * The batch as it really comes back, in order.
 *
 * snapshot, the walk, the shift that brings the viewport into the rows the camera
 * photographs, the picture, the shift undone, the scroll read-back, and what the
 * DOM says is under the pixels. Written out rather than counted, because these
 * are read by position and a fixture that models three of seven will pass a test
 * that the real thing fails.
 */
function wholeBatch({ scrollBefore = 0, after, frame, shifted = "0", beneath } = {}) {
  const evaluation = (value) => ({ command: ["eval"], error: null, success: true,
    result: { result: value } });
  return { ok: true, stdout: JSON.stringify([
    { command: ["snapshot"], error: null, success: true,
      result: { refs: { e1: { name: "Home", role: "link" } }, snapshot: "- link \"Home\" [ref=e1]" } },
    evaluation(JSON.stringify({ frame, viewport: { width: 1280, height: 577 }, scrollY: scrollBefore,
      elements: [{ kind: "control", tag: "a", role: "", name: "Home", x: 483, y: 20,
        width: 43, height: 24, fontPx: 15, fontWeight: 400 }] })),
    evaluation(shifted),
    { command: ["screenshot"], error: null, success: true, result: {} },
    evaluation("restored"),
    evaluation(after),
    evaluation(beneath === undefined ? undefined : beneath),
  ]) };
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
  const seen = await lookAtPage(async () => wholeBatch({ scrollBefore: 0, after: "2400" }));

  assert.equal(seen.moved, true);
  assert.equal(seen.scrollCheck, "moved");
  assert.equal(seen.scrolledTo, 2400);
  // The pixels and the boxes are still returned -- the caller decides what to do
  // with a capture it cannot trust, and this one has them fall back to the tree.
  assert.equal(seen.elements.length, 1);
});

test("a capture taken on a still page is cleared to measure", async () => {
  const seen = await lookAtPage(async () => wholeBatch({ scrollBefore: 2400, after: "2400" }));

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
    const seen = await lookAtPage(async () => wholeBatch({ after: answer }));
    assert.equal(seen.moved, false, `answer ${JSON.stringify(answer)} must not block the capture`);
    assert.equal(seen.scrollCheck, "unavailable");
    assert.equal(seen.scrolledTo, null);
  }
});

test("the scroll read-back is asked for in the same batch as the capture", async () => {
  let asked = null;
  await lookAtPage(async (commands) => { asked = commands; return wholeBatch({ after: "0" }); });

  // The scroll read-back and the probe for what the DOM says is under the pixels
  // both follow the capture, in the same batch: a question asked afterwards is a
  // question about a different moment of the page.
  assert.deepEqual(asked.map((item) => item[0]),
    ["snapshot", "eval", "eval", "screenshot", "eval", "eval", "eval"]);
  // The shift that brings the viewport into the rows the camera photographs is
  // put back in the same batch, before anything else can see the page moved.
  const shot = asked.findIndex((item) => item[0] === "screenshot");
  assert.match(String(asked[shot - 1][1]), /translateY/, "shifted just before the picture");
  assert.match(String(asked[shot + 1][1]), /data-aux-was/, "and put back just after it");
  assert.ok(shot < asked.length - 1, "the read-back must come after the capture");
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

test("the read-back says where the page stood, and still answers the old question", () => {
  // A renderer that painted nothing and a viewport parked past the end of the
  // document produce the same blank pixels and want different fixes. Cycle 31
  // rejected 22 captures for having no ink in them and could say which.
  const parked = pageStanding('{"y":9000,"h":900,"doc":4000,"painted":true}');
  assert.equal(parked.y, 9000);
  assert.equal(parked.pastTheEnd, true, "below its own document: the page is fine, the capture is of nothing");
  assert.equal(parked.painted, true);

  const inside = pageStanding('{"y":200,"h":900,"doc":4000,"painted":true}');
  assert.equal(inside.pastTheEnd, false);

  const unpainted = pageStanding('{"y":0,"h":900,"doc":0,"painted":false}');
  assert.equal(unpainted.painted, false, "nothing laid out at all is the other bug");

  // The scroll-stability guard predates these fields and must not depend on
  // them: a bare number is still a complete answer.
  assert.deepEqual(pageStanding("1200"), { y: 1200, known: true });
  // And an unreadable read-back stays unknown rather than passing as "at the top",
  // which is the distinction the guard exists for.
  for (const bad of ["", "  ", "{oops", "null", undefined]) {
    assert.equal(pageStanding(bad).known, false, `"${bad}" must not read as a position`);
  }
});

test("a page still building itself is not photographed as if it were finished", async () => {
  // Cycle 32 refused 31 captures for having no ink in them, and the standing
  // said why: the document measured 1465px where the same page elsewhere
  // measures 8620px. Nothing was parked past the end and the body had laid out
  // -- the picture was taken while the page was still building, so the tree
  // already listed elements that had not been painted yet.
  const walkResult = (documentHeight) => JSON.stringify({
    viewport: { width: 1280, height: 900 }, scrollY: 112, documentHeight,
    elements: [{ selector: "e1", role: "link", name: "Pricing",
                 box: { x: 0, y: 0, width: 60, height: 20 } }] });

  const runner = (docAtWalk, docAfter) => async () => ({
    ok: true,
    stdout: JSON.stringify([
      { command: ["snapshot"], result: { snapshot: "", refs: {} } },
      { command: ["eval"], result: walkResult(docAtWalk) },
      { command: ["eval"], result: "112" },
      { command: ["screenshot"], result: {} },
      { command: ["eval"], result: "restored" },
      { command: ["eval"], result: JSON.stringify({ y: 112, h: 900, doc: docAfter, painted: true }) },
    ]) });

  const stillArriving = await lookAtPage(runner(1465, 8620));
  assert.equal(stillArriving.layoutCheck, "growing");
  assert.equal(stillArriving.moved, true, "the boxes and the pixels are of different pages");
  assert.ok(stillArriving.grewBy > 7000);

  const settled = await lookAtPage(runner(8620, 8620));
  assert.equal(settled.layoutCheck, "settled");
  assert.equal(settled.moved, false);

  // A lazy image settling, or a scrollbar appearing, is not a page arriving.
  const nudged = await lookAtPage(runner(8620, 8648));
  assert.equal(nudged.layoutCheck, "settled");
  assert.equal(nudged.moved, false);

  // A walk with no picture has no second read to compare against, and says so
  // rather than reporting a guard it could not run as one that passed.
  const noPicture = await lookAtPage(runner(1465, 8620), { capture: false });
  assert.equal(noPicture.layoutCheck, "skipped");
});

test("past-the-end is measured against the furthest the page can scroll", () => {
  // Against the document height it can never fire: a 1465px page in a 900px
  // window stops scrolling at 565, and cycle 33 photographed blank space at
  // 800, 867 and 712 while this check reported everything in order.
  const at = (y, h, doc) => pageStanding(JSON.stringify({ y, h, doc, painted: true })).pastTheEnd;

  assert.equal(at(800, 900, 1465), true, "235px below the last pixel of the document");
  assert.equal(at(867, 900, 1444), true);
  assert.equal(at(712, 900, 1444), true);

  assert.equal(at(112, 900, 1465), false, "inside the page");
  assert.equal(at(565, 900, 1465), false, "exactly at the bottom is still the page");
  assert.equal(at(1560, 900, 8620), false, "a tall page scrolled a long way is fine");
  assert.equal(at(0, 900, 400), false, "a page shorter than the window does not scroll at all");
  // Rounding and rubber-banding are not a viewport below the content.
  assert.equal(at(570, 900, 1465), false);
  assert.equal(at(600, 900, 1465), true);
  // Without both numbers there is no judgement to make, and none is claimed.
  assert.equal(pageStanding(JSON.stringify({ y: 800, doc: 1465 })).pastTheEnd, false);
  assert.equal(pageStanding("800").pastTheEnd, undefined);
});

test("the page is asked for a frame before it is photographed", () => {
  // A picture is of what the compositor last painted, not of what the DOM says
  // exists. Cycle 40 kept four captures of 738,560 pixels of a single colour --
  // pure white, at scrollY 600 and 888, on a page whose plan cards had
  // photographed perfectly at 112 a few steps earlier.
  assert.match(WALK, /requestAnimationFrame\(\s*\n?\s*\(\) => requestAnimationFrame/,
    "one frame only says a frame is coming; the second runs after it is committed");
  // Bounded: a throttled or hidden page can stop producing frames altogether,
  // and a capture that waits forever is worse than one taken early.
  assert.match(WALK, /no frame within 1000ms/, "the wait has to give up and say so");
  assert.match(WALK, /no requestAnimationFrame/, "a page without frames has to say that too");
  // And the verdict travels, because a guard nobody can read is not a guard.
  assert.match(WALK, /JSON\.stringify\(\{ frame,/);
});

test("the walk excludes an element something else is drawn on top of", () => {
  // A live run on open-design.ai measured exactly this: a persistent "Download
  // OpenDesign Desktop" modal sat over the page, and the walk kept reporting the
  // covered background text and buttons underneath it as present, at their
  // original document position -- the perception service was then asked to
  // verify ink for elements the capture could never show ink for, because
  // nothing painted them there; the modal did, on top. Every "no ink at all"
  // region on those steps was one of these, and retrying did nothing, because
  // the modal was not a transient state to wait out.
  //
  // elementFromPoint cannot be executed against a real DOM from this test file
  // (WALK only ever runs inside a browser, via agent-browser's eval, and this
  // suite is deliberately dependency-free of both agent-browser and a browser
  // engine -- see package.json's own "no npm ci" reasoning). Verified instead
  // against a real Chromium page, out of band: the exact WALK source below,
  // executed against four constructed pages -- an ordinary unoccluded
  // paragraph, this same modal-over-background-text shape, a container whose
  // own centre point resolves to its nested child (must not be excluded), and
  // a wide paragraph with only its edge covered so its own centre stays clear
  // (must not be excluded either) -- excluded only the genuinely covered
  // element, in all four cases. These assertions are the standing guard that
  // the logic that passed that check stays in the shipped source.
  assert.match(WALK, /document\.elementFromPoint\(x, y\)/,
    "the same per-point check WHAT_IS_UNDER_THE_PIXELS makes at three fixed points, applied per element");
  assert.match(WALK, /top && top !== node && !node\.contains\(top\)/,
    "an element is its own top point, or its own descendant is -- only something outside its subtree covers it");
  // The centre, not a corner: a corner is the point most likely to sit under a
  // neighbouring element's own rounded edge or box-shadow, which is not
  // occlusion of this element by anything a person would call \"on top of it\".
  assert.match(WALK, /rect\.x \+ rect\.width \/ 2/);
  assert.match(WALK, /rect\.y \+ rect\.height \/ 2/);
  // Clamped into the viewport: an element straddling the edge (already known
  // to be at least partly on screen, from the rect.bottom/rect.top guard above
  // it) must not ask elementFromPoint for a point outside the window, which
  // returns null and would read as "nothing is on top of it" for the wrong
  // reason.
  assert.match(WALK, /Math\.min\(Math\.max\(rect\.x \+ rect\.width \/ 2, 0\), innerWidth - 1\)/);
  assert.match(WALK, /Math\.min\(Math\.max\(rect\.y \+ rect\.height \/ 2, 0\), innerHeight - 1\)/);
  // Runs after the existing visibility/display/opacity guard, not instead of
  // it: occlusion is one more way an element is not really there, joining the
  // reasons already checked, not replacing any of them.
  assert.match(WALK,
    /style\.visibility === "hidden".*?Number\(style\.opacity\) === 0\) return;\s*\n\s*\/\/[\s\S]*?const top = topmost\(rect\);/,
    "the occlusion check runs after the CSS-visibility guard, not before or instead of it");
});

test("the walk reports whether the page had painted", async () => {
  assert.equal((await lookAtPage(async () => wholeBatch({ after: "0", frame: "painted" }))).paintCheck, "painted");
  // A page that never produced one says so rather than passing quietly.
  assert.equal((await lookAtPage(async () => wholeBatch({ after: "0", frame: "no frame within 1000ms" }))).paintCheck,
    "no frame within 1000ms");
  assert.equal((await lookAtPage(async () => wholeBatch({ after: "0" }))).paintCheck, "unavailable");
});

test("the boxes are put into the capture's coordinates, not the viewport's", () => {
  // The walk measures against the viewport, because that is what
  // getBoundingClientRect returns. The capture draws the page at its document
  // position inside a viewport-sized frame: a real refused capture taken at
  // scrollY 112 has rows 0 to 111 pure white and its first ink at row 112. So
  // every crop was taken scrollY pixels too high, and every "no ink in this
  // region" was correct about a region nobody meant to measure.
  const walked = [{ selector: "e1", box: { x: 320, y: 55, width: 640, height: 128 } },
                  { selector: "e2", box: { x: 621, y: 489, width: 87, height: 23 } }];
  assert.deepEqual(intoCaptureSpace(walked, 112).map((item) => item.box.y), [167, 601]);
  // At the top of a page the two spaces are the same, which is why every run
  // began clean and degraded from its first scroll.
  assert.deepEqual(intoCaptureSpace(walked, 0), walked);
  // Everything else about a box is left alone.
  assert.equal(intoCaptureSpace(walked, 112)[0].box.x, 320);
  assert.equal(intoCaptureSpace(walked, 112)[0].box.height, 128);
  // A box the walk could not measure is passed through rather than invented.
  assert.deepEqual(intoCaptureSpace([{ selector: "e3" }], 112), [{ selector: "e3" }]);
});

test("the page is brought to the camera, and put back", async () => {
  // The screenshot renders document rows 0 to one viewport whatever the page is
  // scrolled to -- rows 0 to 111 pure white and first ink at 112, on a kept
  // refusal taken at scrollY 112. Moving the boxes to meet it works while the
  // viewport still overlaps the top of the document and stops working entirely
  // past it: at scrollY 700 of a 1465px page every box lands outside a 577px
  // picture, and cycle 49 lost 21 captures that way.
  const seen = await lookAtPage(async () => wholeBatch({ scrollBefore: 700, after: "700",
    shifted: "700" }));

  assert.equal(seen.shiftedBy, 700, "the document is moved up by what the page is scrolled to");
  // Which means the boxes and the picture are both the viewport, and nothing is
  // left to correct.
  assert.equal((seen.scrollY || 0) - (seen.shiftedBy || 0), 0);
});

test("a shift that did not happen leaves the correction to be made", async () => {
  // A guard that cannot run is not a guard that passed: if the page would not
  // take the transform, the picture is still the document's top rows and the
  // boxes still have to be moved to meet it.
  const seen = await lookAtPage(async () => wholeBatch({ scrollBefore: 700, after: "700",
    shifted: "" }));

  assert.equal(seen.shiftedBy, 0);
  assert.equal((seen.scrollY || 0) - (seen.shiftedBy || 0), 700,
    "the whole offset is still owed");
});

test("alreadySeen travels in the request body, defaulting to empty", async () => {
  const bodies = [];
  const client = new PerceptionClient({
    endpoint: "http://perception.test",
    fetch: async (url, options) => {
      bodies.push(JSON.parse(options.body));
      return { ok: true, json: async () => ({ perceived: [] }) };
    },
  });
  const args = { screenshotBase64: "AAA", elements: [{ selector: "e1", box: {} }] };

  await client.perceive(args);
  assert.deepEqual(bodies[0].alreadySeen, [], "a caller that sends nothing behaves as before");

  await client.perceive({ ...args, alreadySeen: ["e1", "e2"] });
  assert.deepEqual(bodies[1].alreadySeen, ["e1", "e2"]);
});
