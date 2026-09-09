"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  DEFAULT_STREAM_PORT, FRAME_STALE_MS, configureStreamPort, latestFrame,
  streamPort, viewportStreamStatus, __resetViewportStream, __handleMessage,
} = require("../src/viewportStream");

test.beforeEach(() => __resetViewportStream());

test("the stream port is pinned so the worker can find it", () => {
  // Every agent-browser session otherwise binds an OS-assigned port, which the
  // worker cannot learn without shelling out to `stream status`.
  const env = {};
  assert.equal(configureStreamPort(env), DEFAULT_STREAM_PORT);
  assert.equal(env.AGENT_BROWSER_STREAM_PORT, String(DEFAULT_STREAM_PORT));

  const chosen = { AGENT_BROWSER_STREAM_PORT: "9999" };
  assert.equal(configureStreamPort(chosen), 9999);
  assert.equal(chosen.AGENT_BROWSER_STREAM_PORT, "9999");

  // A value that is not a port must not silently become one.
  assert.equal(streamPort({ AGENT_BROWSER_STREAM_PORT: "not-a-port" }), DEFAULT_STREAM_PORT);
});

test("a frame from the browser becomes the newest frame", () => {
  assert.equal(latestFrame(), null);

  __handleMessage(JSON.stringify({
    type: "frame", data: "Zm9v",
    metadata: { deviceWidth: 1280, deviceHeight: 720, pageScaleFactor: 1 },
  }));

  const frame = latestFrame();
  assert.equal(frame.data, "Zm9v");
  // A client-side cursor overlay scales against this geometry.
  assert.equal(frame.metadata.deviceWidth, 1280);
});

test("only the newest frame is kept", () => {
  // A viewer that falls behind should see the present, not work through a
  // backlog, and memory must stay flat however long a run goes on.
  __handleMessage(JSON.stringify({ type: "frame", data: "b2xk" }));
  __handleMessage(JSON.stringify({ type: "frame", data: "bmV3" }));
  assert.equal(latestFrame().data, "bmV3");
});

test("a frame that stopped arriving is not reported as live", () => {
  __handleMessage(JSON.stringify({ type: "frame", data: "Zm9v" }));
  const arrived = latestFrame().receivedAt;

  assert.ok(latestFrame(arrived + FRAME_STALE_MS - 1), "still fresh");
  assert.equal(latestFrame(arrived + FRAME_STALE_MS + 1), null,
    "a stale frame must not be passed off as the live page");
});

test("messages that are not frames are ignored without breaking the socket", () => {
  __handleMessage(JSON.stringify({ type: "frame", data: "Zm9v" }));
  __handleMessage(JSON.stringify({ type: "status", state: "ready" }));
  __handleMessage("not json at all");
  __handleMessage(JSON.stringify({ type: "frame" }));      // no data

  assert.equal(latestFrame().data, "Zm9v", "the last real frame still stands");
});

test("status reports whether frames are actually arriving", () => {
  const status = viewportStreamStatus();
  assert.equal(status.connected, false);
  assert.equal(status.port, streamPort());
  assert.equal(status.ageMs, null);
});
