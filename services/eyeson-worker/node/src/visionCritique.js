"use strict";
/**
 * Real vision-based UX critique of a live JourneyTest screenshot -- the second
 * stage of the two-stage feedback model (spec.md sections 19-21):
 *
 *   Stage 1 (persona feedback): did the synthetic user complete the task?
 *     -- journeytest-core's own AgentVerdict, already wired into
 *        apps/api/executor.py's _pain_points_from_journeys.
 *   Stage 2 (grounded UX critique): independent of whether the task succeeded,
 *     what does the actual rendered page look like to a UX/accessibility
 *     reviewer, referenced against real semantic elements (selector/role/
 *     boundingBox from journeytest-core's snapshot) so a finding can name the
 *     specific place(s) on the screenshot it's about, then grounded against a
 *     small curated UX-heuristics corpus (knowledge.js).
 *
 * toPainPoint() below shapes a critique finding into the full UXPainPoint
 * record spec.md section 20.2 describes (behavioralImpact, elements with
 * roles, diagnosis, alternatives, overlays) so it can flow through the
 * existing, already-tested aggregate.js cohort/root-cause aggregator --
 * built for the native fixture engine's simulated psychological deltas, but
 * live JourneyTest evidence has no such simulation to draw on. Where the
 * native engine measures frustrationDelta/confusionDelta/trustDelta from an
 * actual behavior-state transition, this module asks the vision model to
 * *estimate* the same three quantities as part of its critique -- the same
 * epistemic category as its severity/category judgment, not a fabricated
 * number. cognitiveEffortDelta/physicalEffortDelta/elapsedCostMs/retries/
 * backtracks have no analogue in a single static screenshot critique and are
 * left at 0 (unmeasured) rather than invented.
 *
 * Uses the same OpenAI-compatible endpoint already configured for the rest of
 * this deployment (OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL) -- verified
 * live to support image input (see docs/aux-space-status-overview.md).
 */
const { createHash } = require("node:crypto");
const { CuratedUXKnowledgeProvider, groundPainPoint } = require("./knowledge");

/**
 * A vision critique that could not be produced because the model endpoint was
 * unavailable or not configured -- not because the caller sent a bad request.
 * Carries the HTTP status the worker should answer with, so an upstream outage
 * is not reported to the caller as "invalid_evidence" (it was: a live run's
 * report said only "failed: HTTP Error 422: Unprocessable Entity", which reads
 * as our request being malformed and hid a provider failure entirely).
 */
class VisionUnavailableError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = "VisionUnavailableError";
    this.status = status;
    this.code = code;
  }
}

// Statuses where the identical request is rejected every time. Retrying one
// burns the attempt budget, delays the failure by the backoff, and buries the
// real cause (a 413 payload, a bad key) behind a generic "after 3 attempts".
// A request that never reached a server: DNS, a dropped link, a provider
// restarting. undici throws TypeError("fetch failed"); a timeout arrives as an
// AbortError. Neither carries an HTTP status, so both fell through to the plain
// linear retry.
const UNREACHABLE_ATTEMPTS = 6;
// However many attempts are allowed, stop extending them after this long, so an
// endpoint that hangs rather than refuses cannot hold the critique for ten
// minutes.
const UNREACHABLE_PATIENCE_MS = 180000;
const MAX_BACKOFF_MS = 30000;

/**
 * What actually went wrong, when the answer is hiding one level down.
 *
 * undici reports every transport failure as TypeError("fetch failed") and puts
 * the real cause -- EAI_AGAIN, ECONNREFUSED, UND_ERR_CONNECT_TIMEOUT, a TLS
 * failure -- on error.cause. Cycles 20 and 21 each lost two of three personas to
 * "fetch failed" and the record could not say which, so four different
 * explanations stayed equally plausible: DNS, a dropped link, an exhausted
 * connection pool, a provider restart. They call for different fixes.
 */
function describeFailure(error) {
  const parts = [];
  let current = error;
  for (let depth = 0; current && depth < 4; depth += 1) {
    const code = current.code ? ` (${current.code})` : "";
    const text = `${String(current.message || current)}${code}`;
    if (text && !parts.includes(text)) parts.push(text);
    current = current.cause;
  }
  return parts.join(" <- ").slice(0, 300);
}

