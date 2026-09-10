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


# WCAG 2.2 relative-luminance coefficients and the sRGB transfer function. These
# are the published numbers, not an approximation of them.
_LUMA = (0.2126, 0.7152, 0.0722)
_SRGB_KNEE = 0.04045

# Where "the text" and "the background" are taken from inside a region. Extremes
# would be a single antialiased pixel; the deciles are what a reader's eye
# integrates over a glyph and the paper behind it.
_INK_PERCENTILE = 10
_PAPER_PERCENTILE = 90

# WCAG 2.2 1.4.3 (AA): 4.5:1 for body text, 3:1 for large text and for the
# non-text contrast of a control's boundary (1.4.11).
WCAG_AA_TEXT = 4.5
WCAG_AA_LARGE = 3.0

# 1.4.3 calls text large at 18pt, or 14pt bold -- 24px and 18.66px at the usual
# 96dpi. Height is the only thing a box gives us, so it stands in for size.
LARGE_TEXT_PX = 24.0

# How far outside a solid region to look for what it sits on.
_SURROUND_PX = 12


def relative_luminance(pixels: np.ndarray) -> np.ndarray:
    """WCAG relative luminance for an array of sRGB values in 0..255."""
    channels = pixels.astype(np.float32) / 255.0
    linear = np.where(channels <= _SRGB_KNEE, channels / 12.92,
                      ((channels + 0.055) / 1.055) ** 2.4)
    return linear[..., 0] * _LUMA[0] + linear[..., 1] * _LUMA[1] + linear[..., 2] * _LUMA[2]


def contrast_ratio(image: Image.Image, box: dict) -> dict:
    """The rendered contrast of one element, as WCAG defines it.

    Measured on the page as drawn, deliberately **not** on the degraded capture.
    That is the whole point of having it: whether a persona with 0.35 acuity could
    read something is a fact about that persona, and a report cannot responsibly
    call it a defect in the site on that basis alone. Whether the element clears
    4.5:1 is a fact about the site, true for every visitor, and citable.

    So this is the objective half of an accessibility finding. It is also the only
    half a developer can act on without agreeing about whose eyes to believe.
    """
    left, top = max(0, int(box.get("x", 0))), max(0, int(box.get("y", 0)))
    right = min(image.width, int(left + max(1, box.get("width", 0))))
    bottom = min(image.height, int(top + max(1, box.get("height", 0))))
    if right <= left or bottom <= top:
        return {"ratio": None, "passes": None, "required": None, "largeText": False}

    rgb = image.convert("RGB")
    luminance = relative_luminance(np.asarray(rgb.crop((left, top, right, bottom))))
    ink = float(np.percentile(luminance, _INK_PERCENTILE))
    paper = float(np.percentile(luminance, _PAPER_PERCENTILE))

    # A region of one flat colour has no internal contrast to measure, and taking
    # its deciles gives 1.0:1 for a solid black button on white -- which reads as
    # the worst possible result for one of the most legible things on a page. That
    # is not a bug in the arithmetic, it is the wrong question: a solid control has
    # no text of its own, and what WCAG asks about it (1.4.11, non-text contrast)
    # is its boundary against what surrounds it.
    against = "text against its own background"
    if abs(paper - ink) < 0.01:
        # The bands outside the box, not the expanded box: a 240x60 control sits
        # inside a 264x84 expansion, so it is 65% of those pixels and their median
        # is the control itself. Measured that way a solid green button on white
        # came back 1.0:1 -- the worst possible score for something perfectly
        # legible. The same trap as measuring edge contrast in legibility().
        bands = []
        for crop in ((left, max(0, top - _SURROUND_PX), right, top),                       # above
                     (left, bottom, right, min(rgb.height, bottom + _SURROUND_PX)),        # below
                     (max(0, left - _SURROUND_PX), top, left, bottom),                     # left
                     (right, top, min(rgb.width, right + _SURROUND_PX), bottom)):          # right
            if crop[2] > crop[0] and crop[3] > crop[1]:
                bands.append(relative_luminance(np.asarray(rgb.crop(crop))).ravel())
        if not bands:
            return {"ratio": None, "passes": None, "required": None, "largeText": False,
                    "measured": "a flat region with nothing around it to compare against"}
        ink, paper = float(np.median(luminance)), float(np.median(np.concatenate(bands)))
        against = "a solid region against what surrounds it"

    lighter, darker = max(ink, paper), min(ink, paper)
    ratio = (lighter + 0.05) / (darker + 0.05)

    # 1.4.11 asks 3:1 of a control's boundary, whatever its size.
    if against.startswith("a solid"):
        required, large = WCAG_AA_LARGE, False
    else:
        large = float(box.get("height", 0)) >= LARGE_TEXT_PX
        required = WCAG_AA_LARGE if large else WCAG_AA_TEXT
    return {"ratio": round(float(ratio), 2), "required": required,
            "passes": bool(ratio >= required), "largeText": large, "measured": against}
