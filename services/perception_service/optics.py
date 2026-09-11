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


# What separates fine detail from coarse structure, in pixels. A 16px font's
# strokes are about 2px wide and a 44px heading's about 5px, so a radius in
# between is what tells the two apart.
DETAIL_SIGMA = 3.0

# How much contrast coarse structure keeps when sensitivity is at its worst.
# Not zero: somebody with very poor contrast sensitivity still makes out a large
# dark headline on a light page, and a model that says otherwise is wrong about
# the thing that matters most.
COARSE_FLOOR = 0.45


def apply_contrast(image: Image.Image, sensitivity: float) -> Image.Image:
    """Lose contrast the way an eye loses it: fine detail first.

    The first version of this multiplied every pixel's distance from mid-grey by
    the sensitivity, uniformly. That is wrong in a way that matters more than any
    other detail in this file: it crushes a 44px headline exactly as hard as 11px
    fine print, so a persona with poor contrast sensitivity was reported as unable
    to read a large low-contrast heading they could obviously read. Reduced
    contrast sensitivity is not a volume knob on the whole image.

    What it actually costs is high spatial frequency. Sensitivity to coarse
    structure falls slowly; sensitivity to fine detail falls off a cliff. So the
    image is split -- a blurred copy is the coarse structure, what is left over is
    the detail -- and the detail is attenuated hard while the coarse structure
    keeps most of what it had. That is why somebody who cannot read the body copy
    on a page can still read its headline, which is the whole point.
    """
    if sensitivity >= 0.999:
        return image
    rgb = image.convert("RGB")
    pixels = np.asarray(rgb, dtype=np.float32)
    coarse = np.asarray(rgb.filter(ImageFilter.GaussianBlur(radius=DETAIL_SIGMA)), dtype=np.float32)
    detail = pixels - coarse

    sensitivity = max(0.0, sensitivity)
    kept_coarse = COARSE_FLOOR + (1.0 - COARSE_FLOOR) * sensitivity
    seen = 128.0 + (coarse - 128.0) * kept_coarse + detail * sensitivity
    return Image.fromarray(np.clip(seen, 0, 255).astype(np.uint8))


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


# Normal vision resolves about one arcminute of detail. At a 60cm viewing
# distance on a 96dpi display that is roughly 0.66 CSS pixels -- the number that
# turns an acuity score into a size on the screen.
ARCMINUTE_PX = 0.66

# A regular-weight glyph's stroke is roughly an eighth of its font size, and it is
# the stroke that has to be resolvable, not the letter. Bold strokes are thicker,
# which is why the guidelines let bold text be smaller.
STROKE_RATIO = 8.0
BOLD_STROKE_RATIO = 6.0
BOLD_WEIGHT = 600

# Below this fraction of the size they can resolve, no amount of contrast helps:
# the strokes are finer than the eye can separate at all.
UNRESOLVABLE_BELOW = 0.6

# The contrast a mark needs to survive the optics, for text exactly at the limit
# of what this person resolves. Larger text needs proportionally less, which is
# the same relationship the guidelines encode by asking 3:1 of large text and
# 4.5:1 of body text.
THRESHOLD_AT_LIMIT = 0.10
MIN_THRESHOLD = 0.035
MAX_THRESHOLD = 0.45


def resolvable_stroke_px(acuity: float) -> float:
    """The finest stroke these eyes can separate, in CSS pixels."""
    return ARCMINUTE_PX / max(float(acuity), 0.05)


def readable_size_px(acuity: float, bold: bool = False) -> float:
    """The smallest font size this person can read, given good contrast.

    At full acuity this is about 5px -- smaller than anyone sets text, which is
    why size never comes up for a typical visitor. At 0.35 it is around 15px, so
    16px body copy is marginal and a 34px heading is comfortable. That is the
    difference the model was missing: it judged both by the same contrast bar.
    """
    ratio = BOLD_STROKE_RATIO if bold else STROKE_RATIO
    return resolvable_stroke_px(acuity) * ratio


