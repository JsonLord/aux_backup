#!/usr/bin/env python3
"""The one scorer (RUN-1, docs/parallel-development-spec.md).

Computes every row of the spec's §5 scoreboard from a run directory's own
JSON artifacts -- `ux_report__*.json` and `journey_log__*.json` -- and
nothing else. Per spec.md §55.6h, it never greps raw JSON text and never
counts a persona's own sentences (a quote, an expectation, a reflection):
every check below reads a named, typed field, the same discipline that
section's own two false metrics ("a grep for £", "a pattern for 'does not
state a price'") were built to stop repeating.

Two files per run-dir, deliberately not one: `journey_log__*.json` is read as
the raw ground truth for journey-level metrics (verdicts, loops, perception,
pointer) -- the same file RUN-3's offline replay is built from, so a report
rebuilt from it should score the same as the one that shipped it.
`ux_report__*.json` is read for report-assembly metrics (findings, fill
rates, the report contract, cost) -- things only the assembled report states.

Usage:
    measure.py <run-dir> [<run-dir> ...] [--json-out FILE] [--md-out FILE]

Each <run-dir> holds an `artifacts/` folder with exactly one
`ux_report__*.json` and one `journey_log__*.json`, the shape `last_runs/`
already uses (see `last_runs/AGENTS.md`). Metrics pool across every run-dir
given, and across every persona run inside each report, so a single
multi-persona cohort and several separate run directories are measured the
same way.

As a library: `compute_metrics(run_dirs: list[Path]) -> dict`.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

# Shared with the actual fix (SEC-1), not reimplemented: the scorer and
# services.report_service.assembler.assemble_report must always agree on
# when a run hit its step budget, or measure.py could report a defect the
# report itself no longer has (or the reverse). See helpers.py's own
# docstrings for step_budget/_budget_hit_run_ids/_is_budget_limited_finding.
import sys as _sys

_sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.report_service.helpers import (  # noqa: E402
    _is_budget_limited_finding,
    step_budget,
)
from services.report_service.helpers import _actions_taken as _actions_taken  # noqa: E402,F401
from services.report_service.helpers import _budget_hit_run_ids as budget_hit_run_ids  # noqa: E402

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _find_one(run_dir: Path, pattern: str) -> Path:
    matches = sorted((run_dir / "artifacts").glob(pattern))
    if not matches:
        raise FileNotFoundError(f"{run_dir}/artifacts has no file matching {pattern!r}")
    if len(matches) > 1:
        # last_runs/AGENTS.md's own rule: one run's worth of evidence at a
        # time. More than one match means the snapshot policy was not
        # followed (an old run's files were not deleted before the new one's
        # were added), and silently picking one would measure the wrong run.
        raise FileNotFoundError(
            f"{run_dir}/artifacts has {len(matches)} files matching {pattern!r}, expected "
            f"exactly one -- last_runs/ is a single-snapshot folder (see last_runs/AGENTS.md): "
            f"{[str(m) for m in matches]}")
    return matches[0]


def load_run(run_dir: Path) -> dict[str, Any]:
    """One run-dir's report and journey log, paired."""
    report = json.loads(_find_one(run_dir, "ux_report__*.json").read_text())
    journey_log = json.loads(_find_one(run_dir, "journey_log__*.json").read_text())
    return {"run_dir": str(run_dir), "report": report, "journey_log": journey_log}


# ---------------------------------------------------------------------------
# Journey group -- read from journey_log's raw runs
# ---------------------------------------------------------------------------


def verdict_counts(runs: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "inconclusive": 0}
    for run in runs:
        status = ((run.get("verdict") or {}).get("status") or "").lower()
        if status in counts:
            counts[status] += 1
    return counts


def stuck_high_frustration(runs: list[dict[str, Any]], threshold: float = 0.9) -> tuple[int, int]:
    """A run whose last recorded affect state is at or above `threshold`
    frustration and did not abandon -- the persona who could not leave
    (JRN-1's evidence: frustration reaches 1.00, p(abandon) peaks at 0.033,
    the run ends only when its step budget runs out)."""
    count = 0
    for run in runs:
        affect = [e for e in (run.get("timeline") or []) if e.get("type") == "persona.affect"]
        if not affect:
            continue
        state = (affect[-1].get("data") or {}).get("state") or {}
        frustration = state.get("frustration")
        if frustration is not None and frustration >= threshold and not state.get("abandoned"):
            count += 1
    return count, len(runs)


