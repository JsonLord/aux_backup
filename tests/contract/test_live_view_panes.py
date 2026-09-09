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