/** Nothing answered. Distinct from something answering unhappily. */
function unreachable(error) {
  if (error?.status !== undefined) return false;
  const name = String(error?.name || "");
  if (name === "TypeError" || name === "AbortError") return true;
  return /fetch failed|network|socket hang up|ECONNRESET|ECONNREFUSED|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|UND_ERR/i
    .test(String(error?.message || ""));
}

const NON_RETRYABLE_STATUS = new Set([400, 401, 403, 404, 413, 422]);

const DEFAULT_VISION_MAX_TOKENS = 6000;

function visionMaxTokens() {
  const configured = Number.parseInt(String(process.env.EYESON_VISION_MAX_TOKENS || ""), 10);
  return Number.isInteger(configured) && configured > 0 ? configured : DEFAULT_VISION_MAX_TOKENS;
}

const FINDING_CATEGORIES = ["accessibility", "usability", "visual_design", "copy", "navigation"];
const ELEMENT_ROLES = ["trigger", "cause", "feedback", "obstacle", "recovery"];
// Maps this module's finding categories onto knowledge.js's curated-source
// categories (wcag-error-identification etc. are tagged with problem
// categories like "validation_failure"/"ambiguous_feedback"/"navigation_failure").
const GROUNDING_CATEGORY_MAP = { accessibility: "validation_failure", navigation: "navigation_failure",
  usability: "ambiguous_feedback", visual_design: "ambiguous_feedback", copy: "ambiguous_feedback" };

/**
 * How big the capture is, read from the image itself.
 *
 * Derived here rather than passed in, because the worker always holds the image
 * and a number travelling separately from the thing it describes is a number that
 * can be wrong about it. Only the two headers that matter: PNG's IHDR, which is
 * always at a fixed offset, and JPEG's SOF marker. Anything else returns null and
 * the prompt simply says nothing about the size.
 */
function captureSize(base64) {
  let bytes;
  try {
    bytes = Buffer.from(String(base64 || ""), "base64");
  } catch {
    return null;
  }
  // Height is bytes 20..23, so 24 bytes is exactly enough -- `> 24` rejected a
  // header that was complete.
  if (bytes.length >= 24 && bytes.readUInt32BE(0) === 0x89504e47) {
    return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
  }
  if (bytes.length > 4 && bytes[0] === 0xff && bytes[1] === 0xd8) {
    for (let at = 2; at + 9 < bytes.length;) {
      if (bytes[at] !== 0xff) { at += 1; continue; }
      const marker = bytes[at + 1];
      // The SOF markers carry the dimensions; DHT/DAC/RST and the like do not.
      if (marker >= 0xc0 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc) {
        return { height: bytes.readUInt16BE(at + 5), width: bytes.readUInt16BE(at + 7) };
      }
      at += 2 + bytes.readUInt16BE(at + 2);
    }
  }
  return null;
}

// How many elements the prompt lists before it stops. The count matters to what
// the prompt may claim about the list: a truncated list is not an inventory.
const LISTED_ELEMENTS = 60;

