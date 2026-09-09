"use strict";

const priority = { frustration_spike: 100, explicit_error: 90, abandonment: 80,
  route_change: 70, bookmark: 60, representative: 10 };

function selectScreenBudget(candidates, budget) {
  const maximum = Math.max(0, Math.floor(Number(budget) || candidates.length));
  return candidates.map((candidate, index) => ({ candidate, index,
    score: priority[candidate.selectionReason] || priority.representative }))
    .sort((a, b) => b.score - a.score || a.index - b.index).slice(0, maximum)
    .sort((a, b) => a.index - b.index).map(({ candidate }) => candidate);
}

class AnalysisQueue {
  constructor({ concurrency = 2, analyze }) {
    if (typeof analyze !== "function") throw new Error("analyze callback is required");
    this.concurrency = Math.max(1, Math.floor(concurrency));
    this.analyze = analyze;
    this.pending = [];
    this.active = 0;
    this.byRun = new Map();
  }

  enqueue(job) {
    const promise = new Promise((resolve, reject) => this.pending.push({ job, resolve, reject }));
    const runJobs = this.byRun.get(job.runId) || [];
    runJobs.push(promise.catch(() => undefined));
    this.byRun.set(job.runId, runJobs);
    this.drain();
    return promise;
  }

  drain() {
    while (this.active < this.concurrency && this.pending.length) {
      const item = this.pending.shift();
      this.active += 1;
      Promise.resolve(this.analyze(item.job)).then(item.resolve, item.reject).finally(() => {
        this.active -= 1;
        this.drain();
      });
    }
  }

  async flush(runId) {
    await Promise.all(this.byRun.get(runId) || []);
    this.byRun.delete(runId);
  }
}

module.exports = { AnalysisQueue, selectScreenBudget };
