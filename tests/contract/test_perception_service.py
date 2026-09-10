"""The perception service over HTTP.

The library is tested in test_perception.py; these pin the contract the journey
worker actually calls, and the refusals -- because everything reaching this
service is base64 handed over by another process, and a PNG that costs four
kilobytes on the wire can ask for gigabytes of memory on decode.
"""
import base64
import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.perception_service.main import app

client = TestClient(app)


def encode(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def page():
    image = Image.new("RGB", (1280, 900), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((100, 60, 700, 110), fill=(15, 15, 20))       # a heading
    draw.rectangle((100, 400, 620, 424), fill=(245, 245, 245))   # a caption's ground
    draw.rectangle((104, 406, 600, 418), fill=(233, 233, 233))   # grey on grey
    draw.rectangle((100, 600, 340, 660), fill=(20, 130, 70))     # a button
    return image


ELEMENTS = [
    {"selector": "e1", "role": "heading", "name": "The headline",
     "box": {"x": 100, "y": 60, "width": 600, "height": 50}},
    {"selector": "p@100,400", "role": "text", "name": "Small print about pricing",
     "box": {"x": 100, "y": 400, "width": 520, "height": 24}},
    {"selector": "e2", "role": "button", "name": "Get started",
     "box": {"x": 100, "y": 600, "width": 240, "height": 60}},
]


def perceive(**overrides):
    body = {"screenshotBase64": encode(page()), "elements": ELEMENTS,
            "viewport": {"width": 1280, "height": 900}}
    body.update(overrides)
    return client.post("/v1/perceive", json=body)


def test_health_says_whether_a_screen_parser_is_installed():
    """The optional half has to be legible from outside: a deployment without a
    detector should be obvious, not something inferred from missing findings."""
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert "available" in body["detector"] and "configured" in body["detector"]


def test_the_same_page_reaches_two_people_differently():
    sharp = perceive(abilities={"vision": {"acuity": 1.0, "contrastSensitivity": 1.0}}).json()
    dim = perceive(abilities={"vision": {"acuity": 0.35, "contrastSensitivity": 0.25}}).json()

    assert sharp["counts"]["notPerceived"] == 0
    lost = [item["selector"] for item in dim["notPerceived"]]
    assert "p@100,400" in lost, "grey-on-grey small print is the first thing to go"
    # The heading and the button survive. A model that makes every page unusable
    # for anyone with less than perfect sight is not finding real problems.
    assert "e1" not in lost and "e2" not in lost


def test_the_observation_is_what_the_actor_should_be_handed():
    """The worker passes this straight through, so an element that was never
    looked at must not appear in it however tempting the DOM entry is."""
    body = perceive(behavior={"patience": 0.05}).json()
    assert body["observation"]
    for item in body["notLookedAt"]:
        assert f"[{item['selector']}]" not in body["observation"]
    for item in body["notPerceived"]:
        assert f"[{item['selector']}]" not in body["observation"]


def test_the_scan_pattern_and_the_reasons_for_it_come_back():
    """A finding that says "they never saw the pricing" is only usable if the
    report can also say why -- which pattern, and what about the persona chose it."""
    body = perceive(behavior={"patience": 0.05}).json()
    assert body["scan"]["pattern"] == "spotted"
    assert body["scan"]["why"], "a pattern with no reason is a magic number"
    assert body["scan"]["fixationBudget"] < 10


def test_a_capture_too_large_to_decode_is_refused_rather_than_attempted():
    """A decompression bomb: a PNG of one flat colour costs a few kilobytes on
    the wire and asks for gigabytes on decode."""
    bomb = Image.new("RGB", (12000, 12000), (255, 255, 255))
    response = perceive(screenshotBase64=encode(bomb))
    assert response.status_code == 422
    assert "decode" in response.json()["detail"]


def test_more_motion_frames_than_the_ring_holds_are_refused():
    """Eight is what viewportStream keeps; a caller asking to difference fifty is
    asking for something that would not mean anything anyway."""
    frame = encode(page())
    assert perceive(motionFrames=[frame] * 9).status_code == 422
    assert perceive(motionFrames=[frame] * 2).status_code == 200


def test_something_that_is_not_an_image_is_a_bad_request_not_a_stack_trace():
    assert perceive(screenshotBase64="bm90IGFuIGltYWdl").status_code == 422


def test_an_element_without_a_box_is_dropped_rather_than_guessed_at():
    body = perceive(elements=ELEMENTS + [{"selector": "e9", "role": "link", "name": "No box"}]).json()
    seen = {item["selector"] for item in
            body["perceived"] + body["notPerceived"] + body["notLookedAt"]}
    assert "e9" not in seen
