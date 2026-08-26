"use strict";
const { perceivedScreenshot } = require("./physical");
const { redactSensitive } = require("./safety");

const EVIDENCE_SCHEMA_VERSION = "1.0";

function artifactRef(value, field) {
  if (!value || typeof value !== "object" || !value.artifactId || !value.kind) {
    throw new Error(`${field} must be an artifact reference with artifactId and kind`);
  }
  return { ...value };
}

function normalizeStepEvidence(value, run, step, transition) {
  if (!value?.screenshot) return undefined;
  if (!value.elementMap || !Array.isArray(value.elementMap.elements)) {
    throw new Error("selected screenshot evidence requires elementMap.elements");
  }
  const elementIds = value.elementMap.elements.map((element) => element.id);
  if (elementIds.some((id) => !id) || new Set(elementIds).size !== elementIds.length) {
    throw new Error("elementMap elements require unique stable ids");
  }
  return {
    schemaVersion: EVIDENCE_SCHEMA_VERSION,
    id: value.id || `${run.runId}_evidence_${step.index + 1}`,
    runId: run.runId, userId: run.profileId,
    iterationId: value.iterationId || `${run.runId}_iteration_1`,
    step: step.index + 1, stepId: step.stepId,
    timestampMs: Number(value.timestampMs ?? step.index),
    action: redactSensitive(value.action || { type: "task", description: String(step.task) }),
    screenshot: artifactRef(value.screenshot, "screenshot"),
    perceivedScreenshot: value.perceivedScreenshot
      ? artifactRef(value.perceivedScreenshot, "perceivedScreenshot")
      : perceivedScreenshot(value.screenshot, run.abilities, run.physicalSeed),
    ...(value.accessibilitySnapshot ? { accessibilitySnapshot: artifactRef(value.accessibilitySnapshot, "accessibilitySnapshot") } : {}),
    ...(value.domSnapshot ? { domSnapshot: artifactRef(value.domSnapshot, "domSnapshot") } : {}),
    ...(value.semanticSnapshot ? { semanticSnapshot: artifactRef(value.semanticSnapshot, "semanticSnapshot") } : {}),
    ...(value.uiChanges ? { uiChanges: artifactRef(value.uiChanges, "uiChanges") } : {}),
    elementMap: structuredClone(value.elementMap),
    behavior: { before: transition.before, events: [transition.event], after: transition.after,
      coping: transition.coping.decision },
    eyeson: { status: "pending" },
  };
}

class EvidenceCoordinator {
  constructor(options = {}) {
    this.endpoint = options.endpoint || process.env.EYESON_WORKER_URL;
    this.analyze = options.analyze || (this.endpoint ? this.httpAnalyze.bind(this) : undefined);
  }

  enqueue(evidence) {
    if (!this.analyze) return Promise.resolve({ ...evidence, eyeson: { status: "pending" } });
    evidence.eyeson = { status: "processing" };
    return Promise.resolve(this.analyze(structuredClone(evidence))).then((analysis) => ({
      ...evidence, eyeson: { status: "completed", analysisId: analysis.analysisId,
        findings: analysis.findings || [], painPoints: analysis.painPoints || [] },
    })).catch((error) => ({ ...evidence, eyeson: { status: "failed",
      error: { code: "eyeson_analysis_failed", message: error.message } } }));
  }

  async httpAnalyze(evidence) {
    const response = await fetch(`${this.endpoint.replace(/\/$/, "")}/v1/evidence-analyses`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ evidence }),
    });
    if (!response.ok) throw new Error(`Eyeson returned HTTP ${response.status}`);
    return response.json();
  }
}

module.exports = { EvidenceCoordinator, normalizeStepEvidence, EVIDENCE_SCHEMA_VERSION };
