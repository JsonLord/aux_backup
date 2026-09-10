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
const WALK = `(() => {
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
    });
  };
  document.querySelectorAll(INTERACTIVE).forEach((node) => push(node, "control"));
  document.querySelectorAll("h1,h2,h3,h4,h5,h6,p,li,td,th,figcaption,label,span,div").forEach((node) => {
    const direct = Array.from(node.childNodes).filter((child) => child.nodeType === 3)
      .map((child) => child.textContent.trim()).join(" ").trim();
    if (direct.length >= 2) push(node, "text");
  });
  return JSON.stringify({ viewport: { width: innerWidth, height: innerHeight },
    scrollY: Math.round(scrollY), elements: out.slice(0, 600) });
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
async function lookAtPage(runner = batch, { capture = true, ...options } = {}) {
  const file = capture ? path.join(os.tmpdir(), `perception-${process.pid}-${Date.now()}.png`) : "";
  const commands = capture
    ? [["snapshot"], ["eval", WALK], ["screenshot", file]]
    : [["snapshot"], ["eval", WALK]];
  const empty = { elements: [], refs: {}, viewport: null, scrollY: 0, snapshot: "", screenshotBase64: "" };
  const response = await runner(commands, options);
  if (!response.ok) return empty;
  const results = batchResults(response.stdout);
  const snapshot = results.find((item) => item.command?.[0] === "snapshot")?.result || {};
  const evaluated = results.find((item) => item.command?.[0] === "eval")?.result;
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
  return {
    elements: linkRefs(walked.elements || [], snapshot.refs || {}),
    refs: snapshot.refs || {},
    viewport: walked.viewport || null,
    scrollY: walked.scrollY || 0,
    snapshot: String(snapshot.snapshot || ""),
    screenshotBase64,
  };
}

/** Frame payloads as the perception service wants them: bare base64, oldest first. */
function motionFramesFrom(frames) {
  return (frames || [])
    .map((frame) => String(frame?.data || "").replace(/^data:image\/[a-z+]+;base64,/, ""))
    .filter(Boolean);
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

  async perceive({ screenshotBase64, elements, abilities, behavior, motionFrames, viewport, goal }) {
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
          detectUnnamed: this.detectUnnamed,
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

module.exports = { PerceptionClient, WALK, batchResults, linkRefs, lookAtPage, motionFramesFrom };
