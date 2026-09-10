"""The shape of a perception request, and the caps that keep it from being a weapon.

Everything here arrives as base64 from another process, so the limits are part
of the contract rather than defensive decoration: a page can be stitched to ten
screens tall, a frame ring holds eight frames, and a caller that asks for more
than that is asking for something the service should refuse rather than attempt.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The journey worker's viewport ring is eight frames (viewportStream.js RING_SIZE),
# and differencing more than that buys nothing -- motion is a property of the last
# second or two, not of the whole visit.
MAX_MOTION_FRAMES = 8

# Beyond this many elements a page is not being scanned, it is being crawled, and
# the fixation budget makes the tail irrelevant anyway.
MAX_ELEMENTS = 600


class Box(BaseModel):
    model_config = ConfigDict(extra="ignore")

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0


class Element(BaseModel):
    """The DOM's own account of one thing on the page.

    Used as the candidate list and as the ground truth to diff against -- never
    as the thing the persona perceives. That distinction is the whole point of
    the service.
    """

    model_config = ConfigDict(extra="ignore")

    selector: str = ""
    role: str = ""
    name: str = ""
    box: Box | None = None
    boundingBox: Box | None = None


class Vision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    colorVision: Literal["typical", "protanopia", "deuteranopia", "tritanopia", "custom"] = "typical"
    acuity: float = Field(default=1.0, ge=0.0, le=1.0)
    contrastSensitivity: float = Field(default=1.0, ge=0.0, le=1.0)
    glareSensitivity: float = Field(default=0.0, ge=0.0, le=1.0)


class Abilities(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vision: Vision = Field(default_factory=Vision)
    reading: dict[str, Any] = Field(default_factory=dict)


class Viewport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    width: int = Field(default=1280, ge=1, le=20000)
    height: int = Field(default=900, ge=1, le=20000)


class PerceiveRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    screenshotBase64: str
    elements: list[Element] = Field(default_factory=list, max_length=MAX_ELEMENTS)
    abilities: Abilities = Field(default_factory=Abilities)
    # Free-form because the trait set the persona compiler emits is still
    # growing; choose_pattern reads what it knows and ignores the rest.
    behavior: dict[str, Any] = Field(default_factory=dict)
    motionFrames: list[str] = Field(default_factory=list, max_length=MAX_MOTION_FRAMES)
    viewport: Viewport | None = None
    # The page as this person's eyes delivered it, to sit beside a finding that
    # says they could not see something. Costs a JPEG encode, so it is opt-in.
    returnSeenImage: bool = False
    # Ask the screen parser for things the DOM does not name -- text baked into
    # an image, a canvas-drawn control. Ignored when no detector is installed.
    detectUnnamed: bool = False


class PerceiveResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    eyes: dict[str, Any]
    scan: dict[str, Any]
    perceived: list[dict[str, Any]]
    notPerceived: list[dict[str, Any]]
    notLookedAt: list[dict[str, Any]]
    counts: dict[str, int]
    # The perceived set written out as the actor should receive it, so the caller
    # does not have to reimplement the ordering and the omissions.
    observation: str
    detector: dict[str, Any] = Field(default_factory=dict)
    seenImageBase64: str | None = None
