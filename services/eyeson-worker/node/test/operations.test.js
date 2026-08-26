"use strict";
const assert = require("node:assert/strict");
const test = require("node:test");
const { AnalysisQueue, selectScreenBudget } = require("../src/scheduler");
const { createAlternativeLineage, addValidationRun } = require("../src/lineage");
const { StructuredTracer } = require("../src/observability");
const { redactArtifact, retentionPolicy } = require("../src/privacy");

test("screen budget uses specified priority and bounded analysis concurrency", async () => {
  const candidates = [{ id: "normal", selectionReason: "representative" },
    { id: "error", selectionReason: "explicit_error" }, { id: "spike", selectionReason: "frustration_spike" }];
  assert.deepEqual(selectScreenBudget(candidates, 2).map((item) => item.id), ["error", "spike"]);
  let active = 0, maximum = 0;
  const queue = new AnalysisQueue({ concurrency: 2, analyze: async (job) => {
    active += 1; maximum = Math.max(maximum, active);
    await new Promise((resolve) => setTimeout(resolve, 5));
    active -= 1; return job.id;
  } });
  const results = await Promise.all([1, 2, 3, 4].map((id) => queue.enqueue({ id, runId: "run-1" })));
  await queue.flush("run-1");
  assert.deepEqual(results, [1, 2, 3, 4]);
  assert.equal(maximum, 2);
});

test("alternative lineage never labels impact validated before a rerun", () => {
  const link = createAlternativeLineage({ sourceRunId: "run-1", painPointId: "pain-1", alternativeId: "alt-1" });
  assert.equal(link.validationStatus, "not_validated");
  const validated = addValidationRun(link, "run-validation-1");
  assert.equal(validated.validationStatus, "rerun_recorded");
  assert.deepEqual(validated.validationRunIds, ["run-validation-1"]);
});

test("structured tracing records explicit outputs and correlation without rationale internals", async () => {
  const records = [];
  const tracer = new StructuredTracer({ record: (record) => records.push(record) });
  const value = await tracer.trace("diagnosis", { runId: "run-1", stepId: "step-1" }, async () => ({
    value: { id: "pain-1" }, traceOutput: { observation: "validation error", mechanism: "blocked progress" },
    model: "native-v1", confidence: .9 }));
  assert.deepEqual(value, { id: "pain-1" });
  assert.deepEqual(records[0].output, { observation: "validation error", mechanism: "blocked progress" });
  assert.equal("chainOfThought" in records[0], false);
});

test("privacy redaction and retention policies protect artifacts", () => {
  const redacted = redactArtifact({ username: "tester", password: "unsafe", nested: { authorization: "Bearer abc" },
    form: { inputType: "password", value: "unsafe", elementId: "password" } });
  assert.deepEqual(redacted, { username: "tester", password: "[REDACTED]", nested: { authorization: "[REDACTED]" },
    form: { inputType: "password", value: "[REDACTED]", elementId: "password" } });
  assert.equal(retentionPolicy("evidence.screenshot").expiresInDays, 30);
  assert.equal(retentionPolicy("ux.report").expiresInDays, 180);
  assert.deepEqual(retentionPolicy("evidence.screenshot", { localOnly: true }),
    { storage: "local", expiresInDays: null, uploadAllowed: false });
});
