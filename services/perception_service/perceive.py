"""What a particular person saw of a page, and what they did not.

The order is the argument. Degrade the capture with the persona's optics first,
then decide what is legible, then decide what got looked at. Doing it the other
way -- reading the DOM and describing it to a model -- is how a run comes to
"see" an element that rendered blank and quote text that is not on screen, both
of which happened in live runs here.

Two things fall out that no DOM-based check can produce:

  notPerceived   in the accessibility tree, and there is nothing legible where it
                 lives. Present but not perceivable.
  notLookedAt    legible, but this person never got to it -- their patience ran
                 out first, or something moving pulled them elsewhere.

The second is not a defect in the page by itself. It is the answer to "why did
they not click the thing that was right there", which is the question a usability
report exists to answer and currently cannot.
"""
from __future__ import annotations

import base64
import binascii
import io

from PIL import Image, UnidentifiedImageError

from .goal import affinity as goal_affinity
from .goal import terms as goal_terms
from .optics import Eyes, contrast_ratio, legibility, see
from .salience import motion_map, salience_of
from .scanpath import choose_pattern, scan


# A stitched full-page capture of a long site runs to about 11 megapixels, so
# this leaves plenty of headroom while still refusing a decompression bomb: a
# PNG that costs a few kilobytes on the wire can otherwise ask for gigabytes of
# RAM here, and every caller of this module is handed base64 by someone else.
MAX_PIXELS = 40_000_000


def _decode(image_base64: str) -> Image.Image:
    """One capture, or a ValueError saying why not.

    Everything here is base64 handed over by another process, so both ways of
    being wrong -- not base64, and base64 of something that is not an image --
    are ordinary inputs rather than bugs. They come back as one kind of error so
    that a caller does not have to catch PIL's exception hierarchy to tell a bad
    request from a broken service.
    """
    try:
        raw = base64.b64decode(image_base64, validate=False)
    except (binascii.Error, ValueError) as error:
        raise ValueError(f"capture is not valid base64: {error}") from error
    try:
        image = Image.open(io.BytesIO(raw))
    except (UnidentifiedImageError, OSError) as error:
        raise ValueError(f"capture is not an image this service can decode: {error}") from error
    width, height = image.size
    if width * height > MAX_PIXELS:
        raise ValueError(f"capture is {width}x{height}, larger than this service will decode")
    try:
        return image.convert("RGB")
    except OSError as error:  # a truncated file only fails once the pixels are read
        raise ValueError(f"capture could not be decoded: {error}") from error


