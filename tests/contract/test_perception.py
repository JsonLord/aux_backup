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


def glyphs(draw, box, fill, stroke=2, gap=4):
    """Something text-shaped: strokes with paper between them.

    Solid bars will not do, and finding that out was the point. Text is legible
    because it has internal structure -- ink and background interleaved at glyph
    scale -- and a filled rectangle has none. Once legibility judged text on
    whether it could be *read* rather than on whether something was there, every
    fixture drawing solid bars started reporting its "text" as unreadable, which
    was the fixtures being wrong rather than the model.
    """
    left, top, right, bottom = box
    for x in range(left, right, gap):
        draw.rectangle((x, top, min(x + stroke - 1, right), bottom), fill=fill)


def page(*, faint_text=True, width=1280, height=900):
    """A page with one bold heading, one faint caption and one solid button."""
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    # A heading: near-black on white, unmissable, and large.
    glyphs(draw, (100, 60, 700, 110), (15, 15, 20), stroke=5, gap=11)
    # A caption in the usual designer grey: #999 on white is 2.85:1, which a
    # sharp-eyed reader manages and someone with reduced contrast sensitivity does
    # not. Deliberately not #e9e9e9 on #f5f5f5 -- that is 1.11:1, unreadable to
    # everybody, so it cannot show the difference between two people. It only
    # looked like it could while an unreadable smudge still counted as legible
    # because the block it sat in differed from the page.
    caption = (153, 153, 153) if faint_text else (40, 40, 40)
    glyphs(draw, (104, 406, 600, 418), caption, stroke=2, gap=4)
    # A button: solid green, high contrast. No text of its own, so its edge is all
    # there is to see -- which is the case the shape path exists for.
    draw.rectangle((100, 600, 340, 660), fill=(20, 130, 70))
    return image


