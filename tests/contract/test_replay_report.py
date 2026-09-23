"""RUN-3 (docs/parallel-development-spec.md §6 L0): scripts/cycle/replay_report.py
rebuilds a ux.report from last_runs/ with no live worker and no model call.
Verified here against the real snapshot, and against synthetic fixtures for
the parts a single real run cannot exercise on its own (a screenshot that
cannot be remapped, a count mismatch that must not be guessed at).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from scripts.cycle import replay_report as rr

LAST_RUNS = Path(__file__).resolve().parents[2] / "last_runs"


@pytest.fixture(scope="module")
def replayed():
    if not (LAST_RUNS / "artifacts").exists():
        pytest.skip("last_runs/artifacts is not present in this checkout")
    return rr.replay(LAST_RUNS)


@pytest.fixture(scope="module")
def live_report():
    matches = sorted((LAST_RUNS / "artifacts").glob("ux_report__*.json"))
    return json.loads(matches[0].read_text())


def test_replay_makes_no_model_call_and_is_fast(monkeypatch):
    """The whole point: vision=[] and redesign=[] make _collect_vision_pain_points
    and _generate_redesign_fragment true no-ops (see assembler.py's own early
    returns). Prove it by refusing any outbound network attempt during replay,
    not only by timing it."""
    if not (LAST_RUNS / "artifacts").exists():
        pytest.skip("last_runs/artifacts is not present in this checkout")

    def _forbidden(*args, **kwargs):
        raise AssertionError("replay must never open a network connection")

    monkeypatch.setattr("urllib.request.urlopen", _forbidden)
    started = time.monotonic()
    report = rr.replay(LAST_RUNS)
    elapsed = time.monotonic() - started
    assert report["url"] == "https://open-design.ai/"
    assert elapsed < 10, f"replay took {elapsed:.2f}s, expected well under RUN-3's 30s bound"


def test_replay_reproduces_journey_level_fields(replayed, live_report):
    assert replayed["journey_outcome"]["status"] == live_report["journey_outcome"]["status"]
    assert replayed["evidence_language"] == live_report["evidence_language"]
    assert replayed["scorecard"] == live_report["scorecard"]
    assert len(replayed["journey_outcome"]["runs"]) == len(live_report["journey_outcome"]["runs"])


def test_replay_fills_video_timestamps_the_live_snapshot_predates(replayed):
    """SEC-5 postdates last_runs/'s own live snapshot -- assemble_report is
    shared code, so replay picks it up (category not in diff_reports'
    original five, both now real): every finding with a screenshot gets a
    videoTimestampMs. `step` is the one field replay cannot recover -- see
    replay_report.py's module docstring, category 6."""
    with_screenshot = [
        f for f in replayed["critical_pain_points"]
        if f.get("evidenceScreenshot") or f.get("screenshotRef")
    ]
    assert with_screenshot  # the snapshot has findings with a screenshot
    assert all(f.get("videoTimestampMs") is not None for f in with_screenshot)
    assert all(f.get("step") is None for f in replayed["critical_pain_points"])


def test_replay_carries_perception_and_expectation_findings(replayed, live_report):
    """Everything _pain_points_from_perception/_pain_points_from_expectations
    produce is journey-only, so it must survive replay -- the broken-promise
    findings, byte for byte. Two title families do *not* survive unchanged,
    and that is two report-side fixes working as intended, not a replay
    gap: assemble_report is shared, live code, so replaying an old run
    through today's tree applies every fix made since it shipped (FND-1's
    four "Fails WCAG AA contrast" titles; SEC-1's "Users could not finish
    the tasks they came to do" and "The visitor did not get there", both
    now correctly in run_diagnostics, not critical_pain_points) -- see
    docs/parallel-development-spec.md's FND-1 and SEC-1 rows."""
    replayed_titles = {f["title"] for f in replayed["critical_pain_points"]}
    live_titles = {f["title"] for f in live_report["critical_pain_points"]}
    unaffected_by_any_report_fix = {
        title for title in live_titles
        if not title.startswith("Download link")  # the one eyeson-vision-synthesis finding
        and not title.startswith("Fails WCAG AA contrast")  # FND-1 reclassifies these
        and title not in {  # SEC-1 relocates these to run_diagnostics
            "Users could not finish the tasks they came to do",
            "The visitor did not get there",
        }
    }
    assert unaffected_by_any_report_fix <= replayed_titles
    # FND-1's own replacement: the four false contrast findings grouped into
    # one honest, info-severity finding with instances[].
    grouped = next(
        f for f in replayed["critical_pain_points"]
        if f["source"] == "perception.unverifiedContrast"
    )
    assert grouped["severity"] == "info"
    assert len(grouped["instances"]) == 4
    assert not any(key.startswith("_") for key in grouped)  # no leaked temp fields
    assert not any(title.startswith("Fails WCAG AA contrast") for title in replayed_titles)
    # SEC-1: both budget-limited shapes land in run_diagnostics, not here.
    assert "Users could not finish the tasks they came to do" not in replayed_titles
    assert "The visitor did not get there" not in replayed_titles
    replayed_diagnostic_titles = {f["title"] for f in replayed["run_diagnostics"]}
    assert {"Users could not finish the tasks they came to do", "The visitor did not get there"} <= replayed_diagnostic_titles


