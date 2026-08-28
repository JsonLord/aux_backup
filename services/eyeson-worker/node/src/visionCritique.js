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

const FINDING_CATEGORIES = ["accessibility", "usability", "visual_design", "copy", "navigation"];
const ELEMENT_ROLES = ["trigger", "cause", "feedback", "obstacle", "recovery"];
// Maps this module's finding categories onto knowledge.js's curated-source
// categories (wcag-error-identification etc. are tagged with problem
// categories like "validation_failure"/"ambiguous_feedback"/"navigation_failure").
const GROUNDING_CATEGORY_MAP = { accessibility: "validation_failure", navigation: "navigation_failure",
  usability: "ambiguous_feedback", visual_design: "ambiguous_feedback", copy: "ambiguous_feedback" };

function buildPrompt({ url, task, personaSummary, elements }) {
  const elementList = (elements || []).slice(0, 60).map((element, index) =>
    `${index}. selector="${element.selector}" role=${element.role || element.tag} text="${(element.text || "").slice(0, 80)}" box=${JSON.stringify(element.boundingBox || {})}`,
  ).join("\n");
  return {
    system: "You are a senior UX and accessibility reviewer critiquing a real screenshot of a live "
      + "web page. Only report issues you can actually see or infer from the provided element list -- "
      + "never invent elements that are not in the list or in the image. Respond with ONLY a JSON array "
      + "(no markdown fences, no commentary), where each item is:\n"
      + `{"category": one of ${JSON.stringify(FINDING_CATEGORIES)}, "severity": "low"|"medium"|"high"|"critical", `
      + '"title": short finding title, "description": what is wrong and why, '
      + `"elements": [{"elementSelector": exact selector string from the numbered list, "role": one of ${JSON.stringify(ELEMENT_ROLES)}}] `
      + '(empty array for a page-wide finding with no single element to point to), '
      + '"estimatedImpact": {"frustration": 0-1, "confusion": 0-1, "trust": 0-1 (how much this would erode trust)} '
      + '-- your honest estimate of how a real user would react, not a fixed value, '
      + '"alternatives": [{"proposedChange": a specific, actionable fix, "rationale": why it would help, '
      + '"effort": "low"|"medium"|"high"}] (1-2 alternatives; omit only if you truly have none)}. '
      + "Return an empty array [] if you see no real issues -- do not invent problems to fill the array.",
    user: `Target URL: ${url}\nTask the synthetic user was attempting: ${task}\n`
      + (personaSummary ? `Synthetic user: ${personaSummary}\n` : "")
      + `\nInteractive elements detected on this screenshot (index, selector, role, visible text, bounding box in CSS pixels):\n${elementList || "(none detected)"}\n\n`
      + "Critique the attached screenshot for real, specific UX/accessibility/visual-design/copy/navigation issues.",
  };
}

function clamp01(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.min(1, number)) : fallback;
}

function parseFindings(content) {
  let stripped = content.trim();
  if (stripped.startsWith("```")) {
    stripped = stripped.replace(/^```[a-zA-Z]*\n?/, "").replace(/\n?```\s*$/, "").trim();
  }
  const match = stripped.match(/\[[\s\S]*\]/);
  const parsed = JSON.parse(match ? match[0] : stripped);
  if (!Array.isArray(parsed)) throw new Error("vision critique did not return a JSON array");
  return parsed.filter((item) => item && typeof item === "object" && item.title && item.description)
    .map((item) => ({
      category: FINDING_CATEGORIES.includes(item.category) ? item.category : "usability",
      severity: ["low", "medium", "high", "critical"].includes(item.severity) ? item.severity : "medium",
      title: String(item.title), description: String(item.description),
      elements: Array.isArray(item.elements) ? item.elements
        .filter((element) => element && typeof element.elementSelector === "string")
        .map((element) => ({ elementSelector: element.elementSelector,
          role: ELEMENT_ROLES.includes(element.role) ? element.role : "cause" }))
        : [],
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
    max_tokens: 2500,
  };
  let lastError;
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(`${baseUrl.replace(/\/$/, "")}/chat/completions`, {
        method: "POST", signal: controller.signal,
        headers: { "content-type": "application/json", authorization: `Bearer ${apiKey}` },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`vision endpoint returned HTTP ${response.status}: ${(await response.text()).slice(0, 500)}`);
      const data = await response.json();
      const content = data.choices?.[0]?.message?.content;
      if (!content || !content.trim()) throw new Error("vision endpoint returned an empty completion");
      return content;
    } catch (error) {
      lastError = error;
      if (attempt < maxAttempts) await new Promise((resolve) => setTimeout(resolve, retryWaitMs * attempt));
    } finally {
      clearTimeout(timeout);
    }
  }
  throw new Error(`vision critique failed after ${maxAttempts} attempts: ${lastError?.message}`);
}

/**
 * Critique one screenshot. Returns grounded findings; each element in
 * finding.elements that matched a real detected element carries its `box`
 * (boundingBox) so the caller can crop the specific region it refers to.
 */
async function critiqueScreenshot({ imageBase64, elements = [], url, task, personaSummary, options = {} }) {
  const apiKey = options.apiKey || process.env.OPENAI_API_KEY || process.env.BLABLADOR_API_KEY;
  const baseUrl = options.baseUrl || process.env.OPENAI_COMPATIBLE_ENDPOINT || process.env.OPENAI_BASE_URL || process.env.BLABLADOR_BASE_URL;
  const model = options.model || process.env.OPENAI_MODEL || "auto";
  if (!apiKey || !baseUrl) throw new Error("OPENAI_API_KEY/OPENAI_BASE_URL (or BLABLADOR_* aliases) are required for vision critique");
  const { system, user } = buildPrompt({ url, task, personaSummary, elements });
  const content = await completeVision({ systemPrompt: system, userText: user, imageBase64, model, apiKey, baseUrl,
    maxAttempts: options.maxAttempts, retryWaitMs: options.retryWaitMs, timeoutMs: options.timeoutMs });
  const findings = parseFindings(content);
  const byId = new Map(elements.map((element) => [element.selector, element]));
  const provider = new CuratedUXKnowledgeProvider();
  return Promise.all(findings.map(async (finding) => {
    const resolvedElements = finding.elements.map((ref) => {
      const matched = byId.get(ref.elementSelector);
      return { elementSelector: ref.elementSelector, role: ref.role, box: matched?.boundingBox || null };
    });
    const primaryRole = resolvedElements.find((element) => element.role === "trigger")?.role;
    const grounding = await groundPainPoint({ diagnosis: { category: GROUNDING_CATEGORY_MAP[finding.category] || finding.category },
      elements: resolvedElements.length ? [{ role: primaryRole || resolvedElements[0].role }] : [] }, provider);
    return { ...finding, elements: resolvedElements, grounding };
  }));
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

module.exports = { critiqueScreenshot, toPainPoint, buildPrompt, parseFindings, FINDING_CATEGORIES, ELEMENT_ROLES };