def contrast_needed(text_px: float, acuity: float, bold: bool = False) -> dict:
    """How much surviving contrast text of this size needs, for these eyes.

    Text well above the resolution limit reads at low contrast -- which is why
    somebody with poor eyesight can still read a large headline on a page whose
    body copy is invisible to them. Text at the limit needs much more, and text
    below it cannot be read at any contrast at all.
    """
    limit = readable_size_px(acuity, bold)
    if not text_px or text_px <= 0:
        # Nothing said about the size, so size cannot be held against it.
        return {"threshold": THRESHOLD_AT_LIMIT, "comfort": None, "limitPx": round(limit, 1),
                "resolvable": True}
    comfort = float(text_px) / limit
    if comfort < UNRESOLVABLE_BELOW:
        return {"threshold": MAX_THRESHOLD, "comfort": round(comfort, 2),
                "limitPx": round(limit, 1), "resolvable": False}
    threshold = THRESHOLD_AT_LIMIT / (comfort ** 0.9)
    return {"threshold": round(max(MIN_THRESHOLD, min(MAX_THRESHOLD, threshold)), 4),
            "comfort": round(comfort, 2), "limitPx": round(limit, 1), "resolvable": True}


# Roles whose whole purpose is to be read. Anything with a measured font size is
# treated the same way whatever its role.
TEXT_ROLES = frozenset({"heading", "text", "paragraph", "StaticText", "label", "caption",
                        "listitem", "cell", "columnheader", "rowheader", "h1", "h2", "h3"})