_LOOP_LABEL_MIN = 3


def _click_label_sequence(run: dict[str, Any]) -> list[str]:
    """The sequence of control labels a run clicked, in order. Read from
    `persona.expectation`'s own `targetName` (what the walk read off the
    control), falling back to the raw ref only when no label was recorded --
    the same fallback JRN-2/JRN-3 exist to remove (the adherence judge
    currently sees only the ref)."""
    labels = []
    for e in (run.get("timeline") or []):
        if e.get("type") != "persona.expectation":
            continue
        data = e.get("data") or {}
        action = data.get("action") or {}
        if action.get("type") != "CLICK":
            continue
        label = (data.get("targetName") or action.get("target") or "").strip()
        if label:
            labels.append(label)
    return labels


def has_loop(run: dict[str, Any]) -> bool:
    """The same control clicked 3 or more times, or two controls clicked
    back and forth (a directed transition A->B and at least one B->A) --
    the worksheet's billing-toggle oscillation and this snapshot's
    Pricing/"Start free" alternation, both real live traces."""
    labels = _click_label_sequence(run)
    if not labels:
        return False
    if any(n >= _LOOP_LABEL_MIN for n in Counter(labels).values()):
        return True
    transitions = Counter(zip(labels, labels[1:]))
    checked: set[frozenset[str]] = set()
    for (a, b) in transitions:
        pair = frozenset((a, b))
        if a == b or pair in checked:
            continue
        checked.add(pair)
        if transitions.get((a, b), 0) >= 1 and transitions.get((b, a), 0) >= 1:
            return True
    return False


_ADHERENCE_MATCH_WINDOW_MS = 5000


def executed_below_threshold(run: dict[str, Any]) -> int:
    """`persona.adherence` events the run's own gate marked `passed: false`,
    where the action ran anyway -- confirmed by a `persona.pointer` event on
    the same target, close in time (JRN-3's evidence: 3 actions scored 3, 4
    and 0 against a threshold of 7, and two of the three have a matching
    pointer event on the page)."""
    events = run.get("timeline") or []
    adherence = [e for e in events if e.get("type") == "persona.adherence"]
    pointers = [e for e in events if e.get("type") == "persona.pointer"]
    count = 0
    for e in adherence:
        data = e.get("data") or {}
        if data.get("passed") is not False:
            continue
        history = data.get("history") or []
        target = (history[-1].get("action") or {}).get("target") if history else None
        elapsed = e.get("elapsedMs")
        if target is None or elapsed is None:
            continue
        for p in pointers:
            pdata = p.get("data") or {}
            if pdata.get("target") == target and abs((p.get("elapsedMs") or 0) - elapsed) <= _ADHERENCE_MATCH_WINDOW_MS:
                count += 1
                break
    return count


# ---------------------------------------------------------------------------
# Perception group -- read from journey_log's raw runs
# ---------------------------------------------------------------------------


def perception_captures(runs: list[dict[str, Any]]) -> tuple[int, int]:
    total = refused = 0
    for run in runs:
        for e in (run.get("timeline") or []):
            if e.get("type") != "persona.perception":
                continue
            total += 1
            capture = (e.get("data") or {}).get("capture") or {}
            if capture.get("trustworthy") is False:
                refused += 1
    return total, refused


def legible_share(runs: list[dict[str, Any]]) -> float | None:
    """Pooled across every capture: total legible elements over total
    elements, not the mean of per-capture ratios -- a capture with more
    elements on screen should not count the same as one with few."""
    elements = legible = 0
    for run in runs:
        for e in (run.get("timeline") or []):
            if e.get("type") != "persona.perception":
                continue
            counts = (e.get("data") or {}).get("counts") or {}
            elements += counts.get("elements") or 0
            legible += counts.get("legible") or 0
    return (legible / elements) if elements else None


