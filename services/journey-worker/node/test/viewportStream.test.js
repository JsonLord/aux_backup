"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const {
  DEFAULT_STREAM_PORT, FRAME_STALE_MS, configureStreamPort, discoverStreamPort, latestFrame,
  startViewportStream, streamPort, viewportStreamStatus, __resetViewportStream, __handleMessage,
} = require("../src/viewportStream");

test.beforeEach(() => __resetViewportStream());
// And afterwards, so a test that opened a socket does not leave it holding the
// event loop open -- the runner hangs after the last assertion rather than failing.
test.afterEach(() => __resetViewportStream());

test("only an operator's own pinned port is written into the environment", () => {
  // agent-browser 0.31.1 does not honour AGENT_BROWSER_STREAM_PORT: during a live
  // run with it set to 9254, the run's session came up on 38091 and a second one
  // on 45977, both OS-assigned. Writing a default into the environment made the
  // worker believe it knew a port it did not, so it connected to nothing and the
  // live view silently fell back to screenshots. An unset variable now stays unset
  // and the port is discovered instead.
  const env = {};
  assert.equal(configureStreamPort(env), null);
  assert.equal(env.AGENT_BROWSER_STREAM_PORT, undefined);

  const chosen = { AGENT_BROWSER_STREAM_PORT: "9999" };
  assert.equal(configureStreamPort(chosen), 9999);
  assert.equal(chosen.AGENT_BROWSER_STREAM_PORT, "9999");

  // A value that is not a port must not silently become one.
  assert.equal(configureStreamPort({ AGENT_BROWSER_STREAM_PORT: "not-a-port" }), null);
  assert.equal(streamPort({ AGENT_BROWSER_STREAM_PORT: "not-a-port" }), DEFAULT_STREAM_PORT);
});

test("the stream port is read back from the session that owns it", async () => {
  // The shape agent-browser really answers with, taken from a live session.
  const calls = [];
  const runner = async (args, options) => {
    calls.push({ args, options });
    return { ok: true, stdout: JSON.stringify({ success: true, error: null,
      data: { connected: true, enabled: true, port: 59341, screencasting: false } }) };
  };
  assert.equal(await discoverStreamPort({ session: "aux-run-1", runner }), 59341);
  assert.deepEqual(calls[0].args, ["stream", "status", "--json"]);
  // Asked of the run's own session, not whichever browser is the default.
  assert.equal(calls[0].options.session, "aux-run-1");
});

test("a session that cannot report a port yields none rather than a guess", async () => {
  assert.equal(await discoverStreamPort({ runner: async () => ({ ok: false, stderr: "no session" }) }), null);
  assert.equal(await discoverStreamPort({ runner: async () => ({ ok: true, stdout: "not json" }) }), null);
  assert.equal(await discoverStreamPort({
    runner: async () => ({ ok: true, stdout: JSON.stringify({ data: { port: 0 } }) }) }), null);
});

test("discovery is retried while the driver is still launching the browser", async () => {
  // startViewportStream() is called before runJourney(), so the session does not
  // exist yet on the first ask.
  let attempt = 0;
  const runner = async () => {
    attempt += 1;
    return attempt < 3
      ? { ok: false, stderr: "session not found" }
      : { ok: true, stdout: JSON.stringify({ data: { port: 59342 } }) };
  };
  const slept = [];
  await startViewportStream({ session: "aux-run-1", runner, attempts: 5, delayMs: 7,
    sleep: async (ms) => { slept.push(ms); }, env: {} });
  assert.equal(attempt, 3);
  assert.deepEqual(slept, [7, 7]);
  assert.equal(viewportStreamStatus().url, "ws://127.0.0.1:59342");
});

test("an operator's pinned port is the fallback when discovery never answers", async () => {
  await startViewportStream({ session: "aux-run-1", runner: async () => ({ ok: false, stderr: "gone" }),
    attempts: 2, delayMs: 0, sleep: async () => {}, env: { AGENT_BROWSER_STREAM_PORT: "59343" } });
  assert.equal(viewportStreamStatus().url, "ws://127.0.0.1:59343");
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

test("status reports whether frames are actually arriving", async () => {
  const idle = viewportStreamStatus();
  assert.equal(idle.connected, false);
  // Nothing is being followed yet, so there is no port to report. Naming one
  // from the environment would claim a connection that was never made.
  assert.equal(idle.port, null);
  assert.equal(idle.url, undefined);
  assert.equal(idle.ageMs, null);

  await startViewportStream({ session: "aux-run-1", attempts: 1, delayMs: 0, sleep: async () => {},
    env: {}, runner: async () => ({ ok: true, stdout: JSON.stringify({ data: { port: 59344 } }) }) });
  const following = viewportStreamStatus();
  assert.equal(following.port, 59344);
  assert.equal(following.url, "ws://127.0.0.1:59344");
});

test("a short tail of frames is kept, because motion is what catches the eye", () => {
  // Only the newest frame was ever kept, so the frames that reveal a carousel, an
  // autoplaying video or a blinking CTA were arriving and being discarded. What
  // moves while nobody is touching the page is exactly what distracts a person.
  const { recentFrames, RING_SIZE } = require("../src/viewportStream");
  __resetViewportStream();
  assert.deepEqual(recentFrames(), []);

  for (let index = 0; index < RING_SIZE + 4; index += 1) {
    __handleMessage(JSON.stringify({ type: "frame", data: `frame-${index}`, metadata: {} }));
  }
  const kept = recentFrames();
  assert.equal(kept.length, RING_SIZE, "the ring is bounded, so a long run cannot grow it");
  // Oldest first, newest last -- differencing needs them in order.
  assert.equal(kept.at(-1).data, `frame-${RING_SIZE + 3}`);
  assert.equal(kept[0].data, `frame-4`);
});

test("frames from a page that stopped painting are not read as motion", () => {
  // A page that settled five seconds ago is finished, not animating; differencing
  // its last frames would report whatever changed just before it stopped.
  const { recentFrames } = require("../src/viewportStream");
  __resetViewportStream();
  __handleMessage(JSON.stringify({ type: "frame", data: "old", metadata: {} }));
  assert.equal(recentFrames().length, 1);
  assert.equal(recentFrames(Date.now() + FRAME_STALE_MS + 1000).length, 0);
});