def test_replay_is_missing_exactly_the_documented_vision_sourced_content(replayed, live_report):
    diff = rr.diff_reports(replayed, live_report)
    # findings_missing_from_replay mixes the one genuine vision gap with the
    # four "Fails WCAG AA contrast" titles FND-1 retires and the one
    # SEC-1 retires -- see diff_reports' own docstring on telling the
    # kinds apart. "The visitor did not get there" does not appear here:
    # the live report already merged it into "Users could not finish..."
    # (mergedFrom) before SEC-1 existed to keep them apart, so it was
    # never its own top-level title in live_report to begin with.
    assert set(diff["findings_missing_from_replay"]) == {
        "Download link does not initiate download or navigate to a new page.",
        'Fails WCAG AA contrast: "Video"',
        'Fails WCAG AA contrast: "Italiano"',
        'Fails WCAG AA contrast: "RUРусский"',
        'Fails WCAG AA contrast: "ESEspañol"',
        "Users could not finish the tasks they came to do",
    }
    assert diff["findings_only_in_replay"] == [
        "4 regions measured a low contrast ratio with unconfirmed ink"
    ]
    # All 6 kept screenshots remap cleanly on this snapshot -- see
    # replay_report.py's module docstring, category 4.
    assert diff["matched_findings_missing_screenshot_crop"] == []
    # Empty, not the pre-SEC-1 {"Users could not finish..."}: that title is
    # no longer a *matched* finding at all now -- it does not appear in
    # replay's critical_pain_points to compare redesignHtml against.
    assert diff["matched_findings_missing_redesign_html"] == []
    # Category 2: this run's elements_to_preserve is entirely vision-sourced
    # (confirmed directly: _praise_from_verdicts/_preserved_from_verdicts/
    # _preserved_from_met_expectations all return [] for this journey).
    assert diff["preserve_count"] == [0, 1]
    assert "report.redesign" in diff["model_usage_roles"]["live"]
    assert "report.redesign" not in diff["model_usage_roles"]["replayed"]


def test_screenshot_remap_maps_every_kept_screenshot(replayed):
    journey_log = json.loads(
        sorted((LAST_RUNS / "artifacts").glob("journey_log__*.json"))[0].read_text()
    )
    journeys = journey_log["runs"]
    remap = rr.build_screenshot_remap(LAST_RUNS, journeys)
    originals = journeys[0]["artifacts"]["screenshots"] + [journeys[0]["artifacts"]["video"]]
    assert set(remap) == set(originals)
    for original, local in remap.items():
        assert Path(local).is_file()
        # The whole point of the magic-byte cross-check: an original named
        # .png must map to a real PNG, .jpg to a real JPEG.
        assert rr._magic_matches(Path(local), original)


def test_magic_mismatch_is_not_trusted(tmp_path):
    fake_jpeg_named_png = tmp_path / "x.dat"
    fake_jpeg_named_png.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 20)  # real JPEG bytes
    assert rr._magic_matches(fake_jpeg_named_png, "shot.png") is False
    assert rr._magic_matches(fake_jpeg_named_png, "shot.jpg") is True


def test_remap_count_mismatch_is_left_unmapped(tmp_path):
    """A run whose screenshot count does not match output_artifacts' screenshot
    ids is not guessed at -- see build_screenshot_remap's own docstring."""
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "logs").mkdir(parents=True)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    (run_dir / "artifacts" / "browser_screenshot__art_aaaa.png").write_bytes(png_bytes)
    (run_dir / "logs" / "job_final.json").write_text(json.dumps({
        "job_id": "job_x",
        "output_artifacts": ["art_aaaa"],
        "metadata": {"url": "https://example.com", "tasks": ["do a thing"]},
    }))
    journeys = [{"artifacts": {"screenshots": ["/orig/001.png", "/orig/002.png"]}}]  # 2 originals, 1 local
    remap = rr.build_screenshot_remap(run_dir, journeys)
    assert remap == {}


def test_remap_is_applied_throughout_the_json_tree():
    remap = {"/orig/a.png": "/local/a.png"}
    value = {
        "artifacts": {"screenshots": ["/orig/a.png"]},
        "timeline": [{"type": "persona.perception", "data": {"seenImage": "/orig/a.png"}}],
        "unrelated": "/orig/a.png but longer, not an exact match",
    }
    remapped = rr._remap_paths(value, remap)
    assert remapped["artifacts"]["screenshots"] == ["/local/a.png"]
    assert remapped["timeline"][0]["data"]["seenImage"] == "/local/a.png"
    # Only an exact string match is rewritten -- a longer string that merely
    # contains the original path is left alone.
    assert remapped["unrelated"] == "/orig/a.png but longer, not an exact match"


def test_replay_refuses_a_run_dir_with_no_persona_profile(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "journey_log__art_x.json").write_text(json.dumps({
        "runs": [{"runId": "r1", "artifacts": {}}]
    }))
    (run_dir / "logs").mkdir(parents=True)
    (run_dir / "logs" / "job_final.json").write_text(json.dumps({
        "job_id": "job_x", "output_artifacts": [],
        "metadata": {"url": "https://example.com", "tasks": ["t"]},
    }))
    with pytest.raises(ValueError, match="persona_profile"):
        rr.replay(run_dir)


def test_replay_refuses_a_run_dir_with_no_job_metadata(tmp_path):
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "journey_log__art_x.json").write_text(json.dumps({
        "runs": [{"runId": "r1", "artifacts": {}}]
    }))
    (run_dir / "artifacts" / "persona_profile__art_y.json").write_text(json.dumps({
        "id": "p1", "persona": {}, "behavior": {}, "abilities": {}, "generation": {},
    }))
    with pytest.raises(ValueError, match="job_final"):
        rr.replay(run_dir)
