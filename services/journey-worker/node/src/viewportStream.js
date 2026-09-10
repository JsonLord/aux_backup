"use strict";
/**
 * Real-time frames from the browser a journey is driving.
 *
 * agent-browser runs a WebSocket viewport server for every session and pushes
 * `{type:"frame", data:<base64 jpeg>, metadata:{...}}` as the page paints -- it
 * is CDP's screencast, already built. liveRun.js could only offer whatever
 * screenshot the driver happened to write to disk, which shows the run in the
 * jumps between deliberate captures rather than as it happens.
 *
 * The worker subscribes here and keeps the newest frame in memory. Viewers keep
 * talking to the worker over HTTP, which matters in the Space: only one port is
 * published, so a browser outside the container cannot reach agent-browser's
 * stream port directly. Relaying through the worker is what makes the live view
 * reachable at all, and it keeps liveRunState's response shape unchanged.
 *
 * Only the newest frame is kept. A viewer that falls behind should see the
 * present, not work through a backlog, and the memory cost stays flat however
 * long a run goes on.
 *
 * The pointer is not in these frames -- the browser draws its cursor above the
 * page, outside what CDP captures. assets/cursor-overlay.js puts one in the DOM
 * so it lands in the pixels this streams.
 */

const { runAgentBrowser } = require("./agentBrowser");

const DEFAULT_STREAM_PORT = 9223;
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10000;
// A frame older than this is not "live" any more: the browser has stopped
// painting, or the session went away without the socket noticing.
const FRAME_STALE_MS = 5000;

// The session is not up the instant a run asks for its stream: the driver
// launches the browser first. Long enough to cover that, short enough that a
// run against a session that never appears is not held up.
const DISCOVERY_ATTEMPTS = 10;
const DISCOVERY_DELAY_MS = 1000;

const defaultSleep = (ms) => new Promise((resolve) => {
  const timer = setTimeout(resolve, ms);
  if (typeof timer.unref === "function") timer.unref();
});

let socket = null;
let latest = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
let lastError = "";
let desiredUrl = "";

function streamPort(env = process.env) {
  const configured = Number.parseInt(String(env.AGENT_BROWSER_STREAM_PORT || ""), 10);
  return Number.isInteger(configured) && configured > 0 ? configured : DEFAULT_STREAM_PORT;
}

/**
 * Ask agent-browser which port this session's stream is on.
 *
 * `stream status --json` reports it: {"data":{"connected":true,"port":38091,...}}.
 * Asking is the only reliable way to know. The pinned 0.31.1 does not honour
 * AGENT_BROWSER_STREAM_PORT -- during a live run with it set to 9254, the run's
 * session came up on 38091 and a second session on 45977, both OS-assigned --
 * so a worker that assumes the pinned port connects to nothing and the live view
 * silently falls back to whatever screenshot happens to be on disk. Its own help
 * text says as much: "If --port is omitted, agent-browser binds an available
 * localhost port automatically and reports it back."
 */
async function discoverStreamPort({ session, runner = runAgentBrowser } = {}) {
  const result = await runner(["stream", "status", "--json"], session === undefined ? {} : { session });
  if (!result.ok) return null;
  try {
    const port = JSON.parse(result.stdout)?.data?.port;
    return Number.isInteger(port) && port > 0 ? port : null;
  } catch {
    return null;
  }
}

/**
 * Pin agent-browser's stream to a known port, when an operator asked for one.
 *
 * Kept because a build that does honour it should be taken at its word, and
 * because an explicit port is what an operator publishing it needs. It is no
 * longer relied on: startViewportStream() asks the session where its stream
 * actually is, and uses the answer.
 */
function configureStreamPort(env = process.env) {
  const configured = Number.parseInt(String(env.AGENT_BROWSER_STREAM_PORT || ""), 10);
  if (!Number.isInteger(configured) || configured <= 0) return null;
  env.AGENT_BROWSER_STREAM_PORT = String(configured);
  return configured;
}

function scheduleReconnect() {
  if (reconnectTimer || !desiredUrl) return;
  const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS);
  reconnectAttempt += 1;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect(desiredUrl);
  }, delay);
  if (typeof reconnectTimer.unref === "function") reconnectTimer.unref();
}

function handleMessage(raw) {
  let payload;
  try {
    payload = JSON.parse(typeof raw === "string" ? raw : String(raw));
  } catch {
    return; // a frame we cannot read is not worth tearing the socket down for
  }
  if (payload?.type !== "frame" || !payload.data) return;
  latest = { data: payload.data, metadata: payload.metadata || {}, receivedAt: Date.now() };
}

