"use strict";
const { createHash } = require("node:crypto");

const strategies = {
  validation_failure: [
    ["feedback", "Keep validation feedback adjacent to the field until it is resolved.", "Persistent contextual feedback makes the recovery path visible.", "low"],
    ["copy", "State the required format and provide a valid example before submission.", "Specific instructions reduce interpretation and repeated failure.", "low"],
  ],
  ambiguous_feedback: [
    ["feedback", "Show a persistent processing state with explicit progress or completion criteria.", "System-status feedback distinguishes waiting from failure.", "medium"],
    ["interaction", "Disable duplicate submission while preserving a visible cancel or recovery action.", "Guarding the action prevents accidental repeated requests.", "medium"],
  ],
};

function generateAlternatives(painPoint, options = {}) {
  const templates = strategies[painPoint.diagnosis.category] || [["interaction",
    `Provide a specific recovery path for ${painPoint.elements[0]?.elementId || "the affected control"}.`,
    "A recovery path directly addresses the observed blocked interaction.", "medium"]];
  return templates.map(([strategy, proposedChange, rationale, effort], index) => {
    const id = `alternative_${createHash("sha256").update(`${painPoint.id}:${strategy}:${index}`).digest("hex").slice(0, 16)}`;
    return { id, title: `${strategy[0].toUpperCase()}${strategy.slice(1)} alternative`, strategy,
      proposedChange, rationale, addressesPainPointIds: [painPoint.id],
      expectedImpact: { frustration: "lower", confusion: "lower", taskSuccess: "higher" },
      effort, confidence: painPoint.confidence, grounding: painPoint.grounding?.references || [],
      ...(options.generateVisualSolutions ? { visualAlternative: {
        originalScreenshotRef: painPoint.screenshotRef, targetElementIds: painPoint.elements.map((item) => item.elementId),
        provider: "html-css-sandbox-placeholder" } } : {}) };
  });
}

module.exports = { generateAlternatives };
