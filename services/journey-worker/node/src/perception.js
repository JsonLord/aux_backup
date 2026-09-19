"use strict";
/**
 * What the persona actually sees, asked of the perception service.
 *
 * Until now the observation handed to the actor was the accessibility tree as
 * text. That is the wrong source and it shows: a run has "seen" an element that
 * rendered blank, and quoted text that was not on the screen, because the tree
 * says a thing is there whether or not any pixels agree. Worse, the tree is
 * complete -- so every persona, however impatient or short-sighted, received the
 * same exhaustive list and behaved like a crawler reading a manifest.
 *
 * The service answers a narrower question: given this capture, these eyes and
 * this way of scanning, what did this person actually take in? Two things come
 * back that the tree cannot produce -- what was present but not perceivable, and
 * what was legible but never looked at -- and the second is the answer to "why
 * did they not click the thing that was right there".
 *
 * When the service is not configured or not reachable, the caller keeps the
 * tree-based observation it has always used. Perception makes a run better; it
 * is not allowed to make a run fail.
 */

const { readFile, unlink } = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");

const { batch } = require("./agentBrowser");

const REQUEST_TIMEOUT_MS = 20000;

// Interactive things, and things with text of their own. The second half is why
// this exists rather than a list of refs: agent-browser gives a ref to a button
// and a link, and none at all to a paragraph -- and low-contrast body copy is
// the single most common thing a person cannot read.
const WALK = `(async () => {
  // Ask the page to paint, then wait for the paint.
  //
  // The screencast emits a frame when the compositor produces one, and a page
  // that has finished settling produces none -- so the newest frame can be the
  // blank first paint after a navigation, with nothing since to replace it.
  // Cycle 45 measured four such frames: 1280x577 of a single colour, on a page
  // that elementFromPoint showed fully drawn.
  //
  // A pixel down and back is the smallest thing that makes a compositor commit a
  // frame, and it leaves the page exactly where it found it -- which matters,
  // because every box read below is relative to where the page is standing.
  const restore = Math.round(scrollY);
  scrollBy(0, 1);
  scrollBy(0, -1);
  scrollTo(0, restore);
  // Wait for the page to produce a frame before anything reads it.
  //
  // A picture is of what the compositor last painted, not of what the DOM says
  // exists. Scroll a page and photograph it before the next frame is committed
  // and the capture is of a surface nothing has drawn into yet -- which is white,
  // on a white page, and indistinguishable from a viewport with nothing in it.
  // Cycle 40 kept four such captures: 738,560 pixels of a single colour at
  // scrollY 600 and 888, on a page whose plan cards had photographed perfectly at
  // 112 a few steps earlier.
  //
  // Two nested frames, because one only says a frame is coming: the callback of
  // the second runs after the first has been committed. Bounded, because a
  // throttled or hidden page can stop producing frames altogether and a capture
  // that waits forever is worse than a capture taken early -- and said out loud,
  // because a guard that could not run is not a guard that passed.
  const frame = typeof requestAnimationFrame === "function"
    ? await Promise.race([
        new Promise((resolve) => requestAnimationFrame(
          () => requestAnimationFrame(() => resolve("painted")))),
        new Promise((resolve) => setTimeout(() => resolve("no frame within 1000ms"), 1000)),
      ])
    : "no requestAnimationFrame";
  const INTERACTIVE = "a,button,input,select,textarea,summary,[role],[onclick],[tabindex]";
  const out = [];
  const seen = new Set();
  const push = (node, kind) => {
    if (seen.has(node)) return;
    const rect = node.getBoundingClientRect();
    if (rect.width < 2 || rect.height < 2) return;
    if (rect.bottom < 0 || rect.top > innerHeight) return;
    const style = getComputedStyle(node);
    if (style.visibility === "hidden" || style.display === "none" || Number(style.opacity) === 0) return;
    seen.add(node);
    const label = (node.getAttribute && (node.getAttribute("aria-label")
      || node.getAttribute("alt") || node.getAttribute("title"))) || "";
    out.push({
      kind, tag: node.tagName.toLowerCase(),
      role: (node.getAttribute && node.getAttribute("role")) || "",
      name: (label || node.innerText || node.textContent || "").trim().slice(0, 120),
      x: Math.round(rect.x), y: Math.round(rect.y),
      width: Math.round(rect.width), height: Math.round(rect.height),
      // Measured, not inferred from the box. Whether somebody can read something
      // depends on how big the letters are as much as on their contrast, and a
      // box height is a bad proxy: it is line height for one line and the whole
      // paragraph for several.
      fontPx: Math.round(Number.parseFloat(style.fontSize) || 0),
      fontWeight: Number.parseInt(style.fontWeight, 10) || 400,
    });
  };
  document.querySelectorAll(INTERACTIVE).forEach((node) => push(node, "control"));
  document.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,td,th,figcaption,label,span,div").forEach((node) => {
    const direct = Array.from(node.childNodes).filter((child) => child.nodeType === 3)
      .map((child) => child.textContent.trim()).join(" ").trim();
    if (direct.length >= 2) push(node, "text");
  });
  return JSON.stringify({ frame, viewport: { width: innerWidth, height: innerHeight },
    scrollY: Math.round(scrollY),
    // How much page there was when the boxes were taken. Compared against the
    // same number read after the screenshot: a document that grew between the
    // two was still being built, and the picture is of a page that no longer
    // exists.
    documentHeight: Math.round(document.documentElement.scrollHeight),
    elements: out.slice(0, 600) });
})()`;

