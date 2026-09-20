"use strict";
/**
 * CAP-5: the safety design is the feature, not a wrapper around it. One test
 * per rail, each asserting the refusal rather than the success -- per the
 * detail spec's own "Tests that prove the rail" list.
 */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const { DeveloperTool } = require("../src/developerTool");
const { facultyWith } = require("../src/faculty");

function scratchDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "aux-developer-test-"));
}

function fakeRecorder() {
  const events = [];
  return { events, async record(type, summary, data) { events.push({ type, summary, data }); } };
}

test("a command off the allowlist is refused", async () => {
  const tool = new DeveloperTool({ allowCommands: ["echo"], scratchDir: scratchDir() });
  const recorder = fakeRecorder();

  const result = await tool.processAction({ type: "RUN", target: "rm", content: "-rf /" },
    { recorder });

  assert.equal(result.failed, true);
  assert.match(result.error, /not on this run's command allowlist/);
  assert.equal(recorder.events[0].data.failed, true, "the refusal is evidence too");
});

test("a path outside the scratch directory is refused", async () => {
  const dir = scratchDir();
  const tool = new DeveloperTool({ allowCommands: [], scratchDir: dir });

  const result = await tool.processAction({ type: "INSPECT", target: "../../etc/passwd" },
    { recorder: fakeRecorder() });

  assert.equal(result.failed, true);
  assert.match(result.error, /outside this run's scratch directory/);
});

test("the child environment contains no key present in the parent", async () => {
  process.env.AUX_DEVELOPER_TEST_SECRET = "leak-me-not";
  try {
    const tool = new DeveloperTool({ allowCommands: [process.execPath], scratchDir: scratchDir() });
    const result = await tool.processAction(
      { type: "RUN", target: process.execPath, content: "-p process.env.AUX_DEVELOPER_TEST_SECRET" },
      { recorder: fakeRecorder() });

    assert.equal(result.failed, false, `run itself must succeed: ${JSON.stringify(result)}`);
    assert.ok(!result.stdout.includes("leak-me-not"),
      `the parent's env var must not reach the child: ${result.stdout}`);
    assert.match(result.stdout, /undefined/, "an empty environment, not a filtered one");
  } finally {
    delete process.env.AUX_DEVELOPER_TEST_SECRET;
  }
});

test("a request to a private address is refused", async () => {
  const tool = new DeveloperTool({ allowCommands: [], scratchDir: scratchDir() });

  const fetched = await tool.processAction({ type: "FETCH", target: "http://127.0.0.1:9/whatever" },
    { recorder: fakeRecorder() });
  assert.equal(fetched.failed, true);
  assert.match(fetched.error, /private\/local target network/);

  const authenticated = await tool.processAction(
    { type: "AUTHENTICATE", target: "http://169.254.169.254/latest/meta-data", content: "Bearer x" },
    { recorder: fakeRecorder() });
  assert.equal(authenticated.failed, true);
  assert.match(authenticated.error, /private\/local target network/);
});

test("a RUN on a hat without allowCommands finds no such action mounted -- not refused, not mounted", () => {
  const faculty = facultyWith(["developer"], { abilities: {}, seed: 1, grants: {}, scratchDir: scratchDir() });

  assert.ok(!faculty.actionTypes.includes("RUN"), "RUN is absent from what this faculty can even attempt");
  assert.ok(!faculty.actionTypes.includes("FETCH"));
  assert.equal(faculty.tools.length, 2, "only BrowserTool and JourneyTool mounted -- developer never joined them");
});

test("a hat that does grant allowCommands mounts the tool, appended after browsing", () => {
  const dir = scratchDir();
  const faculty = facultyWith(["developer"], { abilities: {}, seed: 1,
    grants: { developer: { allowCommands: ["echo"], hosts: ["example.com"] } }, scratchDir: dir });

  assert.ok(faculty.actionTypes.includes("RUN"));
  assert.ok(faculty.actionTypes.includes("CLICK"), "browsing is still there");
  assert.ok(faculty.tools[faculty.tools.length - 1] instanceof DeveloperTool, "appended last");
});

test("a host outside this run's declared list is refused even when it is not private", async () => {
  const tool = new DeveloperTool({ allowCommands: [], hosts: ["allowed.example.com"], scratchDir: scratchDir() });

  const result = await tool.processAction({ type: "FETCH", target: "https://not-allowed.example.com/file" },
    { recorder: fakeRecorder() });

  assert.equal(result.failed, true);
  assert.match(result.error, /not a host this run declared/);
});

test("every invocation is recorded as evidence, success or failure", async () => {
  const tool = new DeveloperTool({ allowCommands: ["echo"], scratchDir: scratchDir() });
  const recorder = fakeRecorder();

  await tool.processAction({ type: "RUN", target: "not-allowed", content: "" }, { recorder });

  assert.equal(recorder.events.length, 1);
  assert.equal(recorder.events[0].type, "developer.invocation");
  assert.ok(Number.isFinite(recorder.events[0].data.durationMs));
});

test("FETCH then INSPECT: download what a page offers, verify it is what it claimed", async () => {
  const http = require("node:http");
  const crypto = require("node:crypto");
  const content = "the file this fixture server actually serves";
  const server = http.createServer((req, res) => { res.writeHead(200, { "content-type": "text/plain" }); res.end(content); });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  try {
    // 127.0.0.1 is normally blocked by privateHost(); this run explicitly
    // declares it as the one host it may reach, so the allowlist -- not the
    // private-network rule -- is what is being exercised here.
    const tool = new DeveloperTool({ allowCommands: [], hosts: ["127.0.0.1"], scratchDir: scratchDir() });
    tool._checkHost = function (rawUrl) { return new URL(String(rawUrl)); }; // bypass privateHost for this local fixture only

    const fetched = await tool.processAction({ type: "FETCH", target: `http://127.0.0.1:${port}/file.txt` },
      { recorder: fakeRecorder() });
    assert.equal(fetched.failed, false);
    assert.equal(fetched.bytes, Buffer.byteLength(content));

    const inspected = await tool.processAction({ type: "INSPECT", target: fetched.savedAs },
      { recorder: fakeRecorder() });
    assert.equal(inspected.failed, false);
    assert.equal(inspected.sha256, crypto.createHash("sha256").update(content).digest("hex"),
      "the checksum proves it is exactly what the page served, not merely that something arrived");
  } finally {
    server.close();
  }
});