function buildPrompt({ url, task, personaSummary, elements, capture }) {
  const detected = (elements || []).length;
  const shown = (elements || []).slice(0, LISTED_ELEMENTS);
  const elementList = shown.map((element, index) =>
    // "kind" rather than "role" for the element's own type: the reviewer is asked
    // for a `role` of its own (what part the element plays in the finding), and
    // one word meaning two things in one prompt is an invitation to conflate them.
    `${index}. kind=${element.role || element.tag} text="${(element.text || "").slice(0, 80)}" box=${JSON.stringify(element.boundingBox || {})}`,
  ).join("\n");
  // What the list is, said plainly, because what it is decides what may be
  // concluded from it. A complete list is ground truth a claim can be checked
  // against; a truncated one is a sample and says nothing about what is missing.
  const inventory = detected <= LISTED_ELEMENTS
    ? `This list is complete for this capture: every element the page declared is in it, `
      + `each exactly once. If something is not here, it is not on the page; if something `
      + `appears here once, it is on the page once.`
    : `This list is the first ${LISTED_ELEMENTS} of ${detected} elements detected, so it is a `
      + `sample rather than an inventory -- draw no conclusion from a thing being absent from it.`;
  return {
    system: "You are a senior UX and accessibility reviewer critiquing a real screenshot of a live "
      + "web page. Only report issues you can actually see or infer from the provided element list -- "
      + "never invent elements that are not in the list or in the image.\n"
      // Three things this reviewer has been confidently wrong about, each of
      // which the run could disprove afterwards. Said here so the claim is not
      // made rather than caught later.
      + "Three things you are not looking at, and must not report:\n"
      + "- The capture may be a stitched full-page image, taller than any screen and taller than "
      + "anything a visitor sees at once. Generous vertical whitespace between sections is normal "
      + "page design at that scale. Do not report empty space, tall gaps or a page's length as a "
      + "rendering bug.\n"
      + "- Repeated structure is not repeated content. Pricing tiers, feature cards and testimonial "
      + "rows are deliberately alike. Before reporting that anything is duplicated, check the element "
      + "list: a thing that is on the page twice is in the list twice.\n"
      + "- You are looking at one frame of a journey, not the journey. You cannot see what the "
      + "visitor did next, what scrolling revealed, or whether they found what they came for. Report "
      + "what is wrong with this screen; never that it prevented, blocked or stopped anyone.\n"
      + "Respond with ONLY a JSON array "
      + "(no markdown fences, no commentary), where each item is:\n"
      + `{"category": one of ${JSON.stringify(FINDING_CATEGORIES)}, "severity": "low"|"medium"|"high"|"critical", `
      + '"title": short finding title, "description": what is wrong and why, '
      + `"elements": [{"element": the index number of a line in the numbered list below, "role": one of ${JSON.stringify(ELEMENT_ROLES)}}] `
      + '-- name every element the finding is about. Across sixteen findings in a row this '
      + 'came back empty every time, which leaves a reader nothing to look at and leaves the '
      + 'claim unanchored to anything that can be checked. An empty array means the finding is '
      + 'genuinely about the whole page -- its overall flow, tone or information architecture -- '
      + 'and not that pointing at the elements would have taken a moment longer. If you can say '
      + 'where on the screen the problem is, say which elements. '
      + '"estimatedImpact": {"frustration": 0-1, "confusion": 0-1, "trust": 0-1 (how much this would erode trust)} '
      + '-- your honest estimate of how a real user would react, not a fixed value, '
      + '"alternatives": [{"proposedChange": a specific, actionable fix, "rationale": why it would help, '
      + '"effort": "low"|"medium"|"high"}] (1-2 alternatives; omit only if you truly have none)}. '
      + "Respond with ONLY a JSON object (no markdown fences, no commentary) of the form "
      + '{"issues": [ ...items as described above... ], "strengths": [{"title": short name of the '
      + 'design decision that works well, "description": why it works and what it does for the user, '
      + `"elements": [{"element": the index number of a line in the numbered list below, "role": one of ${JSON.stringify(ELEMENT_ROLES)}}]}]}. `
      + "\"strengths\" are design decisions on THIS screenshot that are working and should be preserved "
      + "in any redesign (consistent control styling, restrained colour use, well-understood icons, clear "
      + "hierarchy, and so on) -- report only what you can actually see, and return an empty array rather "
      + "than inventing praise. Likewise return an empty \"issues\" array if you see no real problems -- "
      + "do not invent problems to fill it.",
    user: `Target URL: ${url}\nTask the synthetic user was attempting: ${task}\n`
      + (personaSummary ? `Synthetic user: ${personaSummary}\n` : "")
      + (capture?.width && capture?.height
          ? `\nThis capture is ${capture.width}x${capture.height} CSS pixels`
            + (capture.height > capture.width * 1.6
                ? " -- a stitched full-page image, far taller than the visitor's screen."
                : ".") + "\n"
          : "")
      + `\nElements on this screenshot. Cite one by its index number -- the number at the `
      + `start of the line -- and nothing else; the selector is resolved from it here.\n`
      + `${elementList || "(none detected)"}\n`
      + `${inventory}\n\n`
      + "Critique the attached screenshot for real, specific UX/accessibility/visual-design/copy/navigation issues.",
  };
}

function clamp01(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
}

/**
 * The complete objects at the start of a JSON array body that may be cut off.
 *
 * A completion that ran out of budget ends mid-value, so `JSON.parse` rejects
 * the whole document -- including the findings that were written in full before
 * the cut. Walking the array and keeping the elements that close is not
 * "repairing" arbitrary JSON: nothing is invented, and anything incomplete is
 * dropped. Strings are tracked so a brace inside a description cannot be
 * mistaken for structure.
 */
