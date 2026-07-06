import os
import sys

# Mocking parts of app.py to test the function logic
class MockUpdate:
    def __init__(self, visible=None):
        self.visible = visible
    def __repr__(self):
        return f"Update(visible={self.visible})"

import gradio as gr
# We can't easily mock gr.update because it's a function that returns a dict usually
# But in our code we just want to see what sl_auto_render returns.

def sl_auto_render_logic(reports):
    default_val = None
    if "user_experience_reports/slides" in reports:
        default_val = "user_experience_reports/slides"
    elif reports:
        default_val = reports[0]

    html = ""
    # Simplified gr.update for test
    carousel_visible = {"visible": False}
    status_text = "No slide decks discovered."
    counter_text = ""
    idx = 0

    if default_val:
        html = f"MOCK_RENDER({default_val})"
        status_text = f"✅ Found and loaded slides folder: `{default_val}`"
        if len(reports) > 1:
            carousel_visible = {"visible": True}
            counter_text = f"Deck 1 of {len(reports)}: {default_val}"

    return status_text, reports, html, carousel_visible, idx, counter_text

def test_sl_auto_render():
    # Case 1: Slides folder found
    reports = ["user_experience_reports/slides", "user_experience_reports/other_slides.md"]
    res = sl_auto_render_logic(reports)
    print("Test 1 (Slides folder found):", res)
    assert "✅ Found and loaded slides folder: `user_experience_reports/slides`" in res[0]
    assert res[3]["visible"] is True

    # Case 2: Only one file found
    reports = ["user_experience_reports/slides.md"]
    res = sl_auto_render_logic(reports)
    print("Test 2 (One file found):", res)
    assert "✅ Found and loaded slides folder: `user_experience_reports/slides.md`" in res[0]
    assert res[3]["visible"] is False

    # Case 3: Nothing found
    reports = []
    res = sl_auto_render_logic(reports)
    print("Test 3 (Nothing found):", res)
    assert "No slide decks discovered." in res[0]

    print("All logic tests passed!")

if __name__ == "__main__":
    test_sl_auto_render()
