"""A persona sees pixels, not the DOM.

Building perception from the accessibility tree is how a run comes to "see" an
element that rendered blank and to quote text that is not on screen -- both
happened in live runs here. These pin the other way round: the capture is
degraded by the persona's own eyes first, and what is not legible after that is
not perceived, whatever the tree says.
"""
import base64
import io

import pytest
from PIL import Image, ImageDraw

from services.perception_service import Eyes, choose_pattern, legibility, motion_map, perceive, see
from services.perception_service.perceive import observation_text
from services.perception_service.salience import salience_of


def encode(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def page(*, faint_text=True, width=1280, height=900):
    """A page with one bold heading, one faint caption and one solid button."""
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    # A heading: near-black on white, unmissable.
    draw.rectangle((100, 60, 700, 110), fill=(15, 15, 20))
    # A caption: grey on slightly-lighter grey, the first thing to disappear.
    caption = (233, 233, 233) if faint_text else (40, 40, 40)
    draw.rectangle((100, 400, 620, 424), fill=(245, 245, 245))
    draw.rectangle((104, 406, 600, 418), fill=caption)
    # A button: solid green, high contrast.
    draw.rectangle((100, 600, 340, 660), fill=(20, 130, 70))
    return image


ELEMENTS = [
    {"selector": "h1", "role": "heading", "name": "The headline",
     "box": {"x": 100, "y": 60, "width": 600, "height": 50}},
    {"selector": "p.caption", "role": "text", "name": "Small print about pricing",
     "box": {"x": 100, "y": 400, "width": 520, "height": 24}},
    {"selector": "a.cta", "role": "button", "name": "Get started",
     "box": {"x": 100, "y": 600, "width": 240, "height": 60}},
]


def test_faint_text_is_lost_to_poor_contrast_sensitivity_and_kept_by_good_eyes():
    """The measurement behind "present but not perceivable". Same page, same DOM,
    two people -- and for one of them the caption is simply not there."""
    image = encode(page())

    sharp = perceive(image_base64=image, elements=ELEMENTS,
                     abilities={"vision": {"acuity": 1.0, "contrastSensitivity": 1.0}})
    assert sharp["counts"]["notPerceived"] == 0

    dim = perceive(image_base64=image, elements=ELEMENTS,
                   abilities={"vision": {"acuity": 0.35, "contrastSensitivity": 0.25}})
    lost = [item["selector"] for item in dim["notPerceived"]]
    assert "p.caption" in lost, "grey-on-grey small print is the first thing to go"
    # The heading and the button survive: the model must find real problems, not
    # make every page unusable.
    assert "h1" not in lost and "a.cta" not in lost


def test_the_optics_change_the_actual_pixels_not_just_a_manifest():
    """physical.js has described this transform since the beginning and never
    applied it, so every ability slider in the UI was decoration."""
    original = page(faint_text=False)
    blurred = see(original, Eyes(acuity=0.0, contrast_sensitivity=0.3, color_vision="deuteranopia"))
    assert blurred.size == original.size
    assert list(blurred.getdata()) != list(original.getdata())

    # Contrast really is compressed toward mid-grey.
    import numpy as np
    spread = lambda im: float(np.asarray(im.convert("L"), dtype=float).std())
    assert spread(blurred) < spread(original)

    # And unimpaired eyes are a no-op, so a typical persona costs nothing.
    assert list(see(original, Eyes()).getdata()) == list(original.convert("RGB").getdata())


def test_a_region_that_renders_blank_is_reported_as_such_with_a_reason():
    blank = Image.new("RGB", (400, 300), (255, 255, 255))
    verdict = legibility(blank, {"x": 10, "y": 10, "width": 100, "height": 40})
    assert verdict["visible"] is False
    assert "flat colour" in verdict["reason"]
    assert verdict["ink"] == 0.0
    # A blank region has neither internal marks nor an edge against its surround.
    assert verdict["internalContrast"] == 0.0 and verdict["edgeContrast"] == 0.0


def test_the_scan_pattern_comes_from_who_the_person_is():
    """T is one pattern of several, and which one somebody uses depends on why
    they came. Hardcoding it would make every persona look at the same things."""
    impatient = choose_pattern({"patience": 0.15, "exploration": 0.2})
    assert impatient.pattern == "spotted"
    assert impatient.fixations < 10, "an impatient person looks at few things"
    assert any("patience" in reason for reason in impatient.reasons)

    diligent = choose_pattern({"patience": 0.8, "verificationTendency": 0.8})
    assert diligent.pattern == "commitment"
    assert diligent.fixations > impatient.fixations

    assert choose_pattern({"patience": 0.5, "verificationTendency": 0.7}).pattern == "layer-cake"
    assert choose_pattern({"patience": 0.5, "exploration": 0.8}).pattern == "z"
    assert choose_pattern({}).pattern == "f"

    # A slow reader gets through less of the page in the same impatience.
    slow = choose_pattern({"patience": 0.8, "verificationTendency": 0.8},
                          {"reading": {"wordsPerMinute": 90}})
    assert slow.fixations < diligent.fixations


def test_a_short_fixation_budget_means_things_lower_down_are_never_seen():
    """The restriction is the point: not a prompt saying "you are impatient", but
    an impatient person genuinely never reaching the pricing at the bottom."""
    many = [{"selector": f"e{index}", "role": "text", "name": f"Item {index}",
             "box": {"x": 100, "y": 100 + index * 60, "width": 300, "height": 40}}
            for index in range(30)]
    tall = Image.new("RGB", (1280, 2000), (255, 255, 255))
    draw = ImageDraw.Draw(tall)
    for index in range(30):
        draw.rectangle((100, 100 + index * 60, 400, 140 + index * 60), fill=(30, 30, 30))

    hurried = perceive(image_base64=encode(tall), elements=many,
                       behavior={"patience": 0.1}, viewport={"width": 1280, "height": 900})
    assert hurried["counts"]["fixated"] <= 6
    assert hurried["counts"]["notLookedAt"] >= 20

    thorough = perceive(image_base64=encode(tall), elements=many,
                        behavior={"patience": 0.9, "verificationTendency": 0.9},
                        viewport={"width": 1280, "height": 900})
    assert thorough["counts"]["fixated"] > hurried["counts"]["fixated"]


def test_the_actor_is_only_told_what_was_actually_looked_at():
    """An actor handed the whole DOM will use the whole DOM, however carefully the
    prompt asks it not to."""
    many = [{"selector": f"e{index}", "role": "link", "name": f"Link {index}",
             "box": {"x": 100, "y": 100 + index * 60, "width": 300, "height": 40}}
            for index in range(20)]
    tall = Image.new("RGB", (1280, 1400), (255, 255, 255))
    draw = ImageDraw.Draw(tall)
    for index in range(20):
        draw.rectangle((100, 100 + index * 60, 400, 140 + index * 60), fill=(30, 30, 30))

    result = perceive(image_base64=encode(tall), elements=many, behavior={"patience": 0.1})
    text = observation_text(result)
    assert text.count("\n") + 1 <= result["counts"]["fixated"] + 1
    assert "you have not looked at" in text
    for item in result["notLookedAt"]:
        assert f"[{item['selector']}]" not in text


def test_something_blinking_pulls_a_distractible_eye_and_not_a_steady_one():
    """Nothing in a static screenshot reveals an animation, which is why the run
    keeps a ring of viewport frames -- differencing them is the whole detector."""
    frames = []
    for step in range(4):
        frame = page(faint_text=False)
        draw = ImageDraw.Draw(frame)
        # A banner blinking away in the corner, far from the F-pattern's path.
        colour = (255, 40, 40) if step % 2 == 0 else (255, 255, 255)
        draw.rectangle((950, 760, 1250, 860), fill=colour)
        frames.append(encode(frame))

    elements = ELEMENTS + [{"selector": "div.ad", "role": "img", "name": "Special offer!!",
                            "box": {"x": 950, "y": 760, "width": 300, "height": 100}}]

    distractible = perceive(image_base64=frames[0], elements=elements, motion_frames=frames,
                            behavior={"patience": 0.5, "distractionSusceptibility": 0.95})
    steady = perceive(image_base64=frames[0], elements=elements, motion_frames=frames,
                      behavior={"patience": 0.5, "distractionSusceptibility": 0.0})

    def rank(result, selector):
        for item in result["perceived"]:
            if item["selector"] == selector:
                return item["order"]
        return 999

    assert rank(distractible, "div.ad") < rank(steady, "div.ad"), \
        "a blinking banner should reach a distractible person sooner"
    assert any(item["drawnByMotion"] for item in distractible["perceived"])


def test_a_page_that_is_not_moving_produces_no_motion_at_all():
    still = [page(faint_text=False), page(faint_text=False), page(faint_text=False)]
    assert float(motion_map(still).max()) == 0.0
    # And one frame cannot show motion, by definition.
    assert float(motion_map([page()]).max()) == 0.0


def test_salience_is_measured_against_the_surroundings_not_the_whole_page():
    """A dark button on a dark section is not prominent just because the rest of
    the page is white."""
    image = Image.new("RGB", (1000, 800), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 400, 1000, 800), fill=(25, 25, 30))          # a dark section
    draw.rectangle((100, 550, 300, 610), fill=(35, 35, 42))          # a button barely on it
    draw.rectangle((100, 100, 300, 160), fill=(35, 35, 42))          # the same button on white

    on_dark = salience_of(image, {"x": 100, "y": 550, "width": 200, "height": 60}, None)
    on_light = salience_of(image, {"x": 100, "y": 100, "width": 200, "height": 60}, None)
    assert on_light["contrast"] > on_dark["contrast"] * 3


