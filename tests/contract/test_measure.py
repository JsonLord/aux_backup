"""RUN-1 (docs/parallel-development-spec.md §6 L0): pins scripts/cycle/measure.py's
output against the real snapshot in last_runs/, so a later change to the scorer
that silently breaks a metric is caught here rather than in a live cycle.

Every expected number below was independently verified against
last_runs/artifacts/*.json before being written into this test -- see the git
history of docs/parallel-development-spec.md for the reasoning behind each one
(the executed-below-threshold and video-timestamp corrections in particular:
the scorer's stricter, pointer-confirmed and diagnostic-excluding numbers
replaced two hand-counted figures that turned out to be off by one each).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.cycle import measure

LAST_RUNS = Path(__file__).resolve().parents[2] / "last_runs"


@pytest.fixture(scope="module")
def metrics():
    if not (LAST_RUNS / "artifacts").exists():
        pytest.skip("last_runs/artifacts is not present in this checkout")
    return measure.compute_metrics([LAST_RUNS])


def test_journey_group_matches_the_snapshot(metrics):
    j = metrics["journey"]
    assert j["verdicts"] == {"passed": 0, "failed": 0, "inconclusive": 1}
    assert j["budget_hit"] == [1, 1]
    assert j["stuck_high_frustration"] == [1, 1]
    assert j["loops"] == 1
    # Pointer-confirmed only: two of the three sub-threshold adherence events
    # have a matching persona.pointer event within 5s; the third (the second
    # "Pricing" rejection at 196575ms) has none either way, so it is not
    # claimed as confirmed-executed. See docs/parallel-development-spec.md's
    # JRN-3 row for the full trace.
    assert j["executed_actions_below_threshold"] == 2
    assert j["expectations_met_rate"] == [0, 6]
    assert j["runs_total"] == 1


def test_perception_group_matches_the_snapshot(metrics):
    p = metrics["perception"]
    assert p["captures"] == 12
    assert p["refused"] == 0
    assert p["legible_share"] == pytest.approx(0.8403547671840355)
    assert p["not_looked_at_slope"] == "falls"
    assert p["pointer"] == {"total": 10, "measured": 10, "missed": 0}


def test_findings_group_matches_the_snapshot(metrics):
    f = metrics["findings"]
    assert f["findings_about_site"] == 13
    assert f["positives"] == 1
    # The "Users could not finish the tasks they came to do" finding: sourced
    # from JourneyTest's own tasks-completed criterion, on a run that hit its
    # step budget (SEC-1's target).
    assert f["run_diagnostics_among_findings"] == 1
    assert f["false_contrast_low_ratio"] == 4
    assert set(f["false_contrast_titles"]) == {
        'Fails WCAG AA contrast: "Video"',
        'Fails WCAG AA contrast: "Italiano"',
        'Fails WCAG AA contrast: "RUРусский"',
        'Fails WCAG AA contrast: "ESEspañol"',
    }
    assert f["preserved_and_faulted_overlap"] == 1
    assert f["contentless_quotes"] == 2


def test_fill_rates_match_the_snapshot(metrics):
    fr = metrics["fill_rates"]
    assert fr["alternatives_with_effort"] == [1, 13]
    assert fr["confidence"] == [0, 13]
    # Denominator is findings *about the site* with a screenshot (8), not
    # every finding with a screenshot (9) -- one of those 9 is the misfiled
    # diagnostic this same run's findings_group excludes from site_findings.
    assert fr["video_timestamp"] == [0, 8]
    assert fr["root_cause"] == [4, 13]
    assert fr["grounding"] == [1, 13]


def test_report_contract_is_computed_not_hand_rated(metrics):
    """Deliberately does not reproduce last_runs/REPORT_CRITERIA.md's 6/2/1
    hand rating -- that rating is named as overstated (section 9) in
    docs/parallel-development-spec.md §2h, and reproducing a known-wrong
    number here would defeat RUN-1's own purpose."""
    contract = metrics["contract"]["per_report"][0]
    assert contract["sections"] == {
        "1_executive_summary": "met",
        "2_synthetic_user": "met",
        "3_journey_outcome": "met",
        "4_experience_trajectory": "missing",
        "5_critical_pain_points": "partial",
        "6_eyeson_ux_review": "met",
        "7_alternative_solutions": "partial",
        "8_ux_knowledge_basis": "partial",
        "9_full_evidence": "partial",
    }
    assert (contract["met"], contract["partial"], contract["missing"]) == (4, 4, 1)
    assert metrics["contract"]["evidence_language_tags"] == [0, 14]


