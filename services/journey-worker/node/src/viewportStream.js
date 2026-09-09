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

const DEFAULT_STREAM_PORT = 9223;
const RECONNECT_BASE_MS = 500;
const RECONNECT_MAX_MS = 10000;
// A frame older than this is not "live" any more: the browser has stopped
// painting, or the session went away without the socket noticing.
const FRAME_STALE_MS = 5000;

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
 * Pin agent-browser's stream to a known port.
 *
 * Every session otherwise binds an OS-assigned one, which the worker has no way
 * to learn without shelling out to `stream status`. Set before the driver
 * launches; the CLI inherits this environment.
 */
function configureStreamPort(env = process.env) {
  const port = streamPort(env);
  env.AGENT_BROWSER_STREAM_PORT = String(port);
  return port;
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

/** Begin following the browser's viewport. Safe to call repeatedly. */
function startViewportStream(env = process.env) {
  const port = streamPort(env);
  return connect(`ws://127.0.0.1:${port}`);
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
    port: streamPort(),
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
  DEFAULT_STREAM_PORT, FRAME_STALE_MS, configureStreamPort, latestFrame,
  sendViewportInput, startViewportStream, stopViewportStream, streamPort, viewportStreamStatus,
  __resetViewportStream, __handleMessage: handleMessage,
};
