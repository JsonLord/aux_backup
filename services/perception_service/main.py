"""The perception service over HTTP, so the journey worker can ask in Node.

Kept a separate process rather than folded into the control plane for the same
reason the persona runtime is: its dependencies are its own. numpy and PIL are
cheap, an optional screen parser is not, and neither belongs in the API image
just because one endpoint would like them.
"""
from fastapi import FastAPI, HTTPException

from .detector import ScreenParser, unnamed_elements
from .models import PerceiveRequest, PerceiveResponse
from .perceive import observation_text, perceive

app = FastAPI(title="Perception", version="1.0.0")
parser = ScreenParser()


@app.get("/healthz")
def health():
    return {"status": "ok", "detector": parser.describe()}


@app.post("/v1/perceive", response_model=PerceiveResponse)
def perceive_page(body: PerceiveRequest):
    """What this persona saw of this page, and what they did not.

    The elements a caller sends are the DOM's account of the page. They are the
    candidate list and the ground truth to diff against; they are never handed
    to the actor as-is, which is the failure this service exists to end.
    """
    elements = [
        {"selector": element.selector, "role": element.role, "name": element.name,
         "box": (element.box or element.boundingBox).model_dump() if (element.box or element.boundingBox) else None}
        for element in body.elements
    ]
    elements = [element for element in elements if element["box"]]

    detections: list[dict] = []
    undeclared: list[dict] = []
    if body.detectUnnamed and parser.available:
        # Detection runs on the raw capture, not the degraded one: the parser
        # stands in for the page's own rendering, and legibility() applies this
        # persona's eyes to whatever it finds, same as for a DOM element.
        from .perceive import _decode

        detections = parser.detect(_decode(body.screenshotBase64))
        undeclared = unnamed_elements(detections, elements)
        elements = elements + [
            {"selector": item["selector"], "role": item["role"], "name": item["name"],
             "box": item["box"]} for item in undeclared
        ]

    try:
        result = perceive(
            image_base64=body.screenshotBase64,
            elements=elements,
            abilities=body.abilities.model_dump(),
            behavior=body.behavior,
            motion_frames=body.motionFrames,
            viewport=body.viewport.model_dump() if body.viewport else None,
            return_seen_image=body.returnSeenImage,
        )
    except ValueError as error:
        # A capture too large to decode, or one that is not an image at all.
        raise HTTPException(422, str(error)) from error

    result["observation"] = observation_text(result)
    result["detector"] = {
        **parser.describe(),
        "requested": body.detectUnnamed,
        "detected": len(detections),
        # Drawn on the page and declared by nothing: a person can read it, a
        # screen reader cannot, and no DOM check can find it.
        "undeclared": undeclared,
    }
    return result