def not_looked_at_slope(runs: list[dict[str, Any]]) -> str:
    """'falls', 'rises', 'mixed' or 'flat' -- whether `notLookedAt` trends
    down within one page. A value that *rises* from the previous capture is
    read as a navigation (new elements the scan has never had a chance to
    see), which starts a new segment; a segment of length 1 says nothing
    about a slope and is dropped."""
    segments: list[list[int]] = []
    for run in runs:
        values = [
            ((e.get("data") or {}).get("counts") or {}).get("notLookedAt")
            for e in (run.get("timeline") or [])
            if e.get("type") == "persona.perception"
        ]
        values = [v for v in values if v is not None]
        current: list[int] = []
        for v in values:
            if current and v > current[-1]:
                if len(current) > 1:
                    segments.append(current)
                current = [v]
            else:
                current.append(v)
        if len(current) > 1:
            segments.append(current)
    if not segments:
        return "unmeasured"
    falling = sum(1 for seg in segments if seg[-1] < seg[0])
    rising = sum(1 for seg in segments if seg[-1] > seg[0])
    if falling and rising:
        return "mixed"
    if falling:
        return "falls"
    if rising:
        return "rises"
    return "flat"


def pointer_stats(runs: list[dict[str, Any]]) -> tuple[int, int, int]:
    total = measured = missed = 0
    for run in runs:
        for e in (run.get("timeline") or []):
            if e.get("type") != "persona.pointer":
                continue
            total += 1
            data = e.get("data") or {}
            if data.get("box"):
                measured += 1
            if data.get("missed"):
                missed += 1
    return total, measured, missed


# ---------------------------------------------------------------------------
# Findings group -- read from the assembled ux.report
# ---------------------------------------------------------------------------


def misfiled_diagnostics(report: dict[str, Any], budget_hits: set[str]) -> list[dict[str, Any]]:
    """A finding that is really a harness limit, not a usability defect.

    SEC-1's own check (`_is_budget_limited_finding`, imported above), not a
    second copy of it: on a report generated by fixed code these are
    already absent from `critical_pain_points` and this returns `[]`
    honestly. Run against a report from before the fix (such as
    `last_runs/`'s own live snapshot, generated before SEC-1 landed), this
    is what still finds them -- both known shapes, `tasks-completed`
    criterion and the `blockers` bucket's own `persona-stopped` id, each
    on a run that hit its own step budget."""
    return [
        f
        for f in (report.get("critical_pain_points") or [])
        if _is_budget_limited_finding(f, budget_hits)
    ]


def false_contrast_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    """A "Fails" title with a measured ratio under 1.2 -- spec.md §55.3's
    rules 2 and 4 ("no ink is not low contrast", "1.00:1 is not a
    measurement") failing again. This does not yet check for verified ink
    (EVD-1's job); once it does, a finding whose ink was genuinely confirmed
    present at a real low ratio should stop counting here, which is a
    change to make alongside EVD-1/FND-1, not to this metric's shape."""
    out = []
    for f in report.get("critical_pain_points") or []:
        title = f.get("title") or ""
        ratio = f.get("contrastRatio")
        if title.startswith("Fails") and ratio is not None and ratio < 1.2:
            out.append(f)
    return out


_LABELED_FINDING_TITLE = re.compile(r"^Promised more than it did:\s*(.+)$")


def preserved_and_faulted_overlap(report: dict[str, Any]) -> list[tuple[str, str]]:
    """A control named in a broken-promise finding's title (the exact control
    label, e.g. "Download OpenDesign free") that also appears, verbatim, in
    an `elements_to_preserve` item's own title or description.

    Scoped to the one finding class the codebase currently titles with an
    exact control label (`_broken_promise_finding`/`_promise_label`) rather
    than a generic word-overlap check: a looser check flags any page that
    praises and criticises different controls sharing ordinary words
    ("clear", "download"), which is not what this metric is asking."""
    preserve = report.get("elements_to_preserve") or []
    preserve_text = " | ".join(
        f"{p.get('title', '')} {p.get('description', '')}" for p in preserve
    ).lower()
    if not preserve_text.strip():
        return []
    overlaps = []
    for f in report.get("critical_pain_points") or []:
        match = _LABELED_FINDING_TITLE.match(f.get("title") or "")
        if not match:
            continue
        label = match.group(1).strip().lower()
        if label and label in preserve_text:
            overlaps.append((label, f.get("title")))
    return overlaps


_CONTENTLESS_QUOTE_MIN_CHARS = 20


def contentless_quotes(report: dict[str, Any]) -> list[str]:
    """A `personaEvidence` quote too short to carry the affect it is meant
    to evidence -- e.g. "You are calm." (13 characters), which is a
    template's default feeling-line, not a reaction to anything on this
    page."""
    out = []
    for f in report.get("critical_pain_points") or []:
        for q in f.get("personaEvidence") or []:
            text = (q.get("quote") or "").strip()
            if text and len(text) < _CONTENTLESS_QUOTE_MIN_CHARS:
                out.append(text)
    return out