def test_the_page_as_this_person_saw_it_can_be_shown_beside_the_finding():
    result = perceive(image_base64=encode(page()), elements=ELEMENTS,
                      abilities={"vision": {"acuity": 0.3, "contrastSensitivity": 0.3}},
                      return_seen_image=True)
    assert result["seenImageBase64"]
    rendered = Image.open(io.BytesIO(base64.b64decode(result["seenImageBase64"])))
    assert rendered.size == (1280, 900)
    assert result["eyes"]["blurPx"] > 0


def test_the_contrast_ratio_is_the_one_wcag_defines():
    """The objective half of an accessibility finding. Whether a persona with 0.35
    acuity could read something is a fact about the persona; whether the element
    clears 4.5:1 is a fact about the site, and the only half a developer can act on
    without first agreeing whose eyes to believe.

    Checked against published values rather than against itself.
    """
    from services.perception_service.optics import contrast_ratio

    def text(fg, bg=(255, 255, 255)):
        # Stripes at glyph scale: real text is ink and paper interleaved, which is
        # what the percentiles exist to separate.
        image = Image.new("RGB", (300, 60), bg)
        draw = ImageDraw.Draw(image)
        for x in range(12, 288, 4):
            draw.rectangle((x, 12, x + 1, 28), fill=fg)
        return image

    box = {"x": 12, "y": 12, "width": 276, "height": 17}
    assert contrast_ratio(text((0, 0, 0)), box)["ratio"] == 21.0, "black on white is the maximum"
    # #767676 is the canonical AA boundary colour on white.
    boundary = contrast_ratio(text((118, 118, 118)), box)
    assert 4.5 <= boundary["ratio"] <= 4.6 and boundary["passes"] is True
    assert contrast_ratio(text((153, 153, 153)), box)["ratio"] == 2.85, "the designer grey"
    assert contrast_ratio(text((170, 170, 170)), box)["passes"] is False
    assert contrast_ratio(text((233, 233, 233), (245, 245, 245)), box)["ratio"] < 1.2