def test_cost_group_matches_the_snapshot(metrics):
    c = metrics["cost"]
    assert c["run_wall_s"] == pytest.approx(243.1)
    assert c["model_calls"] == 55
    assert c["prompt_tokens"] == 37633
    assert c["completion_tokens"] == 15645
    assert c["adherence_share_of_model_wall"] == pytest.approx(0.4722781886184214)


def test_missing_run_dir_reports_which_file_and_pattern(tmp_path):
    empty = tmp_path / "empty-run"
    (empty / "artifacts").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="ux_report__"):
        measure.compute_metrics([empty])


def test_a_second_artifacts_file_refuses_rather_than_guessing(tmp_path):
    """last_runs/AGENTS.md's own rule: a single-snapshot folder, not an
    accumulating archive. Two matching files means that rule was broken, and
    measuring one of them silently would measure the wrong run."""
    run_dir = tmp_path / "run"
    artifacts = run_dir / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "ux_report__a.json").write_text("{}")
    (artifacts / "ux_report__b.json").write_text("{}")
    (artifacts / "journey_log__a.json").write_text('{"runs": []}')
    with pytest.raises(FileNotFoundError, match="expected exactly one"):
        measure.compute_metrics([run_dir])


def test_step_budget_matches_journeytest_js():
    # services/journey-worker/node/src/journeytest.js: stepBudget() ==
    # min(40, max(12, tasks.length * 8)).
    assert measure.step_budget(1) == 12
    assert measure.step_budget(2) == 16
    assert measure.step_budget(5) == 40  # capped at 40, not 40 exactly by luck
    assert measure.step_budget(6) == 40


def test_loop_detects_a_label_clicked_three_times():
    run = {
        "timeline": [
            {
                "type": "persona.expectation",
                "data": {"action": {"type": "CLICK", "target": f"e{i}"}, "targetName": "Pricing"},
            }
            for i in range(3)
        ]
    }
    assert measure.has_loop(run) is True


def test_loop_detects_alternation_between_two_labels():
    def click(label, ref):
        return {"type": "persona.expectation",
                "data": {"action": {"type": "CLICK", "target": ref}, "targetName": label}}

    run = {"timeline": [click("A", "e1"), click("B", "e2"), click("A", "e3")]}
    assert measure.has_loop(run) is True


def test_loop_is_false_for_a_clean_run():
    def click(label, ref):
        return {"type": "persona.expectation",
                "data": {"action": {"type": "CLICK", "target": ref}, "targetName": label}}

    run = {"timeline": [click("Pricing", "e1"), click("Sign up", "e2"), click("Confirm", "e3")]}
    assert measure.has_loop(run) is False


def test_not_looked_at_slope_reads_a_genuine_rise_as_a_navigation():
    run = {
        "timeline": [
            {"type": "persona.perception", "data": {"counts": {"notLookedAt": 10}}},
            {"type": "persona.perception", "data": {"counts": {"notLookedAt": 5}}},
            {"type": "persona.perception", "data": {"counts": {"notLookedAt": 30}}},  # navigation
            {"type": "persona.perception", "data": {"counts": {"notLookedAt": 12}}},
        ]
    }
    assert measure.not_looked_at_slope([run]) == "falls"
