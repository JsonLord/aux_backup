"""How a particular person's eye moves over a page, and what they end up seeing.

Nielsen Norman's eyetracking work does not describe one reading pattern but a
family, and which one somebody uses depends on who they are and why they came:

  F           a sweep across the top, a shorter second sweep, then down the left
  layer-cake  headings and subheadings, skipping the prose between them
  spotted     hunting for one specific token -- a price, a number, a word
  commitment  actually reading, which is rare and takes motivation
  Z           sparse visual layouts, corner to corner

So the pattern is chosen from the compiled persona rather than fixed. An
impatient visitor with a specific goal scans spotted; a diligent one who
double-checks reads in layer-cake and drifts toward commitment; an explorer with
a vague goal wanders. Those are the same trait fields the DSPy compiler already
produces and that nothing downstream has ever read.

The output that matters is not the path, it is what the path *missed*. A fixation
budget runs out, and everything not fixated was not seen -- so the actor cannot
act on it. That restriction is what makes a persona behave like a person: not a
prompt saying "you are impatient", but an impatient person genuinely never
reaching the pricing table at the bottom of the page.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

PATTERNS = ("spotted", "f", "layer-cake", "commitment", "z")


@dataclass
class Scanner:
    """One persona's way of looking at a page."""

    pattern: str = "f"
    fixations: int = 12
    distractibility: float = 0.5
    # A fixation lands near, but not exactly on, what it was aiming at.
    seed: int = 1
    reasons: list[str] = field(default_factory=list)


def choose_pattern(behavior: dict | None, abilities: dict | None = None) -> Scanner:
    """Pick a way of looking from who this person is.

    Deliberately ordered: a goal-directed hunt beats a careful read, because
    somebody who came for a price does not settle in to read the page even if
    they are conscientious by nature.
    """
    traits = behavior or {}
    def trait(name, default=0.5):
        try:
            return max(0.0, min(1.0, float(traits.get(name, default))))
        except (TypeError, ValueError):
            return default

    patience = trait("patience")
    exploration = trait("exploration")
    verification = trait("verificationTendency")
    distractibility = trait("distractionSusceptibility", 0.5)
    reasons: list[str] = []

    if patience <= 0.35:
        pattern, budget = "spotted", 6
        reasons.append("little patience, so they hunt for the one thing they came for")
    elif verification >= 0.65 and patience >= 0.6:
        pattern, budget = "commitment", 22
        reasons.append("patient and inclined to check things, so they actually read")
    elif verification >= 0.6:
        pattern, budget = "layer-cake", 14
        reasons.append("checks things, so they work through the headings")
    elif exploration >= 0.65:
        pattern, budget = "z", 16
        reasons.append("likes poking around, so their eye wanders the page")
    else:
        pattern, budget = "f", 12
        reasons.append("no strong pull either way, so they scan the usual F")

    # A slow reader gets through less of a page in the same impatience.
    reading = ((abilities or {}).get("reading") or {})
    try:
        words_per_minute = float(reading.get("wordsPerMinute", 220))
    except (TypeError, ValueError):
        words_per_minute = 220.0
    if words_per_minute < 160:
        budget = max(3, int(budget * 0.7))
        reasons.append("reads slowly, so fewer things get looked at before patience runs out")

    return Scanner(pattern=pattern, fixations=budget, distractibility=distractibility,
                   reasons=reasons)


def pattern_affinity(pattern: str, box: dict, size: tuple[int, int], role: str = "") -> float:
    """How much this pattern is drawn to this region, before salience.

    Positions are normalised against the *viewport*, not the whole document: a
    person scans the screen in front of them and then scrolls, so "the top" means
    the top of what is on screen.
    """
    width, height = size
    if not width or not height:
        return 0.0
    x = (box.get("x", 0) + box.get("width", 0) / 2) / width
    y = (box.get("y", 0) + box.get("height", 0) / 2) / height
    heading = role in ("heading", "h1", "h2", "h3")

    if pattern == "f":
        # Two horizontal sweeps and a left-hand stem.
        top_sweep = max(0.0, 1.0 - abs(y - 0.08) * 6)
        second_sweep = max(0.0, 1.0 - abs(y - 0.33) * 5) * 0.8
        stem = max(0.0, 1.0 - x * 2.2) * max(0.0, 1.0 - y) * 0.7
        return max(top_sweep, second_sweep, stem)
    if pattern == "layer-cake":
        return 1.0 if heading else 0.15
    if pattern == "spotted":
        # No shape at all: a hunt goes wherever the target might be, which is why
        # salience and the goal dominate for this pattern.
        return 0.35
    if pattern == "commitment":
        # Top to bottom, in order, missing little.
        return max(0.2, 1.0 - y * 0.4)
    if pattern == "z":
        corners = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0))
        nearest = min(math.hypot(x - cx, y - cy) for cx, cy in corners)
        return max(0.0, 1.0 - nearest * 1.4)
    return 0.5


def scan(candidates: list[dict], size: tuple[int, int], scanner: Scanner) -> list[dict]:
    """Walk the page and return the fixations, in the order they happened.

    Two rules make this a scan rather than a ranking. Inhibition of return: once
    something has been looked at, it stops competing, which is why a person does
    not stare at the same banner for their whole visit. And a budget: the eye
    stops when patience does, and whatever is left was not seen.

    Each candidate is `{box, role, salience}`; `salience` is the score from
    salience.py, already weighted by how distractible this person is.
    """
    remaining = list(candidates)
    fixations: list[dict] = []
    for order in range(max(1, scanner.fixations)):
        if not remaining:
            break
        scored = []
        for candidate in remaining:
            affinity = pattern_affinity(scanner.pattern, candidate.get("box") or {}, size,
                                        candidate.get("role", ""))
            salience = float((candidate.get("salience") or {}).get("score", 0.0))
            # Motion interrupts the pattern rather than adding to it: something
            # blinking pulls the eye off the line it was following, which is the
            # complaint people actually have about animated adverts.
            motion = float((candidate.get("salience") or {}).get("motion", 0.0))
            interrupt = motion * (0.3 + 1.4 * scanner.distractibility)
            scored.append((affinity * 0.7 + salience * 0.6 + interrupt, candidate))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        weight, chosen = scored[0]
        remaining.remove(chosen)
        fixations.append({**chosen, "order": order + 1, "weight": round(float(weight), 4),
                          "drawnByMotion": bool((chosen.get("salience") or {}).get("motion", 0) > 0.25)})
    return fixations
