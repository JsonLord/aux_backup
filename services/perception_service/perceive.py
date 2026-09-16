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


# Above this share of a capture's elements coming back illegible, the capture is
# not describing the page. A live run measured five clean steps (0 of 15, 0 of 19,
# 0 of 20 illegible) and then one step at 18 of 29 -- 14 of them "the region and
# everything around it are the same flat colour" -- and the report published
# "Fails WCAG AA contrast" on the site's own navigation bar, at 1:1, for a persona
# with 0.95 acuity, on links the same run clicked twice. The boxes and the pixels
# had come from different scroll positions.
#
# The upstream fix holds the page still and checks it did not move
# (services/journey-worker/node/src/perception.js). This is the independent one,
# and it is independent on purpose: it needs no cooperation from the caller and
# catches any other cause of the same misalignment. It is a ratio rather than a
# count because a page with four elements may legitimately have two bad ones.
#
# Half is the threshold because of what it would mean to be wrong in either
# direction. A page where most of what is on it cannot be read is a blank page,
# and a run that clicked its way through one is proof it was not blank. Against
# that, a genuine page-wide contrast failure loses one capture's findings and is
# still reported from every other step -- the same finding, one fewer time.
UNTRUSTWORTHY_ILLEGIBLE_SHARE = 0.5
# Under this many elements the ratio says nothing: one bad element out of two is
# 50%.
MIN_ELEMENTS_TO_JUDGE = 6

