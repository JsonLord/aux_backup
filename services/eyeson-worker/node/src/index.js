"use strict";
const http = require("node:http");
const { createHash } = require("node:crypto");
const { generateAlternatives } = require("./alternatives");
const { resolvePainEpisodes } = require("./painResolver");
const { renderReport } = require("./report");
const { enrichRun, renderMarkdown } = require("./enricher");
const { CuratedUXKnowledgeProvider, applyGrounding } = require("./knowledge");
const { AnalysisQueue, selectScreenBudget } = require("./scheduler");
const { createAlternativeLineage, addValidationRun } = require("./lineage");
const { StructuredTracer } = require("./observability");
const { redactArtifact } = require("./privacy");
const { critiqueScreenshot, toPainPoint } = require("./visionCritique");
const { aggregateCohort } = require("./aggregate");

const tracer = new StructuredTracer();
const analysisQueue = new AnalysisQueue({ concurrency: Number(process.env.ANALYSIS_CONCURRENCY || 2),
  analyze: ({ evidence, options }) => tracer.trace("eyeson.diagnosis", {
    runId: evidence.runId, userId: evidence.userId, stepId: evidence.stepId,
  }, async () => { const value = analyzeEvidence(evidence, options); return { value,
    traceOutput: { analysisId: value.analysisId, painPointIds: value.painPoints.map((item) => item.id) },
    confidence: value.painPoints[0]?.confidence }; }) });

function analyzeEvidence(evidence, options = {}) {
  if (evidence?.schemaVersion !== "1.0" || !evidence.screenshot?.artifactId) {
    throw new Error("versioned evidence with a screenshot artifact reference is required");
  }
  if (!Array.isArray(evidence.elementMap?.elements)) throw new Error("elementMap.elements is required");
  if (!evidence.behavior?.before || !evidence.behavior?.after) throw new Error("behavior transition is required");
  const anchor = evidence.elementMap.elements[0];
  const analysisId = `eyeson_${createHash("sha256").update(`${evidence.id}:${evidence.screenshot.artifactId}`).digest("hex").slice(0, 20)}`;
  const painPoints = resolvePainEpisodes([evidence]);
  for (const painPoint of painPoints) painPoint.alternatives = generateAlternatives(painPoint, options);
  return { schemaVersion: "1.0", analysisId, evidenceId: evidence.id, runId: evidence.runId,
    stepId: evidence.stepId, timestampMs: evidence.timestampMs, screenshot: evidence.screenshot,
    findings: [{ id: `${analysisId}_finding_1`, category: "evidence_review", severity: "info",
      summary: "Screenshot queued with synchronized behavior and semantic element evidence.",
      elementIds: anchor?.id ? [anchor.id] : [], evidenceRefs: [evidence.screenshot.artifactId],
      confidence: 1, language: "observed-input" }], painPoints,
    limitations: ["PLACEHOLDER: deep visual critique awaits migration of the pinned Eyeson engine into this worker boundary."] };
}

function json(response, status, value) {
  response.writeHead(status, { "content-type": "application/json" });
  response.end(JSON.stringify(value));
}

async function body(request) {
  const chunks = [];
  for await (const chunk of request) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}");
}

const server = http.createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/healthz") return json(response, 200, { service: "eyeson-worker", status: "ready", version: "0.1.0" });
    if (request.method === "POST" && request.url === "/v1/evidence-analyses") {
      const payload = await body(request);
      const evidence = redactArtifact(payload.evidence);
      return json(response, 201, await analysisQueue.enqueue({ runId: evidence.runId, evidence, options: payload.options }));
    }
    if (request.method === "POST" && request.url === "/v1/journey-evidence-analyses") {
      // Real vision-based UX critique of a live JourneyTest screenshot -- see
      // visionCritique.js. Distinct from /v1/evidence-analyses, which requires
      // the native fixture engine's elementMap/behavior-transition evidence
      // contract that live JourneyTest runs don't produce.
      const payload = await body(request);
      if (!payload.imageBase64) return json(response, 422, { error: "invalid_request", message: "imageBase64 is required" });
      const findings = await critiqueScreenshot({ imageBase64: payload.imageBase64, elements: payload.elements,
        url: payload.url, task: payload.task, personaSummary: payload.personaSummary, options: payload.options });
      const context = { runId: payload.runId, userId: payload.userId, route: payload.url,
        stepId: payload.stepId, screenshotRef: payload.screenshotRef, videoTimestampMs: payload.videoTimestampMs };
      const painPoints = findings.map((finding) => toPainPoint(finding, context));
      return json(response, 201, { schemaVersion: "1.0", findings, painPoints });
    }
    if (request.method === "POST" && request.url === "/v1/cohort-aggregation") {
      // Real cross-persona synthesis (aggregate.js's aggregateCohort, already
      // built and tested, previously unused since it targets the native fixture
      // engine's run shape). Accepts one "cohort run" per persona --
      // {runId, profileId, iterationId, verdict, simulationProfile, painPoints}
      // -- painPoints being the UXPainPoint records visionCritique.js's
      // toPainPoint() already produces. Groups pain points into root causes by
      // shared route/elements/category/mechanism, across every persona in the
      // run: this is the "synthesized data analysis, not individual persona
      // testing thought citations" result, not a per-persona listing.
      const payload = await body(request);
      const runs = Array.isArray(payload.runs) ? payload.runs : [];
      return json(response, 201, { schemaVersion: "1.0", rootCauses: aggregateCohort(runs) });
    }
    if (request.method === "POST" && request.url === "/v1/evidence-batches") {
      const payload = await body(request);
      const selected = selectScreenBudget(redactArtifact(payload.candidates || []), payload.screenBudget);
      const analyses = await Promise.all(selected.map((evidence) => analysisQueue.enqueue({
        runId: payload.runId || evidence.runId, evidence, options: payload.options })));
      await analysisQueue.flush(payload.runId || selected[0]?.runId);
      return json(response, 201, { schemaVersion: "1.0", runId: payload.runId,
        analysisStatus: "completed", selectedEvidenceIds: selected.map((item) => item.id), analyses });
    }
    if (request.method === "POST" && request.url === "/v1/reports") {
      const payload = await body(request);
      response.writeHead(201, { "content-type": "text/html; charset=utf-8" });
      return response.end(renderReport(payload.run, payload.cohortRuns));
    }
    if (request.method === "POST" && request.url === "/v1/runs/enrich") {
      const payload = await body(request);
      const run = enrichRun(payload.run);
      return json(response, 201, { run, reportMarkdown: renderMarkdown(run) });
    }
    if (request.method === "POST" && request.url === "/v1/ground") {
      const payload = await body(request);
      return json(response, 201, await applyGrounding(payload.painPoint, new CuratedUXKnowledgeProvider()));
    }
    if (request.method === "POST" && request.url === "/v1/alternative-lineage") {
      return json(response, 201, createAlternativeLineage(await body(request)));
    }
    if (request.method === "POST" && request.url === "/v1/alternative-lineage/validations") {
      const payload = await body(request);
      return json(response, 201, addValidationRun(payload.lineage, payload.validationRunId));
    }
    return json(response, 404, { error: "not_found" });
  } catch (error) {
    return json(response, 422, { error: "invalid_evidence", message: error.message });
  }
});
if (require.main === module) server.listen(Number(process.env.PORT || 8081), "0.0.0.0");

module.exports = { analyzeEvidence, renderReport };