def findings_group(report: dict[str, Any], budget_hits: set[str]) -> dict[str, Any]:
    all_findings = report.get("critical_pain_points") or []
    misfiled = misfiled_diagnostics(report, budget_hits)
    misfiled_ids = {id(f) for f in misfiled}
    site_findings = [f for f in all_findings if id(f) not in misfiled_ids]
    preserve = report.get("elements_to_preserve") or []
    false_contrast = false_contrast_findings(report)
    overlaps = preserved_and_faulted_overlap(report)
    contentless = contentless_quotes(report)

    with_screenshot = [f for f in site_findings if f.get("evidenceScreenshot")]
    alt_with_effort = sum(
        1
        for f in site_findings
        if any(a.get("effort") for a in (f.get("alternatives") or []))
    )
    with_confidence = sum(1 for f in site_findings if f.get("confidence") is not None)
    with_video_ts = sum(1 for f in with_screenshot if f.get("videoTimestampMs") is not None)
    with_root_cause = sum(1 for f in site_findings if f.get("rootCause"))
    with_grounding = sum(1 for f in site_findings if f.get("grounding"))

    return {
        "findings_about_site": len(site_findings),
        "positives": len(preserve),
        "run_diagnostics_among_findings": len(misfiled),
        "false_contrast_low_ratio": len(false_contrast),
        "false_contrast_titles": [f.get("title") for f in false_contrast],
        "preserved_and_faulted_overlap": len(overlaps),
        "preserved_and_faulted_pairs": overlaps,
        "contentless_quotes": len(contentless),
        "fill_rates": {
            "alternatives_with_effort": [alt_with_effort, len(site_findings)],
            "confidence": [with_confidence, len(site_findings)],
            "video_timestamp": [with_video_ts, len(with_screenshot)],
            "root_cause": [with_root_cause, len(site_findings)],
            "grounding": [with_grounding, len(site_findings)],
        },
    }


def expectations_met_rate(report: dict[str, Any]) -> tuple[int, int] | None:
    scorecard = report.get("scorecard") or {}
    met, missed = scorecard.get("expectationsMet"), scorecard.get("expectationsMissed")
    if met is None or missed is None:
        return None
    return met, met + missed


# ---------------------------------------------------------------------------
# Report contract (spec.md §30), computed rather than rated by hand
# ---------------------------------------------------------------------------


def _synthetic_user_complete(user: dict[str, Any]) -> bool:
    return all(user.get(k) for k in ("persona", "behavior", "abilities", "generation"))