/** The role a snapshot ref carries, mapped onto what the walk reports. */
function sameThing(element, ref) {
  const name = String(ref.name || "").trim().toLowerCase();
  if (!name) return false;
  const found = String(element.name || "").trim().toLowerCase();
  return found === name || (found.length > 0 && found.startsWith(name) && found.length < name.length + 40);
}

/**
 * Give each walked element the ref that names it, where one does.
 *
 * The ref is what an action can target, so an element without one is something
 * the persona can read but not click -- which is worth knowing and worth saying,
 * rather than quietly dropping.
 */
function linkRefs(elements, refs) {
  const entries = Object.entries(refs || {});
  const taken = new Set();
  return elements.map((element) => {
    const hit = entries.find(([ref, value]) => !taken.has(ref) && sameThing(element, value));
    if (hit) taken.add(hit[0]);
    return {
      selector: hit ? hit[0] : `${element.tag}@${element.x},${element.y}`,
      // Prefer the tree's own role: it is what a screen reader would announce,
      // and the tag is only a guess at it.
      role: (hit && hit[1].role) || element.role || element.tag,
      name: element.name,
      box: { x: element.x, y: element.y, width: element.width, height: element.height },
      fontPx: element.fontPx || 0,
      fontWeight: element.fontWeight || 400,
      actionable: Boolean(hit),
    };
  });
}

/** Unwrap agent-browser's batch envelope: [{command, error, result}], result.result for eval. */
function batchResults(stdout) {
  let parsed;
  try {
    parsed = JSON.parse(String(stdout || ""));
  } catch {
    return [];
  }
  return Array.isArray(parsed) ? parsed : [];
}

/**
 * One look at the page: its tree, its refs, a box for everything on screen, and
 * the pixels themselves.
 *
 * All of it in a single batch, so the walk, the snapshot and the capture see the
 * same page at the same instant. Read a box a moment after the tree and the two
 * disagree on any page that animates, which is most of them -- and a box that
 * does not match the pixels is worse than no box, because it moves the question
 * "can this person see it" onto the wrong part of the image.
 */
