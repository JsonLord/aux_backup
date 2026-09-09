"use strict";

function createAlternativeLineage(input) {
  if (!input.sourceRunId || !input.painPointId || !input.alternativeId) {
    throw new Error("sourceRunId, painPointId, and alternativeId are required");
  }
  return { schemaVersion: "1.0", sourceRunId: input.sourceRunId, painPointId: input.painPointId,
    alternativeId: input.alternativeId, validationRunIds: [...new Set(input.validationRunIds || [])],
    validationStatus: input.validationRunIds?.length ? "rerun_recorded" : "not_validated" };
}

function addValidationRun(link, validationRunId) {
  if (link?.schemaVersion !== "1.0" || !validationRunId) {
    throw new Error("versioned lineage and validationRunId are required");
  }
  return { ...structuredClone(link), validationRunIds: [...new Set([...link.validationRunIds, validationRunId])],
    validationStatus: "rerun_recorded" };
}

module.exports = { createAlternativeLineage, addValidationRun };
