"""RUN-5 (docs/parallel-development-spec.md §6 L0): golden invariants over
the offline replay of `last_runs/`.

These are not unit tests of one function; they are report-level properties
that must hold of the *assembled* report, run on every PR so a regression in
any lane's own work is caught here rather than on the next live cycle.

Each invariant is proven both ways in this file, not asserted on faith:

- against `last_runs/artifacts/ux_report__*.json` -- the real, live
  snapshot, generated before FND-1/SEC-1/SEC-2/SEC-5 landed -- to show the
  invariant actually would have failed on the code this session started
  from (no code revert needed: that file is the "before" state, unmodified
  on disk);
- against `replay_report.replay(last_runs)` -- today's code, run through
  the offline replay RUN-3 built -- to show it holds now.

A golden test pins a *specific, current* number (`ASSERTED_CONTRACT`
below), not an aspirational one: the §30 contract is not fully met yet
(vision is absent under replay by design, and several lanes -- FND-4, SEC-3,
SEC-4, EVD-2 -- have not landed). Update `ASSERTED_CONTRACT` in the same PR
that closes one of those gaps, with a comment saying which item did it;
letting this test silently start failing (or silently stop meaning
anything, by loosening the assertion) is the failure mode a golden test
exists to prevent.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.cycle.measure import (
    budget_hit_run_ids,
    false_contrast_findings,
    misfiled_diagnostics,
    report_contract_sections,
)
from scripts.cycle.replay_report import replay

LAST_RUNS = Path(__file__).resolve().parents[2] / "last_runs"

# Pinned to today's tree. See the module docstring: update this, with a
# reason, in the PR that closes one of the two remaining "missing" sections.
ASSERTED_CONTRACT = {"met": 5, "partial": 2, "missing": 2}


def _require_snapshot():
    if not (LAST_RUNS / "artifacts").exists():
        pytest.skip("last_runs/artifacts is not present in this checkout")


@pytest.fixture(scope="module")
def live_report():
    _require_snapshot()
    path = next((LAST_RUNS / "artifacts").glob("ux_report__*.json"))
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def replayed_report():
    _require_snapshot()
    return replay(LAST_RUNS)


def _budget_hits(report: dict) -> set[str]:
    outcome = report.get("journey_outcome") or {}
    return budget_hit_run_ids(outcome.get("runs") or [], len(outcome.get("tasks") or []))


# ---------------------------------------------------------------------------
# Proof that the invariants are real: the live snapshot violates every one.
# ---------------------------------------------------------------------------


def test_the_live_snapshot_violates_the_invariants_this_file_guards(live_report):
    """The "before" side of the proof. If any of these assertions ever
    fails, it means last_runs/ was refreshed (last_runs/AGENTS.md's own
    refresh procedure) against a tree where the defect is already fixed --
    check whether this whole file is now testing a defect that no longer
    exists anywhere, and simplify it rather than leaving a proof of a bug
    nobody can reproduce."""
    # spec.md §55.3 rules 2 & 4: "no ink is not low contrast", "1.00:1 is
    # not a measurement" -- the live report has all four.
    assert len(false_contrast_findings(live_report)) == 4

    # SEC-1: a harness limit reported as a usability finding.
    hits = _budget_hits(live_report)
    assert len(misfiled_diagnostics(live_report, hits)) == 1

    # SEC-2: the experience trajectory did not exist yet.
    assert not live_report.get("experience_trajectory")


# ---------------------------------------------------------------------------
# The invariants themselves, proven true on today's replay.
# ---------------------------------------------------------------------------


def test_no_finding_claims_fails_wcag_contrast_without_verified_ink(replayed_report):
    """spec.md §55.3 rules 2 & 4, FND-1's own target."""
    assert false_contrast_findings(replayed_report) == []


def test_no_run_diagnostic_is_filed_among_the_findings(replayed_report):
    """SEC-1's own target: a run that hit its step budget is a diagnostic,
    not a usability claim about the product."""
    hits = _budget_hits(replayed_report)
    assert misfiled_diagnostics(replayed_report, hits) == []
    # The other direction of the same claim: whatever IS in run_diagnostics
    # never leaks back into critical_pain_points under a shared title.
    diagnostic_titles = {f.get("title") for f in replayed_report.get("run_diagnostics") or []}
    finding_titles = {f.get("title") for f in replayed_report.get("critical_pain_points") or []}
    assert not (diagnostic_titles & finding_titles)


def test_the_report_contract_matches_the_pinned_state(replayed_report):
    """See the module docstring: this number moves forward as lanes land,
    never backward without a regression to explain it."""
    contract = report_contract_sections(replayed_report)
    assert (contract["met"], contract["partial"], contract["missing"]) == (
        ASSERTED_CONTRACT["met"], ASSERTED_CONTRACT["partial"], ASSERTED_CONTRACT["missing"]
    )
    # SEC-2 specifically: never missing again once it has landed once.
    assert contract["sections"]["4_experience_trajectory"] == "met"


def test_every_evidence_screenshot_reference_resolves_on_disk(replayed_report):
    """spec.md §53.2 #2: a report that cites a capture the reader cannot
    open is worse than one that cites nothing -- it reads as corroborated.
    Every reference a replayed finding carries must point at a real file,
    since RUN-3's remap either resolves a path or leaves the field unset
    (never a half-resolved dangling reference)."""
    checked = 0
    for finding in replayed_report.get("critical_pain_points") or []:
        for key in ("evidenceScreenshot", "screenshotRef"):
            ref = finding.get(key)
            if ref:
                checked += 1
                assert Path(ref).is_file(), f"{key}={ref!r} on {finding.get('title')!r} does not resolve"
    assert checked > 0  # the snapshot has findings with a screenshot to check


def test_no_finding_carries_a_leaked_internal_temp_field(replayed_report):
    """FND-1's `_unverifiedRatio`/`_unverifiedInk` are popped by
    `_fold_unverified_contrast` either way (folded or not); this is the
    general-purpose guard so any future leading-underscore working field
    added to any finding builder is caught the same way, not just this
    one class's own two names."""
    for finding in replayed_report.get("critical_pain_points") or []:
        leaked = [key for key in finding if key.startswith("_")]
        assert not leaked, f"{finding.get('title')!r} leaks {leaked}"