// Read back where the page is, after the capture. Every box the walk reports is
// in viewport coordinates, so a scroll between the walk and the screenshot leaves
// the boxes describing where things were and the pixels showing where the page is
// now -- and every crop then lands on whatever happens to be at that offset. A
// live run reported the whole navigation bar as failing WCAG AA at 1:1 for a
// persona with 0.95 acuity and 0.92 contrast sensitivity, "the region and
// everything around it are the same flat colour", because the crops had landed on
// blank page. The reveal keeper was the scroller, and it is held now -- this is
// how we know, rather than assume, that nothing else moved.
// Where the page was standing when the capture was taken, and how much page
// there is. A blank capture and a capture of blank page are the same pixels and
// different bugs: the first is a renderer that painted nothing, the second is a
// viewport parked past the end of the document. Cycle 31 rejected 22 captures
// for having no ink in them and the record could not say which.
// A document whose height changes by more than this between the boxes and the
// picture was still being built. Small enough to catch a page that is still
// laying itself out, large enough to ignore a lazy image settling by a few
// pixels or a scrollbar appearing.
const STILL_ARRIVING_PX = 64;

// A few pixels of rounding, rubber-banding and sub-pixel layout are not a
// viewport below the content.
const PAST_THE_END_SLACK = 8;

const SCROLL_AFTER =
  "(() => JSON.stringify({y: Math.round(scrollY), h: Math.round(innerHeight),"
  + " doc: Math.round(document.documentElement.scrollHeight),"
  + " painted: document.body ? document.body.getBoundingClientRect().height > 0 : false}))()";

/**
 * What the browser says is under the pixels, taken in the same batch as the
 * picture.
 *
 * A capture that comes back white and a viewport with nothing in it are the same
 * image and different faults, and nothing this run recorded could tell them
 * apart: cycle 40 refused captures that were pure white at scrollY 600 and 888
 * on a page whose cards had photographed perfectly at 112, and the record could
 * only say the pixels had no ink in them.
 *
 * `elementFromPoint` answers the question the pixels cannot. Three points down
 * the middle of the viewport, each reporting what the DOM believes is there and
 * how much text it holds. Text where the picture is white means the page was
 * painted and the capture missed it. Nothing at any of the three means the
 * window really is looking at empty page, and the picture is honest.
 */
const WHAT_IS_UNDER_THE_PIXELS =
  "(() => { const at = (fraction) => { const x = Math.round(innerWidth / 2),"
  + " y = Math.round(innerHeight * fraction);"
  + " const node = document.elementFromPoint(x, y);"
  + " if (!node) return {at: fraction, found: null};"
  + " const box = node.getBoundingClientRect();"
  + " return {at: fraction, found: node.tagName,"
  + "   text: String(node.innerText || node.textContent || '').trim().slice(0, 60),"
  + "   box: [Math.round(box.x), Math.round(box.y), Math.round(box.width), Math.round(box.height)],"
  + "   opacity: getComputedStyle(node).opacity, visibility: getComputedStyle(node).visibility}; };"
  + " return JSON.stringify({points: [at(0.15), at(0.5), at(0.85)],"
  + "   y: Math.round(scrollY), h: Math.round(innerHeight),"
  + "   doc: Math.round(document.documentElement.scrollHeight)}); })()";

/**
 * Put the boxes into the same coordinate space as the picture.
 *
 * The walk reports every box against the viewport, because that is what
 * `getBoundingClientRect` measures. The capture does not: it draws the page at
 * its document position inside a viewport-sized frame, so a page scrolled to 112
 * comes back with 112 rows of blank above the content -- measured exactly, on a
 * real refused capture: rows 0 to 111 are pure white and the first ink is at 112.
 *
 * So every crop was taken `scrollY` pixels too high, and the perception service
 * was right every time it said the region had no ink in it. This is the whole of
 * the blank captures, and it explains both kinds cycle 40 kept: at scrollY 112
 * part of the page still overlaps its boxes and some regions resolve, while at
 * 600 and 888 every box lands past the bottom of a 577px frame and the entire
 * capture reads blank.
 *
 * It also explains why every run began clean and degraded from the first scroll,
 * and why nothing aimed at reveals, frames or retries ever moved it: none of them
 * was about coordinates.
 *
 * A box that lands past the bottom of the frame is genuinely not in the picture;
 * the service already tells those apart from blank ones and drops them.
 */
function intoCaptureSpace(elements, scrollY) {
  if (!scrollY) return elements || [];
  return (elements || []).map((element) => {
    const y = Number(element?.box?.y);
    if (!Number.isFinite(y)) return element;
    return { ...element, box: { ...element.box, y: Math.round(y + scrollY) } };
  });
}