def legibility(image: Image.Image, box: dict, margin: int = 12, *,
               font_px: float = 0.0, font_weight: int = 400, acuity: float = 1.0,
               role: str = "") -> dict:
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

    # Structure inside, measured strictly inside. A box includes the element's own
    # boundary, and blur pulls the surround across it -- so a mid-grey button on
    # white reported *more* internal contrast at 0.4 acuity (0.23) than with
    # perfect vision (0.12), because blur had imported white into the edge pixels.
    # The same way blur once "helped" a heading by bleeding white inward. Whatever
    # is written on something is written inside it, so that is where to look.
    inset = int(min(_MAX_INSET_PX, max(0, min(right - left, bottom - top) // 6)))
    inner = np.asarray(grey.crop((left + inset, top + inset,
                                  max(left + inset + 1, right - inset),
                                  max(top + inset + 1, bottom - inset))), dtype=np.float32)
    internal = float(inner.max() - inner.min()) / 255.0
    background = float(np.median(inner))
    # What counts as a mark has to scale with how much contrast survived. A fixed
    # twelve grey levels meant that once the optics had compressed a page, every
    # stroke sat within twelve levels of the background and the region read as
    # blank -- so a 44px heading this person could plainly read was reported
    # unreadable, having already passed the contrast test. The point of `ink` is to
    # reject a region whose range comes from one stray pixel, and a share of the
    # surviving range does that without also rejecting faint-but-real text.
    mark = max(_MIN_MARK_LEVELS, internal * 255.0 * _MARK_SHARE)
    ink = float(np.mean(np.abs(inner - background) > mark))

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

    # How much contrast a mark of this size needs to survive, for these eyes. A
    # flat threshold judged a 34px heading and 11px small print by the same bar,
    # and physically the first is readable at a contrast the second is not: blur
    # takes out a 1px stroke and barely touches a 4px one. This is the same
    # relationship the guidelines encode by asking less of large text.
    sizing = contrast_needed(font_px, acuity, font_weight >= BOLD_WEIGHT)
    required = sizing["threshold"]

    has_text = sizing["resolvable"] and internal >= required and ink >= 0.005
    has_shape = edge >= 0.05

    # Something you are meant to read is judged on whether you can read it, not on
    # whether you can tell it is there. Letting edge contrast stand in for both
    # made a paragraph of unresolvable grey smudge count as legible, because the
    # smudge as a whole still differs from the white page around it -- and "there
    # is something there" is not "I can read it". A solid control is the opposite
    # case: it has no text of its own and its edge is the whole of it.
    reads_as_text = bool(font_px) or role in TEXT_ROLES
    visible = has_text if reads_as_text else (has_text or has_shape)

    # The DOM says there is text here and the capture has no ink in it at all --
    # not faint ink, none. That is the two sources disagreeing about what exists,
    # which is a different claim from "this text is hard to read" and must not be
    # reported as a measured contrast ratio. A live run filed "Fails WCAG AA
    # contrast: 'Sourcing' -- 1.01:1" against a 486x21 region that was blank page
    # below a chat bubble: an element of the site's animated mock-up conversation
    # that had not painted yet. The same element was reported 200px higher on the
    # next step, which is what an animation looks like from here.
    nothing_drawn = False
    if visible:
        reason = ""
    elif reads_as_text and has_shape:
        # The most useful thing this measurement can say, and it needs both halves
        # to say it: they can see that something is written there and cannot make
        # out what.
        reason = ("they can see something is written here and cannot make out what"
                  + (f" -- {int(font_px)}px at this contrast" if font_px else ""))
    elif not sizing["resolvable"] and not has_shape:
        reason = (f"at {int(font_px)}px it is finer than this person resolves "
                  f"(they need about {sizing['limitPx']}px), so no amount of contrast helps")
    elif internal < 0.02 and edge < 0.02:
        reason = "the region and everything around it are the same flat colour"
        nothing_drawn = True
    elif internal < required and not has_shape:
        reason = ("too little contrast to make anything out"
                  + (f" at {int(font_px)}px, which for this person needs more than larger text would"
                     if font_px and (sizing["comfort"] or 9) < 1.6 else ""))
    else:
        reason = "nothing in the region stands out from its background"
    return {"visible": visible, "reason": reason, "ink": round(ink, 4),
            "internalContrast": round(internal, 4), "edgeContrast": round(edge, 4),
            "requiredContrast": required, "fontPx": int(font_px or 0),
            "resolvableSizePx": sizing["limitPx"], "sizeComfort": sizing["comfort"],
            # Whether they could tell something was there, which is a different
            # question from whether they could read it.
            "presentButUnreadable": bool(reads_as_text and has_shape and not has_text),
            # Whether anything was drawn in this region at all. See above: a blank
            # crop is the DOM and the capture disagreeing, not a contrast failure.
            "nothingDrawn": bool(nothing_drawn and ink <= 0.0005)}


# WCAG 2.2 relative-luminance coefficients and the sRGB transfer function. These
# are the published numbers, not an approximation of them.
_LUMA = (0.2126, 0.7152, 0.0722)
_SRGB_KNEE = 0.04045

# Where "the text" and "the background" are taken from inside a region. Extremes
# would be a single antialiased pixel; the deciles are what a reader's eye
# integrates over a glyph and the paper behind it.
_INK_PERCENTILE = 10
_PAPER_PERCENTILE = 90
# How far below the paper a pixel has to sit to count as a mark rather than as
# the background's own noise (JPEG ringing, a gradient, a subpixel edge).
_INK_SEPARATION = 0.02
# Below this WCAG ratio between two luminances they are one colour, not two.
#
# A ratio rather than an absolute difference, because luminance is not linear in
# what the eye does with it: #232326 on #19191e differ by 0.006 of relative
# luminance and stand at 1.10:1, which is a real and failing contrast between two
# distinguishable darks. An absolute epsilon large enough to catch a uniform white
# region swallows every dark-on-dark control along with it.
_SAME_COLOUR_RATIO = 1.02
# And how much of the region has to be marks before they are treated as ink. Two
# pixels in a thousand is below the stroke coverage of any real text and above
# what compression noise produces.
_MIN_MARK_SHARE = 0.002

# WCAG 2.2 1.4.3 (AA): 4.5:1 for body text, 3:1 for large text and for the
# non-text contrast of a control's boundary (1.4.11).
WCAG_AA_TEXT = 4.5
WCAG_AA_LARGE = 3.0

# 1.4.3 calls text large at 18pt, or 14pt bold -- 24px and 18.66px at the usual
# 96dpi. Height is the only thing a box gives us, so it stands in for size.
LARGE_TEXT_PX = 24.0

# How far outside a solid region to look for what it sits on.
_SURROUND_PX = 12

# How far inside an element to start measuring what is written on it, so its own
# boundary -- and whatever blur has pulled across that boundary -- is excluded.
_MAX_INSET_PX = 4

# What counts as a mark rather than as background: a share of whatever contrast
# survived the optics, with a floor so a flat region cannot manufacture marks.
_MARK_SHARE = 0.35
_MIN_MARK_LEVELS = 4.0


def relative_luminance(pixels: np.ndarray) -> np.ndarray:
    """WCAG relative luminance for an array of sRGB values in 0..255."""
    channels = pixels.astype(np.float32) / 255.0
    linear = np.where(channels <= _SRGB_KNEE, channels / 12.92,
                      ((channels + 0.055) / 1.055) ** 2.4)
    return linear[..., 0] * _LUMA[0] + linear[..., 1] * _LUMA[1] + linear[..., 2] * _LUMA[2]


def _same_colour(one: float, other: float) -> bool:
    """Whether two relative luminances are the same colour as far as contrast goes."""
    lighter, darker = max(one, other), min(one, other)
    return (lighter + 0.05) / (darker + 0.05) < _SAME_COLOUR_RATIO


def _luminance_for_ratio(lighter: float, required: float) -> float | None:
    """The relative luminance the darker side must not exceed to reach `required`
    against `lighter`.

    From the WCAG definition itself: (L1 + 0.05) / (L2 + 0.05) >= required, solved
    for L2. Returns None when no darker value can get there -- pure black against
    this background still falls short, so the lighter side is what has to move,
    and saying "darken the text" would be advice that cannot be followed.
    """
    target = (lighter + 0.05) / required - 0.05
    return round(target, 4) if target >= 0 else None


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
    flat = luminance.ravel()
    paper = float(np.percentile(flat, _PAPER_PERCENTILE))
    # Ink is whatever differs from the paper, however little of the box it covers.
    #
    # A fixed low percentile of the whole region assumes text fills a fair share of
    # its box, and headings do not: measured on a real capture, "Start free. Keep
    # what makes you sharper." -- 44px bold, near-black on near-white, across a
    # 620x100 box holding two lines -- came back at 1.06:1, because glyph strokes
    # cover under a tenth of that area and the tenth percentile was still
    # background. Sparse text is the case the number matters most for; a heading a
    # sighted reader can obviously read must not measure as failing.
    #
    # So find the marks first, then take the percentile among those: the darkest
    # part of the ink, which is the glyph core a reader actually resolves rather
    # than its antialiased edge. Below a floor of differing pixels there is nothing
    # to call ink and the old whole-region reading stands, which is what keeps a
    # genuinely flat region flat and hands it to the surround comparison below.
    marks = flat[flat < paper - _INK_SEPARATION]
    ink = (float(np.percentile(marks, _INK_PERCENTILE))
           if marks.size >= max(4, int(_MIN_MARK_SHARE * flat.size))
           else float(np.percentile(flat, _INK_PERCENTILE)))

    # A region of one flat colour has no internal contrast to measure, and taking
    # its deciles gives 1.0:1 for a solid black button on white -- which reads as
    # the worst possible result for one of the most legible things on a page. That
    # is not a bug in the arithmetic, it is the wrong question: a solid control has
    # no text of its own, and what WCAG asks about it (1.4.11, non-text contrast)
    # is its boundary against what surrounds it.
    against = "text against its own background"
    if _same_colour(paper, ink):
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
        # Flat inside, and the same flat outside. A real control against a real
        # background is never 1.00:1 -- that number means the crop and its
        # surroundings are one uniform colour, which is a failure to find the
        # element rather than a measurement of it. Saying so is the honest answer;
        # reporting 1:1 hands every caller a compliance verdict on pixels that do
        # not contain the thing. A live report published "Fails WCAG AA contrast:
        # '/ user / year' -- 1:1" with an ink luminance and a paper luminance of
        # 0.9829 apiece, which is this arithmetic faithfully reporting that it had
        # been given one colour twice.
        if _same_colour(paper, ink):
            return {"ratio": None, "required": None, "passes": None, "largeText": False,
                    "measured": "a flat region indistinguishable from its surroundings"}

    lighter, darker = max(ink, paper), min(ink, paper)
    ratio = (lighter + 0.05) / (darker + 0.05)

    # 1.4.11 asks 3:1 of a control's boundary, whatever its size.
    if against.startswith("a solid"):
        required, large = WCAG_AA_LARGE, False
    else:
        large = float(box.get("height", 0)) >= LARGE_TEXT_PX
        required = WCAG_AA_LARGE if large else WCAG_AA_TEXT
    return {"ratio": round(float(ratio), 2), "required": required,
            "passes": bool(ratio >= required), "largeText": large, "measured": against,
            # The two luminances the ratio was computed from, and what the darker
            # of them would have to become to clear the requirement against the
            # lighter one. A report can then say what to change rather than that
            # something should change: "#8a8a8a on #f5f5f5, needs #595959 or
            # darker" is a fix, "raise the contrast to at least 4.5:1" is a
            # restatement of the guideline. Luminance rather than colour because
            # that is what was measured -- many colours share one luminance, and
            # naming a specific hex the page does not use would be a guess
            # dressed as a measurement.
            "inkLuminance": round(darker, 4), "paperLuminance": round(lighter, 4),
            "needsLuminanceBelow": _luminance_for_ratio(lighter, required)}
