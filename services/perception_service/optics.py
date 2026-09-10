"""What a persona's eyes actually do to the pixels, before anything reads them.

physical.js has modelled this since the beginning -- a colour matrix per kind of
colour vision, a blur radius from acuity, a contrast slope -- and only ever
produced a *manifest* of the transform, never the transformed pixels. Nothing
downstream applied it. A persona with 0.2 acuity and one with perfect vision were
handed identical screenshots and identical DOM text, so every ability slider in
the UI was decoration.

Applying it for real, and applying it *first*, is what makes an ability
mechanical rather than descriptive. Degrade the capture before anything parses it
and small low-contrast text stops being resolvable at all: it does not get
detected, so it never reaches the persona, so they cannot act on it. That is what
being unable to see something means. Telling a model "you have poor vision" and
handing it the full text is roleplay; this is simulation.

The coefficients are deliberately the ones physical.js already publishes, so the
two agree about what a given profile sees.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageFilter

# Straight from physical.js colorMatrices, so a run and its replay agree.
COLOR_MATRICES: dict[str, tuple[float, ...]] = {
    "typical": (1, 0, 0, 0, 1, 0, 0, 0, 1),
    "protanopia": (.567, .433, 0, .558, .442, 0, 0, .242, .758),
    "deuteranopia": (.625, .375, 0, .7, .3, 0, 0, .3, .7),
    "tritanopia": (.95, .05, 0, 0, .433, .567, 0, .475, .525),
}

# physical.js: blurPx = (1 - acuity) * 3. A person with half the acuity does not
# see a blurrier world by half; the relationship is steeper than that, but this is
# the number the rest of the system already uses and agreement matters more here
# than a better curve nobody else knows about.
MAX_BLUR_PX = 3.0


@dataclass(frozen=True)
class Eyes:
    """One persona's optics, defaulted to unimpaired."""

    color_vision: str = "typical"
    acuity: float = 1.0
    contrast_sensitivity: float = 1.0
    glare_sensitivity: float = 0.0

    @classmethod
    def from_abilities(cls, abilities: dict | None) -> "Eyes":
        vision = ((abilities or {}).get("vision")) or {}
        def bounded(value, default=1.0):
            try:
                return max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return default
        return cls(
            color_vision=str(vision.get("colorVision") or "typical").lower(),
            acuity=bounded(vision.get("acuity"), 1.0),
            contrast_sensitivity=bounded(vision.get("contrastSensitivity"), 1.0),
            glare_sensitivity=bounded(vision.get("glareSensitivity"), 0.0),
        )

    @property
    def unimpaired(self) -> bool:
        return (self.color_vision in ("", "typical") and self.acuity >= 0.999
                and self.contrast_sensitivity >= 0.999 and self.glare_sensitivity <= 0.001)

    @property
    def blur_px(self) -> float:
        return round((1.0 - self.acuity) * MAX_BLUR_PX, 3)


def apply_color_vision(image: Image.Image, kind: str) -> Image.Image:
    """Collapse the channels the way a given kind of colour blindness does.

    The matrices are the standard simulation ones: they mix the channels the eye
    cannot separate, which is why a red call-to-action on green stops being a
    contrast at all rather than merely changing hue.
    """
    matrix = COLOR_MATRICES.get(kind)
    if matrix is None or kind in ("", "typical"):
        return image
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    transform = np.array(matrix, dtype=np.float32).reshape(3, 3)
    # Row-major: each output channel is a weighted sum of the input channels.
    converted = pixels @ transform.T
    return Image.fromarray(np.clip(converted, 0, 255).astype(np.uint8))


def apply_contrast(image: Image.Image, sensitivity: float) -> Image.Image:
    """Pull everything toward mid-grey by however much contrast is lost.

    Reduced contrast sensitivity does not darken a page; it shrinks the distance
    between light and dark, which is why low-contrast grey-on-grey text is the
    first thing to disappear and solid black on white is the last.
    """
    if sensitivity >= 0.999:
        return image
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    flattened = 128.0 + (pixels - 128.0) * max(0.0, sensitivity)
    return Image.fromarray(np.clip(flattened, 0, 255).astype(np.uint8))


