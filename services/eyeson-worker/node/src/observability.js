"use strict";
const { performance } = require("node:perf_hooks");

class StructuredTracer {
  constructor(sink) { this.sink = sink || { record() {} }; }
  async trace(name, correlation, operation) {
    const started = performance.now();
    try {
      const result = await operation();
      this.sink.record({ name, status: "ok", latencyMs: Number((performance.now() - started).toFixed(3)),
        correlation, output: result.traceOutput, model: result.model, confidence: result.confidence });
      return result.value;
    } catch (error) {
      this.sink.record({ name, status: "failed", latencyMs: Number((performance.now() - started).toFixed(3)),
        correlation, error: { name: error.name, message: error.message } });
      throw error;
    }
  }
}

module.exports = { StructuredTracer };
