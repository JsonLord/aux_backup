"use strict";
/**
 * Whose model budget a run spends (BE-1d).
 *
 * The control plane resolves a chain per run -- this workspace's own providers,
 * and the deployment's only when that caller is allowed them -- and sends it in
 * the run body. These assert the refusals, because the happy path passed before
 * the chain existed too.
 */

const test = require("node:test");
const assert = require("node:assert/strict");

const { modelChain, runWithJourneyTest } = require("../src/journeytest");
const { redactSensitive } = require("../src/safety");

const CHAIN = [
  { baseUrl: "https://mine.example/v1", model: "my-model", apiKey: "sk-mine" },
  { baseUrl: "https://spare.example/v1", model: "spare-model", apiKey: "sk-spare" },
];

test("a run is handed the chain the control plane resolved for it", () => {
  const chain = modelChain({ models: { acting: CHAIN } }, "acting");

  assert.deepEqual(chain.map((entry) => entry.model), ["my-model", "spare-model"]);
  assert.equal(chain[0].apiKey, "sk-mine");
});

test("a trailing slash on an endpoint is one endpoint, not two", () => {
  const [entry] = modelChain(
    { models: { acting: [{ baseUrl: "https://mine.example/v1/", model: "m", apiKey: "k" }] } },
    "acting");

  assert.equal(entry.baseUrl, "https://mine.example/v1");
});

test("an entry missing its key, model or endpoint is dropped rather than half-used", () => {
  // A model, an endpoint and a key are one setting: an alias without its token
  // looks like a fallback and is a 401 on every call.
  const chain = modelChain({ models: { acting: [
    { baseUrl: "https://a.example/v1", model: "a" },                    // no key
    { baseUrl: "https://b.example/v1", apiKey: "sk-b" },                // no model
    { model: "c", apiKey: "sk-c" },                                     // no endpoint
    { baseUrl: "https://d.example/v1", model: "d", apiKey: "sk-d" },    // whole
  ] } }, "acting");

  assert.deepEqual(chain.map((entry) => entry.model), ["d"]);
});

test("a role the run was given nothing for is empty, not the host's environment", () => {
  assert.deepEqual(modelChain({ models: { acting: CHAIN } }, "reflection"), []);
  assert.deepEqual(modelChain({ models: {} }, "acting"), []);
  assert.deepEqual(modelChain({}, "acting"), []);
});

test("a routed run with nothing to act with is refused, not served from the environment", async () => {
  // The rail. This worker's environment holds the deployment's own credentials,
  // and a run that was told it may not use them must not reach them here.
  process.env.JOURNEY_ENGINE = "journeytest";
  process.env.JOURNEY_MODEL = "the-deployments-model";
  process.env.OPENAI_API_KEY = "sk-the-deployments-own";
  process.env.OPENAI_BASE_URL = "https://built-in.example/v1";

  await assert.rejects(
    () => runWithJourneyTest({ url: "https://example.com", tasks: ["t"],
      profile: { id: "p", behavior: {} }, models: { acting: [] } }),
    (error) => {
      assert.match(error.message, /no model provider/i);
      assert.doesNotMatch(error.message, /sk-the-deployments-own/);
      return true;
    });
});

test("a key handed to a run never survives what the recorder writes", () => {
  // Keys travel in the run body, over loopback. Nothing may record them, and
  // redactSensitive is what everything written about a step passes through.
  const recorded = redactSensitive({
    runId: "run_1",
    models: { acting: [{ baseUrl: "https://mine.example/v1", model: "m", apiKey: "sk-mine" }] },
  });

  assert.equal(JSON.stringify(recorded).includes("sk-mine"), false);
});