ELEMENTS = [
    {"selector": "h1", "role": "heading", "name": "The headline",
     "box": {"x": 100, "y": 60, "width": 600, "height": 50}, "fontPx": 40, "fontWeight": 700},
    {"selector": "p.caption", "role": "text", "name": "Small print about pricing",
     "box": {"x": 100, "y": 400, "width": 520, "height": 24}, "fontPx": 13, "fontWeight": 400},
    # A solid control: no text of its own, judged on its edge against the page.
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
        glyphs(draw, (100, 100 + index * 60, 400, 140 + index * 60), (30, 30, 30))

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
        glyphs(draw, (100, 100 + index * 60, 400, 140 + index * 60), (30, 30, 30))

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


def two_sizes_of_the_same_grey():
    """One colour, two sizes. #888 on white is 3.54:1 -- which the guidelines
    accept for large text and reject for body copy, entirely independently of any
    simulation."""
    image = Image.new("RGB", (900, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    glyphs(draw, (40, 40, 620, 74), (136, 136, 136), stroke=3, gap=9)     # 44px
    # A 16px font's strokes are about 2px, not 1: drawn thinner than the type it
    # stands for, the fixture makes the model look harsher than it is.
    glyphs(draw, (40, 160, 620, 172), (136, 136, 136), stroke=2, gap=4)   # 16px
    elements = [
        {"selector": "h1", "role": "heading", "name": "Plans and pricing",
         "box": {"x": 40, "y": 40, "width": 580, "height": 34}, "fontPx": 44, "fontWeight": 700},
        {"selector": "p", "role": "text", "name": "Billing is monthly",
         "box": {"x": 40, "y": 160, "width": 580, "height": 12}, "fontPx": 16},
    ]
    return encode(image), elements


def test_a_large_heading_is_read_at_a_contrast_that_loses_the_body_copy():
    """The thing the model got wrong. Somebody with poor eyesight reads a large
    headline on a page whose body copy is invisible to them, because size and
    contrast trade off against each other -- and a flat contrast threshold cannot
    tell a 44px heading from 16px small print at the same colour.
    """
    image, elements = two_sizes_of_the_same_grey()

    dim = perceive(image_base64=image, elements=elements,
                   abilities={"vision": {"acuity": 0.35, "contrastSensitivity": 0.25}},
                   behavior={"patience": 0.95, "verificationTendency": 0.95})
    lost = {item["selector"] for item in dim["notPerceived"]}
    assert "p" in lost, "16px at 3.54:1 is below what these eyes resolve"
    assert "h1" not in lost, "and the same colour at 44px is not -- it is the size that saves it"

    # Sharp eyes read both, and so does a mild impairment: the model has to find
    # real problems, not turn every grey into a defect. 0.5/0.45 is deliberately
    # not asserted either way -- 16px at 3.54:1 is genuinely marginal there, and a
    # test that pins a coin-flip is a test that will be wrong later.
    for abilities in ({"vision": {"acuity": 1.0, "contrastSensitivity": 1.0}},
                      {"vision": {"acuity": 0.75, "contrastSensitivity": 0.7}}):
        result = perceive(image_base64=image, elements=elements, abilities=abilities,
                          behavior={"patience": 0.95, "verificationTendency": 0.95})
        assert result["counts"]["notPerceived"] == 0, abilities


def test_the_size_a_person_can_read_follows_from_their_acuity():
    """Full acuity resolves about 5px of text, which is smaller than anyone sets,
    so size never comes up for a typical visitor. That is why it stayed missing."""
    from services.perception_service.optics import contrast_needed, readable_size_px

    assert 4.5 < readable_size_px(1.0) < 6.5
    assert 14 < readable_size_px(0.35) < 17, "16px body copy is marginal at 0.35"
    assert readable_size_px(0.2) > 24, "at 0.2 most body text is beyond reach"
    # Bold strokes are thicker, which is why the guidelines let bold text be
    # smaller before it counts as small.
    assert readable_size_px(0.35, bold=True) < readable_size_px(0.35)

    # Larger text needs less surviving contrast, and below the resolution limit no
    # contrast is enough.
    assert contrast_needed(44, 0.35)["threshold"] < contrast_needed(16, 0.35)["threshold"]
    assert contrast_needed(8, 0.35)["resolvable"] is False


def test_something_you_can_see_but_not_read_is_reported_as_that():
    """The most useful thing this measurement can say, and it needs both halves of
    it: they can tell something is there and cannot make out what it says.

    A button is where this actually happens -- its own box is the control, so the
    edge against the page is unmistakable, and a low-contrast label inside it is
    not. "There is a button here and I cannot read it" is a different finding from
    either "I cannot see it" or "I can see it fine".
    """
    image = Image.new("RGB", (600, 200), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 70, 320, 130), fill=(96, 112, 128))          # the control
    glyphs(draw, (60, 92, 300, 108), (126, 142, 158), stroke=2, gap=4)   # its label
    elements = [{"selector": "a.cta", "role": "button", "name": "Start free trial",
                 "box": {"x": 40, "y": 70, "width": 280, "height": 60}, "fontPx": 14}]

    result = perceive(image_base64=encode(image), elements=elements,
                      abilities={"vision": {"acuity": 0.4, "contrastSensitivity": 0.3}},
                      behavior={"patience": 0.95, "verificationTendency": 0.95})
    lost = result["notPerceived"]
    assert len(lost) == 1
    assert lost[0]["presentButUnreadable"] is True
    assert "cannot make out what" in lost[0]["reason"]

    # Sharp eyes read the label, so this is about the persona and not the fixture.
    sharp = perceive(image_base64=encode(image), elements=elements,
                     behavior={"patience": 0.95, "verificationTendency": 0.95})
    assert sharp["counts"]["notPerceived"] == 0


def test_a_solid_control_is_still_judged_on_its_edge():
    """It has no text of its own, so internal structure is the wrong question --
    the case the shape path exists for, and it must survive the text rule."""
    result = perceive(image_base64=encode(page()), elements=ELEMENTS,
                      abilities={"vision": {"acuity": 0.35, "contrastSensitivity": 0.25}})
    assert "a.cta" not in {item["selector"] for item in result["notPerceived"]}