def test_a_solid_control_is_measured_against_what_surrounds_it():
    """A region of one flat colour has no internal contrast, and its percentiles
    give 1.0:1 for a solid black button on white -- the worst possible score for
    one of the most legible things on a page. That is the wrong question: WCAG
    1.4.11 asks about a control's boundary against its surround.
    """
    from services.perception_service.optics import contrast_ratio

    def button(fill, ground=(255, 255, 255)):
        image = Image.new("RGB", (300, 120), ground)
        ImageDraw.Draw(image).rectangle((20, 20, 260, 80), fill=fill)
        return image

    box = {"x": 20, "y": 20, "width": 240, "height": 60}
    green = contrast_ratio(button((13, 122, 74)), box)
    assert green["passes"] is True and green["required"] == 3.0
    assert "surrounds it" in green["measured"]

    # And the surround must exclude the control itself: a 240x60 button inside a
    # 264x84 expansion is 65% of those pixels, so their median is the button and
    # the ratio came back 1.0:1.
    assert green["ratio"] > 4.0

    assert contrast_ratio(button((248, 248, 248)), box)["passes"] is False
    # The case salience.py cares about too: dark on dark is not prominent just
    # because the rest of the page is white.
    assert contrast_ratio(button((35, 35, 42), (25, 25, 30)), box)["passes"] is False


def test_every_element_carries_its_contrast_so_a_report_can_cite_it():
    result = perceive(image_base64=encode(page()), elements=ELEMENTS,
                      abilities={"vision": {"acuity": 0.35, "contrastSensitivity": 0.25}})
    for item in result["perceived"] + result["notLookedAt"]:
        assert "contrast" in item and "passes" in item["contrast"]
    for item in result["notPerceived"]:
        assert "contrast" in item