def _encode(image: Image.Image, quality: int = 78) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def perceive(*, image_base64: str, elements: list[dict], abilities: dict | None = None,
             behavior: dict | None = None, motion_frames: list[str] | None = None,
             viewport: dict | None = None, return_seen_image: bool = False,
             goal: str = "") -> dict:
    """Run one page through one persona's eyes.

    `elements` are the DOM's own account of what is there -- selector, role, name
    and box -- which is used as the list of candidates and as the ground truth to
    diff against. It is never used as the thing the persona perceives.

    `goal` is what they came for, in their own words -- the task text. A scan is
    not a survey, and somebody hunting for a price walks past the feature copy
    without reading it.
    """
    page = _decode(image_base64)
    eyes = Eyes.from_abilities(abilities)
    seen = see(page, eyes)

    frames = [_decode(frame) for frame in (motion_frames or [])]
    motion = motion_map(frames) if len(frames) >= 2 else None

    scanner = choose_pattern(behavior, abilities)
    wanted = goal_terms(goal)
    # A page is scrolled, so affinity is judged against the viewport in front of
    # the person, not against a document that may be ten screens tall.
    size = (int((viewport or {}).get("width") or page.width),
            int((viewport or {}).get("height") or min(page.height, 900)))

    candidates: list[dict] = []
    not_perceived: list[dict] = []
    for element in elements:
        box = element.get("box") or element.get("boundingBox") or {}
        if not box:
            continue
        # Size and acuity together, not contrast alone. Somebody with poor
        # eyesight reads a large headline on a page whose body copy is invisible
        # to them, and a flat contrast threshold cannot tell those apart.
        readable = legibility(seen, box, font_px=float(element.get("fontPx") or 0),
                              font_weight=int(element.get("fontWeight") or 400),
                              acuity=eyes.acuity, role=element.get("role", ""))
        entry = {"selector": element.get("selector") or element.get("elementId"),
                 "role": element.get("role", ""), "name": element.get("name") or element.get("text") or "",
                 "box": box,
                 # Measured on the page as drawn, not on the degraded capture.
                 # Whether *this* persona could read something is a fact about the
                 # persona; whether the element clears 4.5:1 is a fact about the
                 # site, true for every visitor, and the only half of an
                 # accessibility finding a developer can act on without first
                 # agreeing whose eyes to believe.
                 "contrast": contrast_ratio(page, box)}
        if not readable["visible"]:
            not_perceived.append({**entry, **readable})
            continue
        candidates.append({**entry,
                           "salience": salience_of(seen, box, motion, scanner.distractibility),
                           "goalAffinity": goal_affinity(entry["name"], wanted, entry["role"])})

    fixations = scan(candidates, size, scanner)
    # Matched by selector, not by object identity: scan() returns a copy of each
    # candidate with its order attached, so `id()` never matches and every
    # element -- including the ones just fixated -- lands in "not looked at".
    fixated = {item["selector"] for item in fixations}
    not_looked_at = [item for item in candidates if item["selector"] not in fixated]

    result = {
        "eyes": {"colorVision": eyes.color_vision, "acuity": eyes.acuity,
                 "contrastSensitivity": eyes.contrast_sensitivity, "blurPx": eyes.blur_px,
                 "unimpaired": eyes.unimpaired},
        "scan": {"pattern": scanner.pattern, "fixationBudget": scanner.fixations,
                 "why": scanner.reasons, "distractibility": scanner.distractibility,
                 "goalPull": scanner.goal_pull, "lookingFor": sorted(wanted),
                 "motionAvailable": motion is not None},
        "perceived": [{"selector": item["selector"], "role": item["role"], "name": item["name"],
                       "box": item["box"], "salience": item["salience"], "order": item["order"],
                       "goalAffinity": item["goalAffinity"], "contrast": item["contrast"],
                       "drawnByMotion": item["drawnByMotion"]} for item in fixations],
        # In the tree, nothing legible where it lives.
        "notPerceived": not_perceived,
        # Legible, but this person never got to it.
        "notLookedAt": [{"selector": item["selector"], "role": item["role"], "name": item["name"],
                         "box": item["box"], "salience": item["salience"],
                         "goalAffinity": item["goalAffinity"],
                         "contrast": item["contrast"]} for item in not_looked_at],
        "counts": {"elements": len(elements), "legible": len(candidates),
                   "fixated": len(fixations), "notPerceived": len(not_perceived),
                   "notLookedAt": len(not_looked_at)},
    }
    if return_seen_image:
        # The page as this person's eyes delivered it -- the honest thing to put
        # beside a finding that says they could not see something.
        result["seenImageBase64"] = _encode(seen)
    return result


def observation_text(result: dict, limit: int = 60) -> str:
    """The perceived set as the actor should receive it: only what was looked at.

    In fixation order, because that is the order it entered the person's head,
    and with nothing else -- an actor handed the whole DOM will use the whole DOM
    however carefully the prompt asks it not to.
    """
    lines = []
    for item in result.get("perceived", [])[:limit]:
        label = (item.get("name") or "").strip()
        role = (item.get("role") or "").strip()
        marker = " (caught your eye)" if item.get("drawnByMotion") else ""
        lines.append(f"[{item.get('selector')}] {role} {label}".rstrip() + marker)
    missed = result.get("counts", {}).get("notLookedAt", 0)
    if missed:
        lines.append(f"... {missed} other thing(s) on the page you have not looked at")
    return "\n".join(lines)