/**
 * Bring the page to the camera, since the camera will not come to the page.
 *
 * The screenshot renders document rows 0 to one viewport, whatever the page is
 * scrolled to -- measured exactly on a kept refusal at scrollY 112: rows 0 to 111
 * pure white, first ink at 112. Moving the boxes to meet it works while the
 * viewport still overlaps the top of the document and stops working entirely past
 * that: at scrollY 700 of a 1465px page every box lands outside a 577px picture,
 * and cycle 49 lost 21 captures that way with the screencast frame -- the only
 * other source -- coming back white.
 *
 * Translating the document up by the scroll offset puts what the person is
 * looking at into the rows the camera does photograph. The boxes are then already
 * in the picture's coordinates, because both are the viewport.
 *
 * It is put back immediately afterwards, in the same batch, so nothing else ever
 * sees it. The one thing it changes that a scroll would not: a transform makes the
 * root a containing block, so anything `position: fixed` is photographed where it
 * sits in the document rather than pinned. That costs a sticky header its place in
 * one capture; not doing it costs every element in the capture.
 */
const SHIFT_TO_THE_VIEWPORT =
  "(() => { const root = document.documentElement;"
  + " const y = Math.round(scrollY);"
  + " if (!y) return \"0\";"
  + " root.setAttribute(\"data-aux-was\", root.style.transform || \"\");"
  + " root.style.transform = \"translateY(\" + (-y) + \"px)\";"
  + " return String(y); })()";

const PUT_THE_PAGE_BACK =
  "(() => { const root = document.documentElement;"
  + " if (!root.hasAttribute(\"data-aux-was\")) return \"nothing to undo\";"
  + " root.style.transform = root.getAttribute(\"data-aux-was\");"
  + " root.removeAttribute(\"data-aux-was\");"
  + " return \"restored\"; })()";

