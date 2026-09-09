/**
 * Draws the pointer into the page so a live run can be watched.
 *
 * The browser's own cursor is composited above the page, so it never appears in
 * a CDP screencast frame, a screenshot, or a recorded video -- watching a run,
 * you see controls react with nothing visibly touching them. Nothing in the
 * capture path can fix that: the pointer is not in the pixels being captured.
 *
 * A cursor that is part of the DOM is. This element rides in the same layer as
 * the page, so it shows up in the live stream, in every screenshot, and in the
 * run's video without any of them changing.
 *
 * Registered through AGENT_BROWSER_INIT_SCRIPTS, so it runs before first
 * navigation and re-runs for every document, including after a redirect.
 *
 * It never intercepts input (pointer-events:none) and never participates in
 * layout (position:fixed), so the page under test behaves as it would without
 * it. It is still a node the page could see, which is why it is opt-in.
 */
(() => {
  const ID = "__aux_cursor_overlay__";
  if (window.__auxCursorOverlayInstalled) return;
  window.__auxCursorOverlayInstalled = true;

  const SIZE = 22;
  let cursor = null;
  let pending = null;

  function ensure() {
    if (cursor && cursor.isConnected) return cursor;
    if (!document.body) return null;
    cursor = document.createElement("div");
    cursor.id = ID;
    cursor.setAttribute("aria-hidden", "true");
    cursor.style.cssText = [
      "position:fixed", "top:0", "left:0",
      // Without border-box the 2px border is added to the width, so the drawn
      // circle sits 2px off the real pointer -- enough to look like it missed a
      // small control it actually hit.
      "box-sizing:border-box",
      `width:${SIZE}px`, `height:${SIZE}px`,
      "margin:0", "padding:0", "border-radius:50%",
      "background:rgba(255,68,68,.42)",
      "border:2px solid rgba(255,255,255,.95)",
      "box-shadow:0 0 0 1px rgba(0,0,0,.35),0 2px 6px rgba(0,0,0,.45)",
      "pointer-events:none", "z-index:2147483647",
      "transform:translate(-9999px,-9999px)",
      "transition:background-color .08s linear,transform .04s linear",
      "will-change:transform",
    ].join(";");
    document.body.appendChild(cursor);
    return cursor;
  }

  function place(x, y) {
    const node = ensure();
    if (!node) return;
    // Centre the dot on the real pointer position.
    node.style.transform = `translate(${x - SIZE / 2}px, ${y - SIZE / 2}px)`;
  }

  // Coalesce to one paint per frame: a humanised pointer path emits far more
  // mousemove events than the display can show, and each one would otherwise
  // force its own style recalculation inside the page being measured.
  function schedule(event) {
    pending = { x: event.clientX, y: event.clientY };
    if (schedule.queued) return;
    schedule.queued = true;
    requestAnimationFrame(() => {
      schedule.queued = false;
      if (pending) place(pending.x, pending.y);
    });
  }

  function paint(background) {
    const node = ensure();
    if (node) node.style.background = background;
  }

  addEventListener("mousemove", schedule, { capture: true, passive: true });
  addEventListener("mousedown", () => paint("rgba(64,160,255,.85)"), { capture: true, passive: true });
  addEventListener("mouseup", () => paint("rgba(255,68,68,.42)"), { capture: true, passive: true });

  // The element is created on first movement, but a run that clicks without
  // moving first should still be visible.
  if (document.readyState === "loading") {
    addEventListener("DOMContentLoaded", () => ensure(), { once: true });
  } else {
    ensure();
  }
})();
