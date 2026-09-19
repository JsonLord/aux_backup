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

const { modelChain, runWithJourneyTest, servedBy } = require("../src/journeytest");
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


test("what served the run is reported as a host and a model, never as a key", () => {
  // This lands in a journey log a person can download, and a base URL can carry
  // a key in its query string -- so the path goes too, not just the header.
  const record = servedBy({ actingOn: () => ({
    model: "my-model", apiKey: "sk-must-not-appear",
    baseUrl: "https://router.example/v1?token=sk-also-not" }) });

  assert.deepEqual(record, { endpoint: "https://router.example", model: "my-model",
    movedFromPrimary: false });
  assert.equal(JSON.stringify(record).includes("sk-"), false);
});

test("a run that moved to its fallback says so", () => {
  const record = servedBy({ actingOn: () => ({
    model: "spare", apiKey: "sk-x", baseUrl: "https://primary.example/v1",
    movedTo: "https://spare.example/v1" }) });

  assert.equal(record.endpoint, "https://spare.example");
  assert.equal(record.movedFromPrimary, true);
});

test("a run that never reached a model reports nothing rather than a blank row", () => {
  assert.equal(servedBy(null), undefined);
  assert.equal(servedBy({ actingOn: () => ({ model: "m" }) }), undefined);
  assert.equal(servedBy({ actingOn: () => ({ baseUrl: "not a url", model: "m" }) }), undefined);
});
