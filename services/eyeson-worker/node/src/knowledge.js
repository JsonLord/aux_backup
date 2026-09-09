"use strict";

class NullUXKnowledgeProvider {
  async search() { return []; }
}

const CURATED_SOURCES = [
  { id: "wcag-error-identification", source: "W3C Web Accessibility Initiative", title: "WCAG 2.2 — Error Identification",
    framework: "wcag", principle: "3.3.1 Error Identification", content: "Identify input errors and describe them to the user in text.",
    sourceUrl: "https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html", categories: ["validation_failure", "user_error"] },
  { id: "wcag-status-messages", source: "W3C Web Accessibility Initiative", title: "WCAG 2.2 — Status Messages",
    framework: "wcag", principle: "4.1.3 Status Messages", content: "Expose status messages without requiring focus movement.",
    sourceUrl: "https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html", categories: ["ambiguous_feedback", "waiting", "progress"] },
  { id: "nng-system-status", source: "Nielsen Norman Group", title: "Visibility of System Status",
    framework: "nielsen", principle: "Usability heuristic 1", content: "Keep users informed about what is happening through timely feedback.",
    sourceUrl: "https://www.nngroup.com/articles/ten-usability-heuristics/", categories: ["ambiguous_feedback", "waiting", "navigation_failure"] },
];

class CuratedUXKnowledgeProvider {
  constructor(sources = CURATED_SOURCES) { this.sources = sources; }
  async search(query) {
    const categories = new Set(query.problemCategories || [query.painPoint?.diagnosis?.category].filter(Boolean));
    return this.sources.map((source) => ({ ...source,
      relevance: source.categories.some((category) => categories.has(category)) ? 1 : .25 }))
      .filter((source) => source.relevance >= .5).sort((a, b) => b.relevance - a.relevance)
      .map(({ categories: _categories, ...source }) => source);
  }
}

async function groundPainPoint(painPoint, provider = new NullUXKnowledgeProvider()) {
  const references = await provider.search({ painPoint, problemCategories: [painPoint.diagnosis.category],
    elementType: painPoint.elements[0]?.role });
  return { status: provider instanceof NullUXKnowledgeProvider ? "not_configured" : "completed", references };
}

async function applyGrounding(painPoint, provider) {
  const grounding = await groundPainPoint(painPoint, provider);
  return { ...painPoint, grounding, alternatives: (painPoint.alternatives || []).map((alternative) => ({
    ...alternative, grounding: grounding.references,
  })), claimLanguage: { observed: painPoint.diagnosis.observedEvidence,
    inferred: [painPoint.diagnosis.rootCause, painPoint.diagnosis.mechanism],
    grounded: grounding.references.map((reference) => `${reference.source}: ${reference.principle || reference.title}`),
    proposed: (painPoint.alternatives || []).map((alternative) => alternative.proposedChange) } };
}

module.exports = { NullUXKnowledgeProvider, CuratedUXKnowledgeProvider, CURATED_SOURCES, groundPainPoint, applyGrounding };
