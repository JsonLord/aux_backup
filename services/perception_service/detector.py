"""Things on the page that no DOM node accounts for.

The perception model so far takes the accessibility tree as its list of
candidates and asks, of each one, whether there are pixels where it claims to
be. That catches "in the tree but not perceivable". It cannot catch the other
direction -- text baked into a hero image, a control drawn on a canvas, a price
that only exists as a JPEG -- because nothing puts those in the tree to begin
with. A person sees them and acts on them; the run is blind to them.

A screen parser closes that half. OmniParser's detector stage is the right tool
and its captioner is not: the DOM already names everything it knows about, so
paying for Florence-2 to caption an icon we can read from the tree is the
expensive way to learn what we already have. Detector plus OCR answers the one
question the tree cannot: what is drawn here that nothing declared?

So this is deliberately optional and deliberately absent by default. torch plus
weights is a large addition to an image that currently needs neither, and the
perceivability half of the model -- the half carrying most of the value -- runs
on numpy and PIL alone. When no detector is installed the service says so and
keeps working; nothing about a journey depends on it.
"""
from __future__ import annotations

import os
from typing import Any

from PIL import Image

# Anything the detector is less sure of than this is noise on a screenshot: page
# furniture, compression artefacts around a border, half an icon at the fold.
DEFAULT_CONFIDENCE = 0.05

# Two boxes overlapping by this much are the same thing seen twice -- once by the
# DOM and once by the detector -- so the detection is not news.
SAME_THING_IOU = 0.35


def _iou(first: dict, second: dict) -> float:
    ax1, ay1 = float(first.get("x", 0)), float(first.get("y", 0))
    ax2, ay2 = ax1 + float(first.get("width", 0)), ay1 + float(first.get("height", 0))
    bx1, by1 = float(second.get("x", 0)), float(second.get("y", 0))
    bx2, by2 = bx1 + float(second.get("width", 0)), by1 + float(second.get("height", 0))
    left, top = max(ax1, bx1), max(ay1, by1)
    right, bottom = min(ax2, bx2), min(ay2, by2)
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - overlap
    return float(overlap / union) if union > 0 else 0.0


class ScreenParser:
    """OmniParser's detector stage, if it happens to be installed.

    Loaded lazily and never at import time: importing torch costs seconds and
    hundreds of megabytes, and a deployment that never asks for detection should
    never pay either.
    """

    def __init__(self, weights_path: str | None = None, device: str | None = None) -> None:
        self.weights_path = weights_path or os.environ.get("OMNIPARSER_WEIGHTS") or ""
        self.device = device or os.environ.get("OMNIPARSER_DEVICE") or "cpu"
        self._model: Any = None
        self._ocr: Any = None
        self._load_error = ""
        self._loaded = False

    @property
    def available(self) -> bool:
        """Whether a detector can actually run, without loading one to find out."""
        if self._loaded:
            return self._model is not None or self._ocr is not None
        if not self.weights_path:
            return False
        try:  # noqa: SIM105 - the import is the probe
            import torch  # noqa: F401
        except ImportError:
            return False
        return os.path.exists(self.weights_path)

    def describe(self) -> dict:
        return {"configured": bool(self.weights_path), "available": self.available,
                "device": self.device, "loaded": self._loaded,
                **({"error": self._load_error} if self._load_error else {})}

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            from ultralytics import YOLO

            self._model = YOLO(self.weights_path)
        except Exception as error:  # a missing wheel, missing weights, a bad file
            self._load_error = f"icon detector unavailable: {error}"
        try:
            import easyocr

            self._ocr = easyocr.Reader(["en"], gpu=self.device != "cpu", verbose=False)
        except Exception as error:
            self._load_error = (self._load_error + "; " if self._load_error else "") + \
                f"OCR unavailable: {error}"

    def detect(self, image: Image.Image, confidence: float = DEFAULT_CONFIDENCE) -> list[dict]:
        """Every drawn thing the parser can find, in page pixel coordinates."""
        if not self.available:
            return []
        self._load()
        found: list[dict] = []
        if self._model is not None:
            try:
                result = self._model.predict(source=image, conf=confidence, iou=0.7, verbose=False)
                for box, score in zip(result[0].boxes.xyxy.tolist(), result[0].boxes.conf.tolist()):
                    x1, y1, x2, y2 = box
                    found.append({"kind": "icon", "content": "",
                                  "confidence": round(float(score), 4),
                                  "box": {"x": round(x1, 1), "y": round(y1, 1),
                                          "width": round(x2 - x1, 1), "height": round(y2 - y1, 1)}})
            except Exception as error:
                self._load_error = f"detection failed: {error}"
        if self._ocr is not None:
            try:
                for corners, text, score in self._ocr.readtext(image):
                    xs = [point[0] for point in corners]
                    ys = [point[1] for point in corners]
                    found.append({"kind": "text", "content": str(text),
                                  "confidence": round(float(score), 4),
                                  "box": {"x": round(min(xs), 1), "y": round(min(ys), 1),
                                          "width": round(max(xs) - min(xs), 1),
                                          "height": round(max(ys) - min(ys), 1)}})
            except Exception as error:
                self._load_error = f"OCR failed: {error}"
        return found


def unnamed_elements(detections: list[dict], elements: list[dict],
                     threshold: float = SAME_THING_IOU) -> list[dict]:
    """Detections that no DOM element accounts for.

    These are the interesting ones, and they are their own finding: a person can
    read a price rendered into a hero image and a screen reader cannot, which is
    an accessibility defect the tree can never reveal because the tree is where
    the evidence is missing.
    """
    boxes = [element.get("box") or element.get("boundingBox") or {} for element in elements]
    orphans = []
    for detection in detections:
        if any(_iou(detection["box"], box) >= threshold for box in boxes if box):
            continue
        orphans.append({**detection, "selector": f"pixels@{int(detection['box']['x'])},"
                                                 f"{int(detection['box']['y'])}",
                        "role": detection["kind"], "name": detection.get("content", ""),
                        "undeclared": True})
    return orphans