async function lookAtPage(runner = batch, { capture = true, ...options } = {}) {
  const file = capture ? path.join(os.tmpdir(), `perception-${process.pid}-${Date.now()}.png`) : "";
  const commands = capture
    ? [["snapshot"], ["eval", WALK], ["eval", SHIFT_TO_THE_VIEWPORT], ["screenshot", file],
       ["eval", PUT_THE_PAGE_BACK], ["eval", SCROLL_AFTER], ["eval", WHAT_IS_UNDER_THE_PIXELS]]
    : [["snapshot"], ["eval", WALK]];
  const empty = { elements: [], refs: {}, viewport: null, scrollY: 0, snapshot: "",
    screenshotBase64: "", moved: false, scrollCheck: "skipped" };
  const response = await runner(commands, options);
  if (!response.ok) return empty;
  const results = batchResults(response.stdout);
  const snapshot = results.find((item) => item.command?.[0] === "snapshot")?.result || {};
  const evaluations = results.filter((item) => item.command?.[0] === "eval");
  // Named rather than counted. The walk is always first; the rest move whenever a
  // command is added between them, and an index quietly reading the wrong answer
  // is the kind of mistake that looks like a page behaving strangely.
  const evaluated = evaluations[0]?.result;
  const shifted = capture ? scrollNumber(scrollValue(evaluations[1]?.result)) : NaN;
  const after = capture ? evaluations[3]?.result : undefined;
  const beneath = capture ? evaluations[4]?.result : undefined;
  let walked = { elements: [], viewport: null };
  try {
    walked = JSON.parse(typeof evaluated === "string" ? evaluated : evaluated?.result || "{}");
  } catch {
    walked = { elements: [], viewport: null };
  }
  let screenshotBase64 = "";
  if (capture) {
    try {
      screenshotBase64 = (await readFile(file)).toString("base64");
    } catch {
      screenshotBase64 = "";
    }
    unlink(file).catch(() => {});
  }
  const before = Number(walked.scrollY) || 0;
  const standing = pageStanding(scrollValue(after));
  const settled = standing.y;
  // Three states, not two. The hold on the reveal keeper is the fix; this
  // read-back is corroboration. A read-back we cannot parse has lost the
  // corroboration, not the fix -- treating "unknown" as "moved" would let one
  // unexpected envelope shape silently switch perception off for a whole run,
  // which is a worse failure than the one being guarded against and a much
  // quieter one.
  const known = Number.isFinite(settled);
  const scrolled = capture && known && settled !== before;
  // A page still growing is a page still arriving. Cycle 32 refused 31 captures
  // for having no ink in them, and the standing said why: the document measured
  // 1465px where the same page elsewhere measures 8620px. Nothing was parked
  // past the end and the body had laid out -- the picture was simply taken
  // while the page was still building itself, so the tree already listed
  // elements that had not been painted yet.
  //
  // This is the layout twin of the scroll-stability guard, and for the same
  // reason: boxes and pixels have to describe one state of the page.
  const grewBy = capture && standing.known && standing.documentHeight && walked.documentHeight
    ? Math.abs(standing.documentHeight - Number(walked.documentHeight)) : 0;
  const grew = grewBy > STILL_ARRIVING_PX;
  const moved = scrolled || grew;
  return {
    elements: linkRefs(walked.elements || [], snapshot.refs || {}),
    refs: snapshot.refs || {},
    viewport: walked.viewport || null,
    scrollY: before,
    snapshot: String(snapshot.snapshot || ""),
    screenshotBase64,
    // Whether the boxes and the pixels are describing the same page.
    moved,
    scrolledTo: known ? settled : null,
    // Where the page was standing when the capture was taken. A blank capture
    // and a capture of blank page are the same pixels and different bugs.
    standing: standing.known ? standing : undefined,
    // And what the browser says is under those pixels, read in the same batch.
    // Carried raw: this is evidence, and the reader of a refusal is better served
    // by what the page said than by this file's opinion of it.
    beneath: beneath === undefined ? undefined : scrollValue(beneath),
    // "painted" | "no frame within 1000ms" | "no requestAnimationFrame" -- whether
    // the page had drawn a frame when the picture was taken.
    paintCheck: walked.frame || "unavailable",
    // How far the document was moved up to bring the viewport into the picture.
    // Zero at the top of a page, where the camera and the viewport already agree.
    shiftedBy: Number.isFinite(shifted) ? shifted : 0,
    // "same" | "moved" | "unavailable" -- said out loud, because a guard that
    // cannot run is not a guard that passed.
    scrollCheck: !capture ? "skipped" : known ? (scrolled ? "moved" : "same") : "unavailable",
    // "settled" | "growing" | "unavailable" -- said out loud, because a guard
    // that cannot run is not a guard that passed.
    layoutCheck: !capture ? "skipped"
      : (standing.known && standing.documentHeight && walked.documentHeight)
        ? (grew ? "growing" : "settled") : "unavailable",
    grewBy,
  };
}

/**
 * Where the page stood, from the read-back.
 *
 * The read-back used to be a bare number. It now carries the viewport height and
 * the document height with it, because those are what tell a renderer that
 * painted nothing apart from a viewport parked past the end of the page -- the
 * same blank pixels, two different bugs, and cycle 31 rejected 22 captures
 * without being able to say which.
 *
 * The bare-number form is still accepted: the guard this feeds predates the
 * extra fields and must not depend on them.
 */
function pageStanding(value) {
  const plain = scrollNumber(value);
  if (Number.isFinite(plain)) return { y: plain, known: true };
  if (typeof value === "string" && value.trim().startsWith("{")) {
    try {
      const parsed = JSON.parse(value.trim());
      const y = scrollNumber(String(parsed.y));
      if (!Number.isFinite(y)) return { y: NaN, known: false };
      return { y, known: true, viewportHeight: Number(parsed.h) || 0,
               documentHeight: Number(parsed.doc) || 0, painted: Boolean(parsed.painted),
               // Below the end of its own content: the viewport starts past the
               // last pixel the document has, so the capture is of nothing and
               // the page is perfectly fine.
               //
               // The comparison is against the furthest a document can be
               // scrolled -- its height less one viewport -- not against its
               // height. Against the height it can never fire: a page 1465px
               // tall in a 900px viewport stops scrolling at 565, and cycle 33
               // photographed blank space at 800, 867 and 712 while this check
               // reported everything in order.
               pastTheEnd: Number(parsed.doc) > 0 && Number(parsed.h) > 0
                 && y > Math.max(0, Number(parsed.doc) - Number(parsed.h)) + PAST_THE_END_SLACK };
    } catch { return { y: NaN, known: false }; }
  }
  return { y: NaN, known: false };
}

