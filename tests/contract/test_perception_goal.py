"""A scan is not a survey.

Somebody who came to find a price does not read a features page evenly and then
decide. Their eye goes to anything that might be the thing they came for, and
everything else is scenery. Without this the spotted pattern had nothing to
spot: on a real Chromium rendering, a persona who came to find the price fixated
six paragraphs of feature copy and never looked at the price, which was bolder
and larger than any of them.
"""
import base64
import io

from PIL import Image, ImageDraw

from services.perception_service.goal import affinity, terms
from services.perception_service.perceive import perceive


def test_the_words_that_say_what_somebody_wants_are_kept_and_the_rest_dropped():
    assert terms("find out how much it costs") == {"much", "costs"}
    assert terms("the a of and") == set(), "a goal made only of glue words says nothing"


def test_a_price_is_recognised_by_how_it_is_written_not_only_by_its_words():
    """"From EUR 49 per month" shares no word with "find the price" and is
    exactly what was being looked for."""
    wanted = terms("find the price")
    assert affinity("From EUR 49 per month", wanted) > 0.8
    assert affinity("$12.99", wanted) > 0.8
    assert affinity("Everything you need for step 4 of your workflow.", wanted) == 0.0


def test_pricing_counts_as_price_because_that_is_how_pages_are_written():
    """Exact matching walked a price-hunter straight past a heading saying Pricing."""
    wanted = terms("find the price")
    assert affinity("Pricing", wanted, "link") > 0.5
    assert affinity("Plans and pricing", wanted, "heading") > 0.5
    # And the prefix rule is not so loose that any short word matches.
    assert affinity("Cardigan sizes", terms("rent a car")) == 0.0


def test_free_is_not_treated_as_a_price():
    """It is money-adjacent enough to match almost any marketing page, and it
    made "Start free trial" outrank the actual price."""
    wanted = terms("find the price")
    assert affinity("Start free trial", wanted, "link") == 0.0


def test_a_control_that_names_the_goal_beats_prose_that_mentions_it():
    """A navigation label naming the thing is a promise about where it is."""
    wanted = terms("contact support")
    assert affinity("Contact support", wanted, "link") > affinity("contact support hours vary", wanted, "")


def test_the_hunt_finds_the_price_before_it_reads_the_feature_copy():
    """The behaviour this file exists for, measured end to end."""
    image = Image.new("RGB", (1000, 800), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    # Text-shaped, not solid bars: a filled rectangle has no internal structure,
    # so it is not readable and must not stand in for a line of copy.
    for top in range(60, 700, 90):
        for x in range(40, 700, 4):
            draw.rectangle((x, top, x + 1, top + 40), fill=(35, 35, 35))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

    elements = [{"selector": f"f{index}", "role": "text",
                 "name": f"Everything you need for step {index} of your workflow.",
                 "box": {"x": 40, "y": 60 + index * 90, "width": 660, "height": 40},
                 "fontPx": 16}
                for index in range(6)]
    elements.append({"selector": "price", "role": "text", "name": "From EUR 49 per month",
                     "box": {"x": 40, "y": 600, "width": 660, "height": 40}, "fontPx": 22})

    hurried = {"patience": 0.1}
    hunting = perceive(image_base64=encoded, elements=elements, behavior=hurried,
                       viewport={"width": 1000, "height": 800}, goal="find the price")
    assert hunting["perceived"][0]["selector"] == "price", \
        "somebody who came for the price looks at the price first"
    assert hunting["scan"]["lookingFor"] == ["price"]

    # With no goal there is nothing to hunt for, and the page's own shape decides.
    aimless = perceive(image_base64=encoded, elements=elements, behavior=hurried,
                       viewport={"width": 1000, "height": 800})
    assert aimless["perceived"][0]["selector"] != "price"


def test_a_patient_reader_is_pulled_less_by_the_goal_than_a_hunter():
    """Both are goal-directed; only one is single-minded about it. A reader who
    settles in still works through the page rather than snatching one line."""
    from services.perception_service.scanpath import choose_pattern

    hunter = choose_pattern({"patience": 0.1})
    reader = choose_pattern({"patience": 0.9, "verificationTendency": 0.9})
    assert hunter.goal_pull > reader.goal_pull * 2


def test_a_goal_about_cost_is_pulled_to_the_link_that_says_pricing():
    """"costs" and "Pricing" are not inflections of each other, so the prefix rule
    cannot join them and correctly does not try. They are the same want, and
    MONEY_WORDS already knows it -- it was only ever used to gate the currency
    marks. A live run gave the site's own Pricing link an affinity of 0.00 for a
    persona whose task was "find out what it costs", so the one link that promised
    the answer pulled no harder than the feature copy around it; the run spent five
    steps scrolling the homepage before clicking it."""
    from services.perception_service.goal import affinity, terms

    wanted = terms("Find out what it costs, and say plainly whether the page tells you.")

    answer = affinity("£200 / user / year", wanted, "span")
    promise = affinity("Pricing", wanted, "link")
    mention = affinity("Our pricing is simple", wanted, "p")

    assert answer > promise > mention > 0, (
        "the answer written out beats the link promising it, which beats prose about it")
    assert promise >= 0.8
    # Other words for the same want, not just the one the task happened to use.
    assert affinity("Plans", wanted, "link") >= 0.8
    assert affinity("Subscription", wanted, "link") >= 0.8


def test_a_free_trial_still_does_not_outrank_a_price():
    """The failure this file was written for. "free" is money-adjacent enough to
    match almost any marketing page, and letting it in made "Start free trial"
    outrank "From EUR 49 per month" for somebody hunting for the price. Widening
    the money match to synonyms must not quietly let it back."""
    from services.perception_service.goal import affinity, terms

    wanted = terms("Find out what it costs.")

    assert affinity("Start free trial", wanted, "button") == 0.0
    assert affinity("Start free. Keep what makes you sharper.", wanted, "heading") == 0.0
    assert affinity("From EUR 49 per month", wanted, "p") > 0.8
    # And an unrelated control gains nothing from the control bonus.
    assert affinity("Sign in", wanted, "link") == 0.0


def test_a_goal_about_getting_in_touch_finds_the_support_link():
    """The same shape, for the other thing people most often arrive hunting for."""
    from services.perception_service.goal import affinity, terms

    plain = terms("Find out how to contact support about a billing problem.")
    assert affinity("Support", plain, "link") >= 0.8
    assert affinity("help@example.com", plain, "span") >= 0.8
    assert affinity("Careers", plain, "link") == 0.0

    # And the phrasing people actually use, which this set did not recognise.
    colloquial = terms("Find a way to get in touch with someone about a billing problem.")
    assert affinity("Support", colloquial, "link") >= 0.8
    assert affinity("Careers", colloquial, "link") == 0.0