def report_contract_sections(report: dict[str, Any]) -> dict[str, Any]:
    """spec.md §30's nine sections, each rated met/partial/missing from real
    fields. This deliberately does not always reproduce
    `last_runs/REPORT_CRITERIA.md`'s hand rating: section 9 (full evidence)
    is rated "partial" here rather than "met", because
    `snapshots`/`console`/`network`/`uiChanges` are empty on every run in the
    snapshot this was written against -- see
    docs/parallel-development-spec.md §2h, which names that hand rating as
    overstated. Reproducing a rating this project has already said is wrong
    would defeat RUN-1's whole purpose."""
    sections: dict[str, str] = {}

    summary = (report.get("executive_summary") or "").strip()
    if not summary:
        sections["1_executive_summary"] = "missing"
    else:
        # SEC-9: spec.md §30.1's five bullets, checked against the fixed
        # markers _executive_summary (assembler.py) itself uses for each --
        # legitimate here because this pipeline controls its own wording
        # (unlike a persona's or a vision model's free-form prose, which
        # this file never pattern-matches). "No usability issues were
        # identified" satisfies both the pain-point and recommendation
        # bullets vacuously: a clean run has nothing to name or recommend,
        # and that is not the same thing as a missing bullet.
        has_lead = "The one thing to change:" in summary or "No usability issues were identified" in summary
        bullets = {
            "task_outcome": " attempted " in summary,
            "experience_quality": "the experience left a persona" in summary,
            "strongest_pain_point": has_lead,
            "strongest_recommendation": "Recommended:" in summary or "No usability issues were identified" in summary,
            "completion_or_abandonment": "completed the task" in summary,
        }
        sections["1_executive_summary"] = "met" if all(bullets.values()) else "partial"

    users = report.get("synthetic_users") or []
    if users and all(_synthetic_user_complete(u) for u in users):
        sections["2_synthetic_user"] = "met"
    elif users:
        sections["2_synthetic_user"] = "partial"
    else:
        sections["2_synthetic_user"] = "missing"

    jruns = (report.get("journey_outcome") or {}).get("runs") or []
    complete = [r for r in jruns if r.get("durationMs") and r.get("timeline") and r.get("verdict")]
    if jruns and len(complete) == len(jruns):
        sections["3_journey_outcome"] = "met"
    elif complete:
        sections["3_journey_outcome"] = "partial"
    else:
        sections["3_journey_outcome"] = "missing"

    # SEC-2's field. Absent today by construction -- see docs/
    # parallel-development-spec.md §2h and §6 SEC-2.
    sections["4_experience_trajectory"] = "met" if report.get("experience_trajectory") else "missing"

    findings = report.get("critical_pain_points") or []

    def _core_ok(f: dict[str, Any]) -> bool:
        return bool(
            (f.get("evidenceScreenshot") or f.get("elementBox"))
            and f.get("evidence")
            and f.get("recommendation")
        )

    core_ok = [f for f in findings if _core_ok(f)]
    if findings and len(core_ok) == len(findings):
        sections["5_critical_pain_points"] = "met"
    elif core_ok:
        sections["5_critical_pain_points"] = "partial"
    else:
        sections["5_critical_pain_points"] = "missing"

    eyeson = [f for f in findings if f.get("source") == "eyeson-vision-synthesis"]
    sections["6_eyeson_ux_review"] = "met" if eyeson else "missing"

    # A *ranked* list (spec.md's own wording) is a standalone field (SEC-3);
    # per-finding alternatives existing is a different, narrower claim.
    ranked = report.get("ranked_alternatives")
    any_alts = any(f.get("alternatives") for f in findings)
    if ranked:
        sections["7_alternative_solutions"] = "met"
    elif any_alts:
        sections["7_alternative_solutions"] = "partial"
    else:
        sections["7_alternative_solutions"] = "missing"

    # A standalone provider-status block (SEC-4) vs per-finding grounding.
    basis = report.get("knowledge_basis")
    any_grounding = any(f.get("grounding") for f in findings)
    if basis:
        sections["8_ux_knowledge_basis"] = "met"
    elif any_grounding:
        sections["8_ux_knowledge_basis"] = "partial"
    else:
        sections["8_ux_knowledge_basis"] = "missing"

    channels = ["screenshots", "snapshots", "uiChanges", "video"]
    channel_present = []
    for channel in channels:
        present = False
        for run in jruns:
            value = (run.get("artifacts") or {}).get(channel)
            if isinstance(value, list) and value:
                present = True
            elif isinstance(value, str) and value:
                present = True
        channel_present.append(present)
    if all(channel_present):
        sections["9_full_evidence"] = "met"
    elif any(channel_present):
        sections["9_full_evidence"] = "partial"
    else:
        sections["9_full_evidence"] = "missing"

    counts = Counter(sections.values())
    return {
        "sections": sections,
        "met": counts.get("met", 0),
        "partial": counts.get("partial", 0),
        "missing": counts.get("missing", 0),
    }


def evidence_language_tags(report: dict[str, Any]) -> tuple[int, int]:
    """spec.md §31: every claim should carry which of the four kinds
    (observed/inferred/grounded/proposed) it is. `evidenceKind` is SEC-6's
    field; absent today, so this reads 0/N until SEC-6 lands."""
    findings = report.get("critical_pain_points") or []
    tagged = sum(1 for f in findings if f.get("evidenceKind"))
    return tagged, len(findings)


# ---------------------------------------------------------------------------
# Cost group -- read from the assembled ux.report
# ---------------------------------------------------------------------------


def run_wall_seconds(runs: list[dict[str, Any]]) -> float | None:
    total = 0.0
    found = False
    for run in runs:
        ms = run.get("durationMs")
        if ms:
            total += ms / 1000
            found = True
    return round(total, 1) if found else None