function connect(url) {
  desiredUrl = url;
  if (socket) return socket;
  if (typeof WebSocket !== "function") {
    lastError = "this runtime has no global WebSocket";
    return null;
  }
  try {
    socket = new WebSocket(url);
  } catch (error) {
    lastError = String(error?.message || error);
    socket = null;
    scheduleReconnect();
    return null;
  }
  socket.addEventListener("open", () => {
    reconnectAttempt = 0;
    lastError = "";
  });
  socket.addEventListener("message", (event) => handleMessage(event.data));
  socket.addEventListener("error", () => {
    // The close handler owns reconnection; an error without a close is not fatal.
    lastError = "viewport stream socket error";
  });
  socket.addEventListener("close", () => {
    socket = null;
    scheduleReconnect();
  });
  return socket;
}

/**
 * Begin following the browser's viewport. Safe to call repeatedly.
 *
 * The port is discovered from the session rather than assumed. Discovery is
 * retried because the session does not exist until the driver launches, which is
 * after the run asks for the stream; each attempt is one cheap CLI call, and the
 * socket's own reconnect takes over once a port is known.
 */
async function startViewportStream({ session, env = process.env, runner = runAgentBrowser,
  attempts = DISCOVERY_ATTEMPTS, delayMs = DISCOVERY_DELAY_MS, sleep = defaultSleep } = {}) {
  for (let attempt = 0; attempt < Math.max(1, attempts); attempt += 1) {
    const port = await discoverStreamPort({ session, runner });
    if (port) return connect(`ws://127.0.0.1:${port}`);
    lastError = `agent-browser has not reported a stream port for session '${session || "default"}' yet`;
    if (attempt + 1 < Math.max(1, attempts)) await sleep(delayMs);
  }
  // An operator-pinned port is the last thing to try: on a build that honours it
  // this is right, and on one that does not there was nothing to connect to
  // anyway.
  const pinned = Number.parseInt(String(env.AGENT_BROWSER_STREAM_PORT || ""), 10);
  if (Number.isInteger(pinned) && pinned > 0) return connect(`ws://127.0.0.1:${pinned}`);
  return null;
}

function stopViewportStream() {
  desiredUrl = "";
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
  if (socket) {
    try {
      socket.close();
    } catch {
      // already gone
    }
    socket = null;
  }
  latest = null;
  reconnectAttempt = 0;
}

/**
 * Send a viewer's input to the browser.
 *
 * The stream is bidirectional: agent-browser accepts input_mouse, input_keyboard
 * and input_touch on the same socket it pushes frames down. That is what lets a
 * person finish something the agent cannot -- a second factor, or a challenge
 * that wants a human -- without a second browser or a second connection.
 *
 * The worker relays rather than the viewer connecting directly, because in a
 * Space only one port is published and the stream's is not it. The worker
 * already holds this socket, so relaying costs nothing extra.
 *
 * Movement is forwarded as it happens, not just the click. A pointer that
 * teleports to a checkbox looks less human than one that never moved, and
 * challenge scoring watches exactly that.
 */
function sendViewportInput(payload) {
  if (!socket || socket.readyState !== 1) {
    return { sent: false, error: "the viewport stream is not connected" };
  }
  const type = String(payload?.type || "");
  if (!["input_mouse", "input_keyboard", "input_touch"].includes(type)) {
    return { sent: false, error: `unsupported input type '${type}'` };
  }
  try {
    socket.send(JSON.stringify(payload));
  } catch (error) {
    return { sent: false, error: String(error?.message || error) };
  }
  return { sent: true };
}

/** The newest frame, or null when none has arrived recently. */
function latestFrame(now = Date.now()) {
  if (!latest) return null;
  if (now - latest.receivedAt > FRAME_STALE_MS) return null;
  return latest;
}

function viewportStreamStatus(now = Date.now()) {
  return {
    connected: Boolean(socket && socket.readyState === 1),
    // Where the worker is actually listening, which is what a reader needs when
    // the answer is "no frames". Reporting the environment's port instead said
    // 9223 while the session was on 38091 -- a status that agreed with the
    // configuration and disagreed with reality.
    url: desiredUrl || undefined,
    port: desiredUrl ? Number.parseInt(desiredUrl.split(":").pop(), 10) : null,
    ageMs: latest ? now - latest.receivedAt : null,
    error: lastError || undefined,
  };
}

/** Test seam: drop all state between cases. */
function __resetViewportStream() {
  stopViewportStream();
  lastError = "";
}

module.exports = {
  DEFAULT_STREAM_PORT, DISCOVERY_ATTEMPTS, DISCOVERY_DELAY_MS, FRAME_STALE_MS, configureStreamPort,
  discoverStreamPort, latestFrame, sendViewportInput, startViewportStream, stopViewportStream,
  streamPort, viewportStreamStatus, __resetViewportStream, __handleMessage: handleMessage,
};