function completeObjectsIn(text) {
  const objects = [];
  let depth = 0, start = -1, inString = false, escaped = false;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (inString) {
      if (escaped) escaped = false;
      else if (character === "\\") escaped = true;
      else if (character === '"') inString = false;
      continue;
    }
    if (character === '"') { inString = true; continue; }
    if (character === "{") { if (depth === 0) start = index; depth += 1; continue; }
    if (character === "}") {
      depth -= 1;
      if (depth === 0 && start >= 0) {
        try { objects.push(JSON.parse(text.slice(start, index + 1))); } catch { /* not usable */ }
        start = -1;
      }
    }
  }
  return objects;
}

/** The body of the named array, from its opening bracket to the end of the text. */
function arrayBodyAfter(text, key) {
  const at = text.indexOf(`"${key}"`);
  if (at < 0) return "";
  const open = text.indexOf("[", at);
  return open < 0 ? "" : text.slice(open + 1);
}

/**
 * What a truncated completion still said.
 *
 * A live run lost every screenshot's critique to this: the model hit max_tokens
 * mid-array (finish_reason "length", completion_tokens exactly at the cap) and
 * the parse threw, so a critique with several complete findings in it counted
 * for nothing and the report said only that the vision stage "failed". The
 * findings that were written in full are real observations about real pixels,
 * so they are kept and the incomplete tail is dropped.
 */
function salvageTruncatedCritique(text) {
  const issues = completeObjectsIn(arrayBodyAfter(text, "issues"));
  const strengths = completeObjectsIn(arrayBodyAfter(text, "strengths"));
  if (!issues.length && !strengths.length) return null;
  return { issues, strengths };
}

