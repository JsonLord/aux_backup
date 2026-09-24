"""A slide has to fit the screen.

`.slide` is `overflow-y: auto`, which sounds safe and is not: content past the
fold is simply absent when somebody presents the deck, and nothing says so. This
renders a deck of the worst realistic content -- long findings, a screenshot
each, long recommendations -- at the sizes people actually present at, and
measures.

Measured before the fix: every finding slide lost 49px at 1024x600, the size of
an older projector and of a half-height window.
"""
import base64
import io
import shutil

import pytest

from apps.api.executor import JobExecutor

CHROMIUM = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# Where people present. The last two are where it broke.
SIZES = [(1280, 800), (1440, 900), (1024, 768), (1280, 620), (1024, 600), (820, 1180)]

LONG_SUMMARY = (
    "The persona clicked the navigation item labelled Pricing and arrived on a page consisting "
    "entirely of vision statements about the future of work. They scrolled twice, read three "
    "headings, opened the link marked Research expecting a cost breakdown, and found no number "
    "anywhere on either page. Frustration rose from 0.20 to 0.63 across three actions, confusion "
    "from 0.00 to 0.67, and the coping model sampled abandon. They left after the third action "
    "without completing either task, which for this profile is the expected outcome rather than a "
    "failure of the simulation.")
LONG_FIX = (
    "Put at least one concrete number on the page the Pricing link goes to, even a starting price "
    "with a qualifier, or rename the link so it matches what the page actually shows. A visitor "
    "who follows a link named Pricing and finds philosophy does not conclude the pricing is "
    "elsewhere; they conclude the product is not for them and they leave, which is what happened. "
    "If the price genuinely cannot be published, say so on that page and give the next step.")


def _stress_deck() -> str:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1280, 900), (230, 235, 240)).save(buffer, format="JPEG", quality=60)
    crop = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
    findings = [{
        "severity": "critical", "category": "navigation",
        "title": f"Pricing link leads to a page with no prices on it ({index})",
        "summary": LONG_SUMMARY, "recommendation": LONG_FIX,
        "evidence": "internal contrast 0.035, edge contrast 0.0028, ink 0.0",
        "observation": "The page displays general information about the tool and its philosophy.",
        "screenshotCrop": crop, "screenshotIsRegion": False,
        "runId": "run_1", "personaId": "friedrich_wolf", "source": "blockers",
        "reasoning": "Right, where's the price. Four pages of vision statements and not one number.",
    } for index in range(1, 5)]
    return JobExecutor._slide_deck({
        "url": "https://example.test/", "evidence_language": "observed",
        "executive_summary": LONG_SUMMARY, "critical_pain_points": findings,
        "elements_to_preserve": [{"title": "Clear value proposition", "description": LONG_SUMMARY}],
        "impact_analysis": {"personasTested": 3},
        "journey_outcome": {"tasks": [LONG_SUMMARY[:180], LONG_SUMMARY[:180]]},
        "synthetic_users": [{"id": "friedrich_wolf"}]})


def test_the_short_viewport_rules_come_last_in_the_stylesheet():
    """They override single-class rules like `.shot img`, so an equally specific
    rule appearing after them wins and the whole block does nothing -- which is
    what happened when they sat at the top: the measured overflow did not move by
    a pixel."""
    deck = _stress_deck()
    styles = deck[deck.index("<style"):deck.index("</style>")]
    assert "@media (max-height: 620px)" in styles
    # Against the *base* rule, not the last occurrence -- the override inside the
    # media block is itself a ".shot img{", so rindex finds that one and the
    # comparison passes no matter where the block sits.
    base = styles.index(".shot img{width:100%")
    assert styles.index("@media (max-height: 620px)") > base
    assert styles.index("@media (max-height: 720px)") > base


def test_the_deck_keeps_its_designed_size_on_a_normal_laptop():
    """Shrinking type everywhere to fit the worst case would make every deck
    worse to read. The breakpoints only bite on a short viewport."""
    styles = _stress_deck()
    assert "font:20px/1.55" in styles
    assert "max-height:42vh" in styles, "the full-size image cap is still the default"


@pytest.mark.skipif(not shutil.which(CHROMIUM) and not __import__("pathlib").Path(CHROMIUM).exists(),
                    reason="no Chromium to measure with")
def test_no_slide_is_cut_off_at_any_size_people_present_at(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")

    deck = tmp_path / "deck.html"
    deck.write_text(_stress_deck(), encoding="utf-8")

    clipped = []
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM, args=["--no-sandbox"])
        for width, height in SIZES:
            page = browser.new_page(viewport={"width": width, "height": height})
            page.goto(deck.as_uri(), wait_until="load", timeout=30000)
            # Every slide is display:none until selected, so each is shown in turn
            # and measured: scrollHeight past clientHeight is content nobody
            # presenting this deck will ever see.
            overflow = page.evaluate("""() => {
              const out = [];
              for (const [index, slide] of [...document.querySelectorAll('.slide')].entries()) {
                const was = slide.style.display;
                slide.style.display = 'flex';
                const over = slide.scrollHeight - slide.clientHeight;
                if (over > 2) out.push({ index: index + 1, over });
                slide.style.display = was;
              }
              return out;
            }""")
            for item in overflow:
                clipped.append(f"{width}x{height} slide {item['index']} cut off by {item['over']}px")
            page.close()
        browser.close()

    assert not clipped, "content past the fold is absent when presenting:\n" + "\n".join(clipped)
