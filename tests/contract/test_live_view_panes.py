"""The live view shows the running browser twice: whole, and around the pointer."""
import pytest

app = pytest.importorskip("app")

FRAME = "data:image/jpeg;base64,AAAA"
CURSOR = {"x": 640, "y": 360, "viewport": {"width": 1280, "height": 720}}


def test_both_panes_are_drawn_from_the_one_frame():
    # A second view must not cost a second capture, a second browser or a second
    # stream -- it is a crop of the image already on screen.
    html = app.render_live_panes(FRAME, CURSOR)

    assert html.count(FRAME) == 2
    assert "Full viewport" in html
    assert "Pointer close-up" in html


def test_the_close_up_follows_the_pointer():
    left = app.render_live_panes(FRAME, {"x": 128, "y": 72, "viewport": {"width": 1280, "height": 720}})
    right = app.render_live_panes(FRAME, {"x": 1152, "y": 648, "viewport": {"width": 1280, "height": 720}})

    assert "background-position:10.00% 10.00%" in left
    assert "background-position:90.00% 90.00%" in right


def test_a_pointer_outside_the_viewport_cannot_pan_the_close_up_off_the_frame():
    html = app.render_live_panes(FRAME, {"x": 5000, "y": -20, "viewport": {"width": 1280, "height": 720}})
    assert "background-position:100.00% 0.00%" in html


def test_the_close_up_waits_rather_than_magnifying_a_guess():
    # Centring on the middle of the page would imply that is where the agent is
    # looking, which is worse than saying nothing.
    html = app.render_live_panes(FRAME, None)

    assert "The pointer has not moved yet" in html
    assert "waiting for the pointer" in html
    assert html.count(FRAME) == 1, "there is nothing to magnify yet"


def test_the_close_up_keeps_the_viewport_shape():
    html = app.render_live_panes(FRAME, CURSOR)
    assert "aspect-ratio:1280/720" in html


def test_the_frame_and_caption_are_escaped_into_the_markup():
    html = app.render_live_panes('x" onerror="alert(1)', CURSOR, caption='<script>bad</script>')
    assert 'onerror="alert(1)' not in html
    assert "<script>bad</script>" not in html
    assert "&lt;script&gt;" in html


def test_the_close_up_scales_against_the_page_viewport_not_the_stream_metadata():
    """A real frame measured 1280x633 while its metadata reported 1280x720.

    The screencast's deviceWidth/deviceHeight describe the device, not the image,
    so scaling against them would push the close-up off the pointer vertically.
    cursor.viewport is read from the same page the image is a render of.
    """
    cursor = {"x": 1072, "y": 161, "viewport": {"width": 1280, "height": 633}}
    html = app.render_live_panes(FRAME, cursor)

    # 161 / 633, not 161 / 720 (which would be 22.36%).
    assert "background-position:83.75% 25.43%" in html
    assert "aspect-ratio:1280/633" in html


def _live_state(frame):
    return {"status": "live", "elapsedMs": 1000, "frames": 1, "frame": frame,
            "frameName": "001.png", "reasoning": [],
            "cursor": {"x": 10, "y": 10, "viewport": {"width": 100, "height": 100}}}


def test_the_clickable_canvas_is_only_decoded_while_somebody_is_driving(monkeypatch):
    """At two seconds a tick, decoding a frame nobody is clicking on is waste."""
    import base64, io
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(buffer, format="PNG")
    frame = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    monkeypatch.setattr(app, "fetch_live_state", lambda run_id: _live_state(frame))

    *_, idle_canvas = app.poll_live_run("run_1", True, "", False)
    *_, driving_canvas = app.poll_live_run("run_1", True, "", True)

    # An empty update leaves the component alone; the driving one carries a frame.
    assert idle_canvas.get("value") is None and not idle_canvas.get("visible")
    assert driving_canvas["visible"] is True
    assert driving_canvas["value"] is not None


def test_a_stale_pointer_is_shown_dimmed_and_captioned_as_last_seen():
    """Every navigation destroys the on-page marker, and a run that clicks through
    links spends most of its time with no live position -- a five-minute live run
    reported none on all ninety polls. The last real position is still the right
    place to look, so it is shown; what must not happen is showing it as if the
    pointer were there now."""
    panes = app.render_live_panes("data:image/jpeg;base64,AAAA",
                              {"x": 515, "y": 316, "viewport": {"width": 1280, "height": 633},
                               "stale": True, "ageMs": 4200})
    assert "pointer last seen at 515, 316 4s ago" in panes
    assert "opacity:.55" in panes
    # And it is still a crop centred on that position, not the empty-state pane.
    assert "The pointer has not moved yet" not in panes
    assert "background-position:40.23% 49.92%" in panes


def test_a_live_pointer_is_not_dimmed():
    panes = app.render_live_panes("data:image/jpeg;base64,AAAA",
                              {"x": 515, "y": 316, "viewport": {"width": 1280, "height": 633},
                               "stale": False, "ageMs": 0})
    assert "pointer at 515, 316" in panes
    assert "last seen" not in panes
    assert "opacity:.55" not in panes