def apply_glare(image: Image.Image, sensitivity: float) -> Image.Image:
    """Wash out the bright end, the way glare does for someone sensitive to it."""
    if sensitivity <= 0.001:
        return image
    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    lifted = pixels + (255.0 - pixels) * (sensitivity * 0.35)
    return Image.fromarray(np.clip(lifted, 0, 255).astype(np.uint8))


def see(image: Image.Image, eyes: Eyes) -> Image.Image:
    """The page as this persona's eyes deliver it.

    Order matters and follows the eye: colour is lost at the receptors, contrast
    and glare in the optics, sharpness last. Blurring before flattening contrast
    would let the flattening act on already-smeared edges and overstate the loss.
    """
    if eyes.unimpaired:
        return image.convert("RGB")
    seen = apply_color_vision(image.convert("RGB"), eyes.color_vision)
    seen = apply_contrast(seen, eyes.contrast_sensitivity)
    seen = apply_glare(seen, eyes.glare_sensitivity)
    if eyes.blur_px > 0.01:
        seen = seen.filter(ImageFilter.GaussianBlur(radius=eyes.blur_px))
    return seen


def legibility(image: Image.Image, box: dict, margin: int = 12) -> dict:
    """Whether there is anything to see where this element lives, after the optics.

    Not "is it in the DOM" -- it is, that is why we are looking -- but whether the
    pixels still carry a mark a person could read or click. This is the
    measurement behind "present but not perceivable".

    Two ways of being visible, and an element needs only one. Text is *internal*
    structure: dark marks on a lighter background inside its own box. A solid
    button has no internal structure at all -- it is one flat colour by design --
    and is visible because it *differs from what surrounds it*.

    Measuring only the first is a trap worth recording: a solid black heading on
    white came back as "a single flat colour" and was reported as invisible, and
    blurring the page *helped*, because blur bled the surrounding white inward and
    manufactured the variance the measure was looking for. Exactly backwards.
    """
    left, top = max(0, int(box.get("x", 0))), max(0, int(box.get("y", 0)))
    right = min(image.width, int(left + max(1, box.get("width", 0))))
    bottom = min(image.height, int(top + max(1, box.get("height", 0))))
    if right <= left or bottom <= top:
        return {"visible": False, "reason": "outside the captured page",
                "ink": 0.0, "internalContrast": 0.0, "edgeContrast": 0.0}

    grey = image.convert("L")
    region = np.asarray(grey.crop((left, top, right, bottom)), dtype=np.float32)
    if region.size == 0:
        return {"visible": False, "reason": "empty region",
                "ink": 0.0, "internalContrast": 0.0, "edgeContrast": 0.0}

    # Structure inside: marks standing away from the region's own background.
    internal = float(region.max() - region.min()) / 255.0
    background = float(np.median(region))
    ink = float(np.mean(np.abs(region - background) > 12.0))

    # Difference from around it: a ring just outside the element's own box.
    outer = grey.crop((max(0, left - margin), max(0, top - margin),
                       min(image.width, right + margin), min(image.height, bottom + margin)))
    surround = np.asarray(outer, dtype=np.float32)
    if surround.size > region.size:
        # The ring is the surround minus the element -- sum the whole box and take
        # the element's contribution out, rather than building a mask.
        ring_total = float(surround.sum()) - float(region.sum())
        ring_count = surround.size - region.size
        edge = abs(float(region.mean()) - ring_total / ring_count) / 255.0
    else:
        edge = 0.0

    has_text = internal >= 0.08 and ink >= 0.005
    has_shape = edge >= 0.05
    visible = has_text or has_shape
    if visible:
        reason = ""
    elif internal < 0.02 and edge < 0.02:
        reason = "the region and everything around it are the same flat colour"
    elif internal < 0.08 and not has_shape:
        reason = "too little contrast to make anything out"
    else:
        reason = "nothing in the region stands out from its background"
    return {"visible": visible, "reason": reason, "ink": round(ink, 4),
            "internalContrast": round(internal, 4), "edgeContrast": round(edge, 4)}