def cost_from_report(report: dict[str, Any]) -> dict[str, Any]:
    usage = report.get("model_usage") or {}
    by_role = usage.get("byRole") or {}
    total_wall = usage.get("totalWallMs")
    adherence_wall = (by_role.get("adherence") or {}).get("wallMs")
    adherence_share = (
        (adherence_wall / total_wall) if (total_wall and adherence_wall is not None) else None
    )
    return {
        "model_calls": usage.get("totalCalls") or 0,
        "prompt_tokens": usage.get("totalPromptTokens") or 0,
        "completion_tokens": usage.get("totalCompletionTokens") or 0,
        "adherence_share_of_model_wall": adherence_share,
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def compute_metrics(run_dirs: list[Path]) -> dict[str, Any]:
    loaded = [load_run(d) for d in run_dirs]
    reports = [item["report"] for item in loaded]
    all_runs: list[dict[str, Any]] = []
    for item in loaded:
        all_runs.extend(item["journey_log"].get("runs") or [])

    # Every report in a pooled measurement is assumed to share the same task
    # list (one cohort, or several cohorts run against the same benchmark
    # task set) -- the first report's task count sets the step budget for
    # the whole pool. A mixed-task pool is not a shape RUN-2/RUN-6 produce.
    num_tasks = 0
    if reports:
        num_tasks = len((reports[0].get("journey_outcome") or {}).get("tasks") or [])

    budget_hits = budget_hit_run_ids(all_runs, num_tasks)

    verdicts = verdict_counts(all_runs)
    budget_hit_count = len(budget_hits)
    stuck_count, _ = stuck_high_frustration(all_runs)
    loop_count = sum(1 for run in all_runs if has_loop(run))
    exec_below = sum(executed_below_threshold(run) for run in all_runs)

    exp_pairs = [e for e in (expectations_met_rate(r) for r in reports) if e]
    exp_met = sum(e[0] for e in exp_pairs)
    exp_total = sum(e[1] for e in exp_pairs)

    captures, refused = perception_captures(all_runs)
    legible = legible_share(all_runs)
    slope = not_looked_at_slope(all_runs)
    ptr_total, ptr_measured, ptr_missed = pointer_stats(all_runs)

    fg_list = [findings_group(r, budget_hits) for r in reports]

    def _sum(key: str) -> int:
        return sum(fg[key] for fg in fg_list)

    pooled_fill: dict[str, list[int]] = {}
    if fg_list:
        for key in fg_list[0]["fill_rates"]:
            num = sum(fg["fill_rates"][key][0] for fg in fg_list)
            den = sum(fg["fill_rates"][key][1] for fg in fg_list)
            pooled_fill[key] = [num, den]

    contract_per_report = [report_contract_sections(r) for r in reports]
    lang_pairs = [evidence_language_tags(r) for r in reports]
    lang_tagged = sum(p[0] for p in lang_pairs)
    lang_total = sum(p[1] for p in lang_pairs)

    wall_s = run_wall_seconds(all_runs)
    cost_list = [cost_from_report(r) for r in reports]
    adherence_shares = [
        c["adherence_share_of_model_wall"]
        for c in cost_list
        if c["adherence_share_of_model_wall"] is not None
    ]

    return {
        "run_dirs": [str(d) for d in run_dirs],
        "journey": {
            "verdicts": verdicts,
            "budget_hit": [budget_hit_count, len(all_runs)],
            "stuck_high_frustration": [stuck_count, len(all_runs)],
            "loops": loop_count,
            "runs_total": len(all_runs),
            "executed_actions_below_threshold": exec_below,
            "expectations_met_rate": [exp_met, exp_total],
        },
        "perception": {
            "captures": captures,
            "refused": refused,
            "legible_share": legible,
            "not_looked_at_slope": slope,
            "pointer": {"total": ptr_total, "measured": ptr_measured, "missed": ptr_missed},
        },
        "findings": {
            "findings_about_site": _sum("findings_about_site"),
            "positives": _sum("positives"),
            "run_diagnostics_among_findings": _sum("run_diagnostics_among_findings"),
            "false_contrast_low_ratio": _sum("false_contrast_low_ratio"),
            "false_contrast_titles": [t for fg in fg_list for t in fg["false_contrast_titles"]],
            "preserved_and_faulted_overlap": _sum("preserved_and_faulted_overlap"),
            "preserved_and_faulted_pairs": [
                pair for fg in fg_list for pair in fg["preserved_and_faulted_pairs"]
            ],
            "contentless_quotes": _sum("contentless_quotes"),
        },
        "fill_rates": pooled_fill,
        "contract": {
            "per_report": contract_per_report,
            "evidence_language_tags": [lang_tagged, lang_total],
        },
        "cost": {
            "run_wall_s": wall_s,
            "model_calls": sum(c["model_calls"] for c in cost_list),
            "prompt_tokens": sum(c["prompt_tokens"] for c in cost_list),
            "completion_tokens": sum(c["completion_tokens"] for c in cost_list),
            "adherence_share_of_model_wall": (
                sum(adherence_shares) / len(adherence_shares) if adherence_shares else None
            ),
        },
        "stability": {
            "reproduced_ge_2": None,
            "note": "needs a repeat-seed cohort (SCL-1); not measured from a single run",
        },
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt_frac(pair) -> str:
    if not pair:
        return "unmeasured"
    num, den = pair
    return f"{num}/{den}" if den else f"{num}/0"


def format_markdown_row(metrics: dict[str, Any]) -> str:
    """One scoreboard row, matching docs/parallel-development-overview.md's
    table shape -- for docs/scoreboard.md, written by RUN-2's run_cycle.py."""
    j, p, f, fr, c, cost = (
        metrics["journey"],
        metrics["perception"],
        metrics["findings"],
        metrics["fill_rates"],
        metrics["contract"],
        metrics["cost"],
    )
    v = j["verdicts"]
    lines = [
        f"| Verdicts: passed / failed / inconclusive | {v['passed']} / {v['failed']} / {v['inconclusive']} |",
        f"| Budget-hit share | {_fmt_frac(j['budget_hit'])} |",
        f"| Runs ending at frustration >= 0.9 still browsing | {j['stuck_high_frustration'][0]} |",
        f"| Loops | {j['loops']} |",
        f"| Actions executed below the adherence threshold | {j['executed_actions_below_threshold']} |",
        f"| Expectations met rate | {_fmt_frac(j['expectations_met_rate'])} |",
        f"| Captures / refused | {p['captures']} / {p['refused']} |",
        f"| Legible share (pooled) | {p['legible_share']:.2f} |" if p["legible_share"] is not None else "| Legible share (pooled) | unmeasured |",
        f"| notLookedAt slope | {p['not_looked_at_slope']} |",
        f"| Pointer measured / total | {p['pointer']['measured']} / {p['pointer']['total']} |",
        f"| Findings about the site / positives | {f['findings_about_site']} / {f['positives']} |",
        f"| Run diagnostics filed as findings | {f['run_diagnostics_among_findings']} |",
        f"| False contrast (ratio < 1.2) | {f['false_contrast_low_ratio']} |",
        f"| Preserved-and-faulted overlaps | {f['preserved_and_faulted_overlap']} |",
        f"| Contentless quotes | {f['contentless_quotes']} |",
    ]
    for key, label in [
        ("alternatives_with_effort", "Alternatives with effort"),
        ("confidence", "Confidence"),
        ("video_timestamp", "Video timestamp (where a screenshot exists)"),
        ("root_cause", "Root cause"),
        ("grounding", "Grounding"),
    ]:
        if key in fr:
            lines.append(f"| {label} | {_fmt_frac(fr[key])} |")
    for report in c["per_report"]:
        lines.append(f"| Section 30 met / partial / missing | {report['met']} / {report['partial']} / {report['missing']} |")
    lines.append(f"| Section 31 tagged claims | {_fmt_frac(c['evidence_language_tags'])} |")
    lines.append(f"| Run wall (s) / model calls / tokens | {cost['run_wall_s']} / {cost['model_calls']} / {cost['prompt_tokens'] + cost['completion_tokens']} |")
    adh = cost["adherence_share_of_model_wall"]
    lines.append(f"| Adherence share of model wall | {adh:.0%} |" if adh is not None else "| Adherence share of model wall | unmeasured |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="+", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    args = parser.parse_args(argv)

    metrics = compute_metrics(args.run_dirs)
    payload = json.dumps(metrics, indent=2, default=str)
    row = format_markdown_row(metrics)

    if args.json_out:
        args.json_out.write_text(payload + "\n")
    else:
        print(payload)
    if args.md_out:
        args.md_out.write_text(row + "\n")
    else:
        print(row, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
