"""What pulls the eye, before anyone has decided to look at anything.

Two kinds. Motion is the loud one: a carousel, an autoplaying video, a blinking
call to action. Nothing in a static screenshot reveals it, which is why the
journey worker now keeps a short ring of viewport frames instead of only the
newest -- differencing consecutive frames *is* the detector, and it needs no
model at all.

The rest is static: size, contrast against the surrounding page, colour distance,
and how near the centre something sits. Crude next to a trained saliency model,
and deliberately so for now: it is arithmetic over pixels the run already has,
runs in milliseconds on a CPU, and is honest about being a heuristic. A model
slots in behind the same call when the deployment can carry one.

Everything here works on the page *as the persona sees it* -- optics first -- so a
low-contrast banner that pops for one person genuinely does not for another.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# Below this, a difference between frames is compression noise rather than
# something moving. JPEG frames from a screencast are never bit-identical.
MOTION_NOISE_FLOOR = 12.0

# The grid the motion map is computed on. Fine enough to separate a banner ad
# from the article beside it, coarse enough to stay cheap on a tall page.
MOTION_GRID = 24


def motion_map(frames: list[Image.Image], grid: int = MOTION_GRID) -> np.ndarray:
    """How much each cell of the page changed while nobody was touching it.

    Consecutive differences rather than first-against-last: a carousel that
    returns to its first slide would otherwise read as perfectly still.
    """
    if len(frames) < 2:
        return np.zeros((grid, grid), dtype=np.float32)
    small = [np.asarray(frame.convert("L").resize((grid, grid), Image.LANCZOS), dtype=np.float32)
             for frame in frames]
    changes = np.zeros((grid, grid), dtype=np.float32)
    for earlier, later in zip(small, small[1:]):
        difference = np.abs(later - earlier)
        changes += np.where(difference > MOTION_NOISE_FLOOR, difference, 0.0)
    peak = float(changes.max())
    return changes / peak if peak > 0 else changes


def motion_at(motion: np.ndarray, box: dict, size: tuple[int, int]) -> float:
    """The motion under one region, on a 0-1 scale."""
    width, height = size
    grid = motion.shape[0]
    if not width or not height:
        return 0.0
    left = max(0, min(grid - 1, int(box.get("x", 0) / width * grid)))
    top = max(0, min(grid - 1, int(box.get("y", 0) / height * grid)))
    right = max(left + 1, min(grid, int((box.get("x", 0) + box.get("width", 0)) / width * grid)))
    bottom = max(top + 1, min(grid, int((box.get("y", 0) + box.get("height", 0)) / height * grid)))
    return float(motion[top:bottom, left:right].max())


def static_salience(image: Image.Image, box: dict) -> dict:
    """How much this region stands out from the page around it, standing still.

    Contrast against its own surroundings rather than against the whole page: a
    dark button on a dark section is not prominent just because the page is
    mostly white elsewhere.
    """
    left, top = max(0, int(box.get("x", 0))), max(0, int(box.get("y", 0)))
    right = min(image.width, int(left + max(1, box.get("width", 0))))
    bottom = min(image.height, int(top + max(1, box.get("height", 0))))
    if right <= left or bottom <= top:
        return {"area": 0.0, "contrast": 0.0, "centrality": 0.0}

    grey = image.convert("L")
    region = np.asarray(grey.crop((left, top, right, bottom)), dtype=np.float32)
    margin = max(16, (right - left) // 2)
    around = np.asarray(grey.crop((max(0, left - margin), max(0, top - margin),
                                   min(image.width, right + margin),
                                   min(image.height, bottom + margin))), dtype=np.float32)
    contrast = abs(float(region.mean()) - float(around.mean())) / 255.0

    page_area = float(image.width * image.height) or 1.0
    area = min(1.0, ((right - left) * (bottom - top)) / page_area * 40.0)
    # Horizontal only: a page is scrolled, so "near the middle" vertically means
    # nothing, while the horizontal centre is where the eye rests.
    centre_x = (left + right) / 2.0
    centrality = 1.0 - min(1.0, abs(centre_x - image.width / 2.0) / (image.width / 2.0 or 1.0))
    return {"area": round(area, 4), "contrast": round(contrast, 4),
            "centrality": round(centrality, 4)}


def salience_of(image: Image.Image, box: dict, motion: np.ndarray | None,
                distractibility: float = 0.5) -> dict:
    """Everything about this region that competes for attention, as one number.

    Motion is weighted by how distractible the persona is -- the field the
    persona compiler already produces and nothing has ever read. Someone who is
    hard to distract barely registers the banner; someone who is not will look at
    it instead of the thing they came for, which is the behaviour a page with an
    autoplaying video actually produces.
    """
    parts = static_salience(image, box)
    movement = motion_at(motion, box, image.size) if motion is not None else 0.0
    weight = 0.25 + 1.5 * max(0.0, min(1.0, distractibility))
    score = (movement * weight
             + parts["contrast"] * 0.9
             + parts["area"] * 0.5
             + parts["centrality"] * 0.3)
    return {**parts, "motion": round(movement, 4), "score": round(float(score), 4)}
