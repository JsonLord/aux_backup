"""Driving the browser a run is using, from the live view.

Some obstacles a run cannot pass on its own: a second factor whose code is on
someone's phone, or a challenge specifically asking whether a human is there.
Rather than fail, the browser is handed over and the person watching finishes it.

Everything goes through the journey worker. In a Space only one port is
published and agent-browser's stream port is not it, so the viewer cannot reach
the browser directly -- the worker already holds that socket and relays.

Coordinates need no conversion. The streamed frame is a render of the page
viewport, so a click at (x, y) in the image is a click at (x, y) in the page --
which is also why the close-up scales against `cursor.viewport` rather than the
stream's device metadata.
"""
from __future__ import annotations

import json
import os
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


def worker_base(worker_url: str | None = None) -> str:
    return (worker_url or os.getenv("JOURNEY_WORKER_URL", "http://127.0.0.1:8080")).rstrip("/")


def _call(path: str, payload: dict[str, Any] | None = None, *, method: str = "POST",
          worker_url: str | None = None, timeout: float = 15.0) -> dict[str, Any]:
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    call = urlrequest.Request(f"{worker_base(worker_url)}{path}", data=data, method=method,
                              headers={"content-type": "application/json"})
    try:
        with urlrequest.urlopen(call, timeout=timeout) as response:
            body = response.read()
        return json.loads(body) if body else {}
    except urlerror.HTTPError as error:
        # The worker's own explanation is worth more than the status: "take over
        # the browser before sending input" tells a reader what to do next.
        try:
            return {"error": json.loads(error.read()).get("message") or str(error)}
        except Exception:  # noqa: BLE001
            return {"error": f"HTTP {error.code}"}
    except OSError as error:
        return {"error": f"could not reach the journey worker: {type(error).__name__}"}


def begin_takeover(run_id: str = "", reason: str = "manual", url: str = "",
                   worker_url: str | None = None) -> dict[str, Any]:
    return _call("/v1/takeovers", {"runId": run_id, "reason": reason, "url": url},
                 worker_url=worker_url)


def end_takeover(worker_url: str | None = None) -> dict[str, Any]:
    return _call("/v1/takeovers", method="DELETE", worker_url=worker_url)


def takeover_state(worker_url: str | None = None) -> dict[str, Any]:
    return _call("/v1/takeovers", None, method="GET", worker_url=worker_url)


def click_at(x: float, y: float, worker_url: str | None = None) -> dict[str, Any]:
    """A press and release at one point.

    A move is sent first so the page sees the pointer arrive rather than a click
    materialising out of nowhere. It is still a jump, not a path -- Gradio has no
    pointer-move event to forward, so this cannot reproduce human movement, only
    human intent.
    """
    for event, button, clicks in (("mouseMoved", "none", 0),
                                  ("mousePressed", "left", 1),
                                  ("mouseReleased", "left", 1)):
        outcome = _call("/v1/input", {"type": "input_mouse", "eventType": event,
                                      "x": float(x), "y": float(y),
                                      "button": button, "clickCount": clicks},
                        worker_url=worker_url)
        if outcome.get("error"):
            return outcome
    return {"clicked": [round(float(x)), round(float(y))]}


def type_text(text: str, *, submit: bool = False, worker_url: str | None = None) -> dict[str, Any]:
    """Type into whatever the page has focused, optionally pressing Enter after."""
    for character in str(text or ""):
        outcome = _call("/v1/input", {"type": "input_keyboard", "eventType": "char",
                                      "key": character, "text": character},
                        worker_url=worker_url)
        if outcome.get("error"):
            return outcome
    if submit:
        for event in ("keyDown", "keyUp"):
            _call("/v1/input", {"type": "input_keyboard", "eventType": event,
                                "key": "Enter", "code": "Enter"}, worker_url=worker_url)
    return {"typed": len(str(text or "")), "submitted": submit}
