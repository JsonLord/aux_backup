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
 *     boundingBox from journeytest-core's snapshot) so a specific finding can
 *     be tied to a specific place on the screenshot, then grounded against a
 *     small curated UX-heuristics corpus (knowledge.js).
 *
 * Uses the same OpenAI-compatible endpoint already configured for the rest of
 * this deployment (OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL) -- verified
 * live to support image input (see docs/aux-space-status-overview.md).
 */
const { CuratedUXKnowledgeProvider, groundPainPoint } = require("./knowledge");

const FINDING_CATEGORIES = ["accessibility", "usability", "visual_design", "copy", "navigation"];
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
      + "(no markdown fences, no commentary), where each item is "
      + `{"category": one of ${JSON.stringify(FINDING_CATEGORIES)}, "severity": "low"|"medium"|"high"|"critical", `
      + '"elementSelector": the exact selector string from the numbered list below this finding is about, '
      + 'or null for a page-wide finding, "title": short finding title, "description": what is wrong and '
      + 'why, "recommendation": a specific, actionable fix}. Return an empty array [] if you see no real '
      + "issues -- do not invent problems to fill the array.",
    user: `Target URL: ${url}\nTask the synthetic user was attempting: ${task}\n`
      + (personaSummary ? `Synthetic user: ${personaSummary}\n` : "")
      + `\nInteractive elements detected on this screenshot (index, selector, role, visible text, bounding box in CSS pixels):\n${elementList || "(none detected)"}\n\n`
      + "Critique the attached screenshot for real, specific UX/accessibility/visual-design/copy/navigation issues.",
  };
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
      elementSelector: typeof item.elementSelector === "string" ? item.elementSelector : null,
      title: String(item.title), description: String(item.description),
      recommendation: item.recommendation ? String(item.recommendation) : undefined,
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
    max_tokens: 2000,
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
 * Critique one screenshot. Returns grounded findings, each optionally carrying
 * a `box` (the matched element's boundingBox) so the caller can crop the
 * specific region of the screenshot the finding refers to.
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
    const element = finding.elementSelector ? byId.get(finding.elementSelector) : undefined;
    const grounding = await groundPainPoint({ diagnosis: { category: GROUNDING_CATEGORY_MAP[finding.category] || finding.category },
      elements: element ? [{ role: element.role }] : [] }, provider);
    return { ...finding, box: element?.boundingBox || null, grounding };
  }));
}

module.exports = { critiqueScreenshot, buildPrompt, parseFindings, FINDING_CATEGORIES };