function parseCritique(content, { truncated = false, elements = [] } = {}) {
  let stripped = content.trim();
  if (stripped.startsWith("```")) {
    stripped = stripped.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n?```\s*$/, "").trim();
  }
  // The prompt asks for {"issues": [...], "strengths": [...]}, but a vision model
  // that ignores the wrapper and returns a bare issues array is still useful --
  // accept both rather than throwing away a real critique over its envelope.
  let parsed;
  try {
    parsed = JSON.parse(stripped);
  } catch (error) {
    const objectMatch = stripped.match(/\{[\s\S]*\}/);
    const arrayMatch = stripped.match(/\[[\s\S]*\]/);
    const candidate = objectMatch && (!arrayMatch || objectMatch.index <= arrayMatch.index) ? objectMatch : arrayMatch;
    let recovered = null;
    try {
      if (candidate) recovered = JSON.parse(candidate[0]);
    } catch { /* fall through to salvage */ }
    if (recovered === null) {
      const salvaged = salvageTruncatedCritique(stripped);
      if (salvaged) {
        return { issues: normalizeIssues(salvaged.issues, elements), strengths: normalizeStrengths(salvaged.strengths, elements),
          truncated: true };
      }
      // Say which failure this is. "did not return JSON" for a completion that
      // was cut off at the budget reads as the model misbehaving, when what
      // happened is that we asked for more than we left room for.
      throw new Error(truncated
        ? `vision critique was cut off at the completion budget before any finding was complete: ${error.message}`
        : "vision critique did not return JSON");
    }
    parsed = recovered;
  }
  if (Array.isArray(parsed)) return { issues: normalizeIssues(parsed, elements), strengths: [] };
  if (!parsed || typeof parsed !== "object") throw new Error("vision critique did not return a JSON object or array");
  return { issues: normalizeIssues(parsed.issues, elements), strengths: normalizeStrengths(parsed.strengths, elements) };
}

function normalizeStrengths(value, elements) {
  if (!Array.isArray(value)) return [];
  return value.filter((item) => item && typeof item === "object" && item.title && item.description)
    .map((item) => ({
      title: String(item.title), description: String(item.description),
      elements: citedOnThePage(Array.isArray(item.elements) ? item.elements
        // A citation is a line number or a selector; either can name a real
        // element, and citedOnThePage decides which of them actually does.
        .filter((element) => element && (element.element !== undefined
          || typeof element.elementSelector === "string"))
        .map((element) => ({ element: element.element, elementSelector: element.elementSelector,
          role: ELEMENT_ROLES.includes(element.role) ? element.role : "cause" }))
        : [], elements),
    }));
}

function parseFindings(content) {
  return parseCritique(content).issues;
}

/**
 * Keep only the cited selectors that are really on the page.
 *
 * Asking the reviewer to name the elements a finding is about took citations from
 * zero of sixteen to eight of ten -- and every selector in that first batch was
 * invented. Against a Tailwind site whose element list is agent-browser refs
 * ("e6", "span@316,533") it produced Bootstrap: `a.btn.btn-primary.btn-lg.mr-3`,
 * `h1.display-4.font-weight-bold.mb-3`, `div.col-md-6.text-center > p`. Plausible
 * CSS for some other website.
 *
 * An invented citation is worse than none, because it reads as corroboration and
 * a reader has to go and look to find out it is not. The prompt already says
 * "exact selector string from the numbered list"; this is the part that does not
 * depend on the model having listened.
 *
 * Duplicates go too: the same selector arrived three times in one finding's array,
 * which says nothing three times.
 */
function citedOnThePage(cited, elements) {
  const page = elements || [];
  const real = new Map(page.map((element) => [element.selector, element]).filter(([key]) => key));
  // Nothing to check against is not the same as a citation that failed a check.
  // A caller that did not pass the page's elements -- a test of the parser, a
  // legacy path -- has given no basis to judge, and stripping every citation on
  // that basis would be the guard causing the harm it exists to prevent.
  //
  // An index is the exception, because it is not a name: it is a lookup into a
  // list, and with no list it resolves to nothing. A live report carried
  // `elementId: null` on twenty-four citations across seven findings for exactly
  // this reason -- the screenshots had no paired DOM snapshot, so the element
  // list was empty and the indices passed straight through unresolved. A citation
  // that resolves to nothing is not a citation.
  if (!real.size) {
    return (cited || []).filter((element) => typeof element.elementSelector === "string"
      && element.elementSelector);
  }
  const kept = [];
  const seen = new Set();
  for (const element of cited || []) {
    // The number first. The reviewer is asked to point at a line of the numbered
    // list rather than to transcribe a selector, because an index is a thing it
    // cannot make plausible: 3 is either in range or it is not, and "e6" spelled
    // as `a.btn.btn-primary.btn-lg.mr-3` is not detectable as wrong without
    // checking, whereas 97 out of 29 is.
    const index = Number.isInteger(element.element) ? element.element
      : (/^\d+$/.test(String(element.element ?? "")) ? Number(element.element) : null);
    const selector = index !== null && index >= 0 && index < page.length
      ? page[index].selector
      // A model that wrote the selector out anyway is not punished for it, as
      // long as the selector is real: this check is about whether the thing
      // exists, not about which way it was named.
      : (real.has(element.elementSelector) ? element.elementSelector : null);
    if (!selector || seen.has(selector)) continue;
    seen.add(selector);
    kept.push({ ...element, elementSelector: selector });
  }
  return kept;
}

function normalizeIssues(value, elements) {
  const parsed = Array.isArray(value) ? value : [];
  return parsed.filter((item) => item && typeof item === "object" && item.title && item.description)
    .map((item) => ({
      category: FINDING_CATEGORIES.includes(item.category) ? item.category : "usability",
      severity: ["low", "medium", "high", "critical"].includes(item.severity) ? item.severity : "medium",
      title: String(item.title), description: String(item.description),
      elements: citedOnThePage(Array.isArray(item.elements) ? item.elements
        // A citation is a line number or a selector; either can name a real
        // element, and citedOnThePage decides which of them actually does.
        .filter((element) => element && (element.element !== undefined
          || typeof element.elementSelector === "string"))
        .map((element) => ({ element: element.element, elementSelector: element.elementSelector,
          role: ELEMENT_ROLES.includes(element.role) ? element.role : "cause" }))
        : [], elements),
      estimatedImpact: { frustration: clamp01(item.estimatedImpact?.frustration),
        confusion: clamp01(item.estimatedImpact?.confusion), trust: clamp01(item.estimatedImpact?.trust) },
      alternatives: Array.isArray(item.alternatives) ? item.alternatives
        .filter((alternative) => alternative && alternative.proposedChange)
        .map((alternative) => ({ proposedChange: String(alternative.proposedChange),
          rationale: alternative.rationale ? String(alternative.rationale) : undefined,
          effort: ["low", "medium", "high"].includes(alternative.effort) ? alternative.effort : "medium" }))
        : [],
    }));
}

async function completeVision({ systemPrompt, userText, imageBase64, mimeType = "image/png",
  model, apiKey, baseUrl, maxAttempts = 3, retryWaitMs = 2000, timeoutMs = 60000 }) {
  const payload = {
    model, temperature: 0.2,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: [
        { type: "text", text: userText },
        { type: "image_url", image_url: { url: `data:${mimeType};base64,${imageBase64}` } },
      ] },
    ],
    // Vision-capable models routed by "auto" can spend a large share of the
    // completion budget on hidden reasoning before emitting visible text
    // (observed live: gemini-3.5-flash cut off at 9 visible tokens with
    // max_tokens=300, finish_reason "length"); this needs real headroom.
    //
    // 2500 was still not enough. A live critique of a page with 52 detected
    // elements stopped at exactly 2500 completion tokens with finish_reason
    // "length", mid-string inside its fourth finding -- and every screenshot in
    // that run failed the same way, so the report carried no vision findings at
    // all. A finding runs to a few hundred tokens once it carries a
    // recommendation and its element references, so this leaves room for a full
    // critique rather than most of one. EYESON_VISION_MAX_TOKENS overrides it
    // for a route with a smaller ceiling.
    max_tokens: visionMaxTokens(),
  };
  let lastError;
  let attemptsSpent = 0;
  let allowed = Math.max(1, maxAttempts);
  const startedAt = Date.now();
  for (let attempt = 1; attempt <= allowed; attempt += 1) {
    attemptsSpent = attempt;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
        method: "POST", signal: controller.signal,
        headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const failure = new Error(
          `vision endpoint returned HTTP ${response.status}: ${(await response.text()).slice(0, 500)}`);
        failure.status = response.status;
        throw failure;
      }
      const data = await response.json();
      const choice = data.choices?.[0];
      const content = choice?.message?.content;
      if (!content || !content.trim()) throw new Error("vision endpoint returned an empty completion");
      // Whether the model stopped because it was finished or because it ran out
      // of room. The difference decides whether an unparseable answer is the
      // model's fault or ours, and the caller cannot tell from the text alone.
      return { content, truncated: choice?.finish_reason === "length" };
    } catch (error) {
      lastError = error;
      if (NON_RETRYABLE_STATUS.has(error?.status)) break;
      // Nothing answered at all. The same blip that ended two of three personas
      // in cycle 20 also took the whole vision critique, which had the same three
      // quick tries and the same linear wait -- so the report carried no vision
      // findings and said so, truthfully, about an outage that lasted under a
      // minute. An endpoint that is gone deserves more patience than one that
      // answered unhappily, not less.
      if (unreachable(error) && Date.now() - startedAt < UNREACHABLE_PATIENCE_MS) {
        allowed = Math.max(allowed, UNREACHABLE_ATTEMPTS);
      }
      if (attempt < allowed) {
        await new Promise((resolve) => setTimeout(resolve,
          unreachable(error) ? Math.min(MAX_BACKOFF_MS, retryWaitMs * 2 ** attempt)
                             : retryWaitMs * attempt));
      }
    } finally {
      clearTimeout(timeout);
    }
  }
  throw new VisionUnavailableError(
    `vision critique failed after ${attemptsSpent} attempts: ${describeFailure(lastError)}`,
    502, "vision_upstream_failed");
}

/**
 * Critique one screenshot. Returns grounded findings; each element in
 * finding.elements that matched a real detected element carries its `box`
 * (boundingBox) so the caller can crop the specific region it refers to.
 */
async function critiqueScreenshot({ imageBase64, imageMimeType, elements = [], url, task,
  personaSummary, options = {} }) {
  const apiKey = options.apiKey || process.env.OPENAI_API_KEY || process.env.BLABLADOR_API_KEY;
  const baseUrl = options.baseUrl || process.env.OPENAI_COMPATIBLE_ENDPOINT || process.env.OPENAI_BASE_URL || process.env.BLABLADOR_BASE_URL;
  const model = options.model || process.env.OPENAI_MODEL || "auto";
  if (!apiKey || !baseUrl) {
    throw new VisionUnavailableError(
      "OPENAI_API_KEY/OPENAI_BASE_URL (or BLABLADOR_* aliases) are required for vision critique",
      503, "vision_not_configured");
  }
  const { system, user } = buildPrompt({ url, task, personaSummary, elements,
    capture: captureSize(imageBase64) });
  // The producer downscales and re-encodes before sending, so the bytes are not
  // necessarily PNG any more; mislabelling them breaks strict providers.
  const { content, truncated } = await completeVision({ systemPrompt: system, userText: user, imageBase64,
    model, apiKey, baseUrl, mimeType: imageMimeType || "image/png",
    maxAttempts: options.maxAttempts, retryWaitMs: options.retryWaitMs, timeoutMs: options.timeoutMs });
  const { issues, strengths } = parseCritique(content, { truncated, elements });
  const byId = new Map(elements.map((element) => [element.selector, element]));
  const resolve = (refs) => refs.map((ref) => {
    const matched = byId.get(ref.elementSelector);
    return { elementSelector: ref.elementSelector, role: ref.role, box: matched?.boundingBox || null };
  });
  const provider = new CuratedUXKnowledgeProvider();
  const findings = await Promise.all(issues.map(async (finding) => {
    const resolvedElements = resolve(finding.elements);
    const primaryRole = resolvedElements.find((element) => element.role === "trigger")?.role;
    const grounding = await groundPainPoint({ diagnosis: { category: GROUNDING_CATEGORY_MAP[finding.category] || finding.category },
      elements: resolvedElements.length ? [{ role: primaryRole || resolvedElements[0].role }] : [] }, provider);
    return { ...finding, elements: resolvedElements, grounding };
  }));
  return { findings, strengths: strengths.map((item) => ({ ...item, elements: resolve(item.elements) })) };
}

/**
 * Shape one grounded critique finding into the full UXPainPoint record
 * aggregate.js's aggregateCohort() expects, given the run/persona context
 * Python has (executor.py's _vision_critique_journeys).
 */
function toPainPoint(finding, context) {
  const { runId, userId, route, stepId, screenshotRef, videoTimestampMs = 0 } = context;
  const signatureElements = finding.elements.map((element) => element.elementSelector).sort().join(",");
  const signature = `${runId}:${finding.title}:${signatureElements}`;
  const id = `pain_${createHash("sha256").update(signature).digest("hex").slice(0, 20)}`;
  const confidence = 0.7; // vision-model judgment on a single screenshot, not a repeated measurement
  return {
    id, runId, userId, route, stepIds: [stepId],
    title: finding.title, summary: finding.description,
    severity: finding.severity, category: finding.category,
    confidence, screenshotRef, videoTimestampMs,
    behavioralImpact: { frustrationDelta: finding.estimatedImpact.frustration, confusionDelta: finding.estimatedImpact.confusion,
      trustDelta: -finding.estimatedImpact.trust, cognitiveEffortDelta: 0, physicalEffortDelta: 0,
      elapsedCostMs: 0, retries: 0, backtracks: 0 },
    elements: finding.elements.map((element) => ({ elementId: element.elementSelector, box: element.box,
      role: element.role, contribution: element.role === "trigger" ? 1 : 0.7, confidence })),
    diagnosis: { category: finding.category, mechanism: finding.description, rootCause: finding.title,
      observedEvidence: [`vision critique of ${screenshotRef || "screenshot"}`], behavioralEvidence: [],
      personaInteraction: "Impact is a vision-model estimate from a single screenshot, not a measured behavior transition.",
      confidence },
    grounding: finding.grounding, alternatives: finding.alternatives.map((alternative, index) => ({
      id: `${id}_alt_${index}`, title: `${finding.category} alternative`, strategy: finding.category,
      proposedChange: alternative.proposedChange, rationale: alternative.rationale || "",
      addressesPainPointIds: [id], expectedImpact: { frustration: "lower", confusion: "lower", taskSuccess: "higher" },
      effort: alternative.effort, confidence, grounding: (finding.grounding?.references) || [],
    })),
    overlays: finding.elements.filter((element) => element.box).map((element) => ({ elementId: element.elementSelector,
      box: element.box, modes: { frustration: finding.estimatedImpact.frustration, confusion: finding.estimatedImpact.confusion,
        repeatedAction: 0 }, metricVersion: "vision-critique-v1" })),
  };
}

module.exports = {
  buildPrompt, captureSize, DEFAULT_VISION_MAX_TOKENS, completeObjectsIn, salvageTruncatedCritique, visionMaxTokens,
  critiqueScreenshot, toPainPoint, buildPrompt, parseFindings, parseCritique,
  VisionUnavailableError, FINDING_CATEGORIES, ELEMENT_ROLES,
  unreachable, UNREACHABLE_ATTEMPTS, describeFailure };