def _outside_capture(box: dict, width: int, height: int) -> bool:
    """Whether any part of this box falls outside the capture.

    Cropping clamps to the image, so a box that overhangs an edge is measured on
    whatever sits inside the edge instead -- which is not the element, and is the
    one case where every number that follows is confidently about the wrong pixels.
    """
    left, top = float(box.get("x", 0)), float(box.get("y", 0))
    return (left < 0 or top < 0
            or left + float(box.get("width", 0)) > width
            or top + float(box.get("height", 0)) > height)


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
        # Part of this element is outside the capture, so the crop is clamped to
        # the edge and measures pixels that are not the element. A live report
        # filed "Fails WCAG AA contrast: '/ user / year' -- 1:1" against a box at
        # y = -10: ten of its twenty-three rows were above the top of the
        # viewport, the crop clamped to y = 0, and what got measured was the top
        # of the page. The recommendation it produced said the darker side sits at
        # 0.9829 and has to reach 0.2943 against a background at 0.9829, which is
        # the arithmetic faithfully reporting that it had been handed one flat
        # colour twice.
        #
        # Judged here rather than asked of the browser, because it follows from
        # the box and the capture and needs no round trip. A clipped element is
        # still something the person can partly see, so it stays a scan candidate
        # when it is legible; what it can never do is carry a claim about the
        # page, because the element was not the thing measured.
        clipped = _outside_capture(box, page.width, page.height)
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
            if not clipped:
                not_perceived.append({**entry, **readable})
            continue
        candidates.append({**entry,
                           "salience": salience_of(seen, box, motion, scanner.distractibility),
                           "goalAffinity": goal_affinity(entry["name"], wanted, entry["role"])})

    measured = len(candidates) + len(not_perceived)
    # Two different things look the same in a count of "illegible", and lumping
    # them together means an animating page trips the wire meant for a misaligned
    # capture.
    #
    # A region with no ink at all is the DOM and the capture disagreeing about
    # what exists. A few of those on a page with fade-in or type-out animations is
    # ordinary; most of the page being those means the boxes and the pixels came
    # from different states and nothing measured here means anything.
    #
    # A region that was drawn and cannot be read is a measurement. Most of a page
    # measuring that way is the other kind of impossible: a page where most of
    # what is on it cannot be read is a blank page, and a run that clicked its way
    # through one is proof it was not blank.
    blank = sum(1 for item in not_perceived if item.get("nothingDrawn"))
    drawn_illegible = len(not_perceived) - blank
    with_ink = len(candidates) + drawn_illegible
    blank_share = (blank / measured) if measured else 0.0
    illegible_share = (drawn_illegible / with_ink) if with_ink else 0.0
    # Said out loud rather than acted on quietly: the caller decides what a capture
    # it cannot trust is worth, and a reader of the run record can see that a
    # measurement was withheld rather than that a page was clean.
    # And the two together, which is the question the guard is actually asking.
    # Splitting the failures across two buckets let a bad capture through: a live
    # run measured 14 blank and 4 illegible out of 29, so 62% of the capture did
    # not resolve -- and 14/29 is 0.483 while 4/15 is 0.267, both under the bar.
    # It published the entire navigation bar as undrawn. How a capture's failures
    # divide says which sentence to print; it does not change whether most of the
    # capture resolved.
    unresolved_share = (len(not_perceived) / measured) if measured else 0.0
    enough = measured >= MIN_ELEMENTS_TO_JUDGE
    trustworthy = not (enough and (unresolved_share > UNTRUSTWORTHY_ILLEGIBLE_SHARE
                                   or blank_share > UNTRUSTWORTHY_ILLEGIBLE_SHARE
                                   or illegible_share > UNTRUSTWORTHY_ILLEGIBLE_SHARE))

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
        # In the tree, nothing legible where it lives. Empty when the capture
        # cannot be trusted: one misaligned capture publishing a page's whole
        # navigation as a WCAG failure is a worse report than one with a gap.
        "notPerceived": not_perceived if trustworthy else [],
        # Whether this capture is describing the page the boxes describe, and why
        # not. `illegibleShare` is reported either way so the judgement can be
        # checked rather than taken.
        "capture": {"trustworthy": trustworthy, "measured": measured,
                    "illegibleShare": round(illegible_share, 4),
                    "blankShare": round(blank_share, 4),
                    "unresolvedShare": round(unresolved_share, 4),
                    "reason": "" if trustworthy else
                              (f"{blank} of {measured} regions the tree says hold something had no "
                               f"ink in them at all, which reads as boxes and pixels taken from "
                               f"different states of the page"
                               if blank_share > UNTRUSTWORTHY_ILLEGIBLE_SHARE else
                               f"{drawn_illegible} of {with_ink} regions that were drawn measured "
                               f"illegible, which reads as a capture that does not line up with "
                               f"the boxes rather than as a page"
                               if illegible_share > UNTRUSTWORTHY_ILLEGIBLE_SHARE else
                               f"{len(not_perceived)} of {measured} regions did not resolve at all "
                               f"-- {blank} with no ink and {drawn_illegible} drawn but illegible "
                               f"-- which is too much of one capture to stand behind however the "
                               f"failures divide")},
        # Legible, but this person never got to it.
        "notLookedAt": [{"selector": item["selector"], "role": item["role"], "name": item["name"],
                         "box": item["box"], "salience": item["salience"],
                         "goalAffinity": item["goalAffinity"],
                         "contrast": item["contrast"]} for item in not_looked_at],
        "counts": {"elements": len(elements), "legible": len(candidates),
                   "fixated": len(fixations),
                   "notPerceived": len(not_perceived) if trustworthy else 0,
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
    if not lines:
        # Looked, and took in nothing. That is a real thing for a page to do to
        # somebody and the strongest finding this service can produce -- and it
        # used to be returned as "", which the caller could not tell from a
        # service that had failed, so it discarded the whole result: the counts,
        # the notPerceived list, every legibility finding on the capture. The
        # runs where a person could read nothing were exactly the runs whose
        # evidence was thrown away.
        unreadable = result.get("counts", {}).get("notPerceived", 0)
        return (f"You cannot make out anything here. {unreadable} thing(s) are on this part of "
                "the page and none of them are legible to you." if unreadable
                else "You cannot make out anything here.")
    return "\n".join(lines)