/**
 * The read-back as a number, or NaN when there is no answer in it.
 *
 * Strict on purpose: `Number("")` is 0, so an empty read-back would have matched
 * a page at the top and reported itself as a passed guard. A guard that cannot
 * tell "the page is at 0" from "nobody answered" is not a guard.
 */
function scrollNumber(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : NaN;
  if (typeof value !== "string" || !/^-?\d+(\.\d+)?$/.test(value.trim())) return NaN;
  return Number(value.trim());
}

/** Unwrap agent-browser's eval envelopes down to the scroll number. */
function scrollValue(value) {
  let current = value;
  let depth = 0;
  while (current && typeof current === "object" && "result" in current && depth < 5) {
    current = current.result;
    depth += 1;
  }
  return typeof current === "string" ? current.trim() : current;
}

/** One screencast frame as bare base64, or "" when there is nothing usable in it. */
function frameImage(frame) {
  return String(frame?.data || "").replace(/^data:image\/[a-z+]+;base64,/, "");
}

/** Frame payloads as the perception service wants them: bare base64, oldest first. */
function motionFramesFrom(frames) {
  return (frames || []).map(frameImage).filter(Boolean);
}

class PerceptionClient {
  /**
   * @param {object} [options]
   * @param {string} [options.endpoint]  PERCEPTION_SERVICE_URL; absent means off
   */
  constructor(options = {}) {
    this.endpoint = String(options.endpoint || process.env.PERCEPTION_SERVICE_URL || "").replace(/\/$/, "");
    this.timeoutMs = Number(options.timeoutMs) || REQUEST_TIMEOUT_MS;
    this.fetch = options.fetch || globalThis.fetch;
    this.detectUnnamed = options.detectUnnamed ?? process.env.PERCEPTION_DETECT_UNNAMED === "1";
    // One failure is enough: a service that is not there will not be there next
    // step either, and forty timeouts would cost a run thirteen minutes.
    this.disabled = !this.endpoint;
    this.lastError = "";
  }

  get available() {
    return Boolean(this.endpoint) && !this.disabled;
  }

  async perceive({ screenshotBase64, elements, abilities, behavior, motionFrames, viewport, goal,
    returnSeenImage = false, alreadySeen }) {
    if (!this.available || !screenshotBase64 || !elements?.length) return null;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    try {
      const response = await this.fetch(`${this.endpoint}/v1/perceive`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          screenshotBase64, elements, abilities: abilities || {}, behavior: behavior || {},
          motionFrames: motionFrames || [], viewport: viewport || undefined, goal: goal || "",
          // Asked for by the director on every step and dropped here until now,
          // so the one artifact that makes an eyesight finding checkable was
          // never produced.
          returnSeenImage: Boolean(returnSeenImage),
          detectUnnamed: this.detectUnnamed,
          // CAP-0: what this persona has already fixated this run, so the service
          // deprioritises re-fixating it rather than the scan resetting to
          // nothing every step. The director accumulates this; this client only
          // forwards it.
          alreadySeen: alreadySeen || [],
        }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error(`perception service returned HTTP ${response.status}`);
      return await response.json();
    } catch (error) {
      this.lastError = error.message;
      this.disabled = true;
      return null;
    } finally {
      clearTimeout(timer);
    }
  }
}

module.exports = { PerceptionClient, SCROLL_AFTER, WALK, batchResults, frameImage, intoCaptureSpace, linkRefs, lookAtPage,
  motionFramesFrom, pageStanding, scrollNumber, scrollValue };
