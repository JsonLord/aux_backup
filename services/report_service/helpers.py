"""Module-level helpers for assembling a report.

Moved verbatim from apps/api/executor.py (BE-2). `apps.api.executor`
re-exports every name here, so existing importers are unaffected.
"""
from __future__ import annotations

import base64
from collections import Counter
from html import escape
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import shutil
from typing import Any
from urllib import request

from apps.api.store import Store



def download_name(kind: str, job_id: str, capture_stem: str | None = None) -> str:
    extension = {"ux.report": "json", "ux.presentation": "html", "ux.slides": "html", "journey.log": "json",
                 "ui.prototype": "html", "browser.screenshot": "png", "browser.snapshot": "json",
                 "browser.ui-change": "json", "browser.video": "webm"}[kind]
    # A run captures many screenshots; naming them all after the job alone made
    # them indistinguishable. The capture's own stem is what tells them apart
    # (and pairs a snapshot with its screenshot).
    suffix = f"-{re.sub(r'[^A-Za-z0-9_.-]', '_', capture_stem)}" if capture_stem else ""
    return f"{kind.replace('.', '-')}-{job_id}{suffix}.{extension}"

_JOURNEYTEST_SEVERITY_MAP = {"info": "low", "minor": "medium", "major": "high", "critical": "critical"}
# journeyContract() always emits a single fail criterion with this id (see
# services/journey-worker/node/src/journeytest.js) -- for a fail criterion,
# result == "met" means the failure condition occurred (bad); every other
# criterion in this codebase is a pass criterion, where "not-met"/"blocked" is bad.
_FAIL_CRITERION_IDS = {"tasks-blocked"}
# Bookkeeping browser events whose summaries are pure plumbing ("Captured
# screenshot") rather than anything a reader would recognise as the persona
# doing something. Excluded from the narration so the thought log reads as a
# journey, not a driver trace.
_QUIET_BROWSER_EVENTS = {"browser.snapshot", "browser.screenshot", "browser.get_url", "browser.get_title",
                         "browser.console_evidence", "browser.network_evidence",
                         "browser.network_har.start", "browser.network_har.stop"}
# Generic quality adjectives. They carry no information about *which* design
# decision is being praised, so they are ignored when grouping strengths.
_QUALITY_ADJECTIVES = frozenset({
    "clear", "clean", "high", "good", "great", "excellent", "strong", "effective", "simple",
    "minimalist", "minimal", "concise", "consistent", "well", "nice", "solid", "readable",
    "distraction", "free", "design", "visual", "excellentt",
})
# JourneyTest's `uxFindings` bucket is "things the reviewer noticed about the UX",
# and a real run puts praise in it as readily as problems ("Clear value proposition",
# "Prominent sign-up entry point" both arrived there against a live site). The
# schema has no polarity field, so polarity has to be read from the text. The
# asymmetry matters: mistaking praise for a problem publishes a wrong issue, while
# mistaking a problem for praise buries a real one -- so an item is only treated as
# praise when it carries praise language AND no problem language at all.
_PRAISE_MARKERS = re.compile(
    r"\b(clear|clearly|clean|prominent|prominently|well[- ]\w+|good|great|excellent|strong|"
    r"effective|effectively|simple|intuitive|easy|easily|readable|legible|consistent|obvious|"
    r"helpful|accessible|concise|visible|straightforward|polished|professional|"
    r"uncluttered|scannable|discoverable|reassuring|works well|done well)\b", re.I)
_PROBLEM_MARKERS = re.compile(
    r"\b(no|not|never|none|without|missing|missed|lack|lacks|lacking|absent|unclear|ambiguous|"
    r"ambiguity|confus\w*|difficult|hard|cannot|can't|unable|fail|fails|failed|failure|error|"
    r"errors|broken|block|blocks|blocked|blocking|slow|hidden|hides|obscure\w*|overwhelm\w*|"
    r"inconsistent|inconsistency|clutter\w*|cramped|tiny|small|low|poor|weak|risk|risky|issue|"
    r"issues|problem|problems|frustrat\w*|mislead\w*|distract\w*|too|only|but|however|although|"
    r"should|would benefit|improve|improved|improvement|instead|degrade\w*|truncat\w*|overlap\w*|"
    r"contrast ratio|unlabel\w*|unreadable|illegible|inaccessible)\b", re.I)


def _reads_as_timeout(error: BaseException) -> bool:
    """Whether this urllib failure is "the answer did not arrive in time".

    A read timeout surfaces as socket.timeout, which is TimeoutError since 3.10;
    a connect timeout is wrapped in URLError with the same object as its reason.
    Anything else -- refused, DNS, reset -- means the worker was never going to
    answer, and there is nothing on disk to go looking for.
    """
    if isinstance(error, TimeoutError):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, TimeoutError)


def _reads_as_praise(title: str, description: str) -> bool:
    """True when a verdict finding describes a design decision that works.

    Deliberately one-sided: praise language must be present and problem language
    must be entirely absent. "Clear labelling, but the button is small" keeps its
    problem word and stays an issue.
    """
    text = f"{title or ''} {description or ''}"
    if not text.strip():
        return False
    return bool(_PRAISE_MARKERS.search(text)) and not _PROBLEM_MARKERS.search(text)


_TITLE_STOPWORDS = {"the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "is", "are", "not",
                    "its", "it's", "this", "that", "was", "were", "be", "been", "has", "have", "but"}
# Additional filler that carries no information in a *sentence* (titles are short
# enough that these barely occur, so they are kept out of _TITLE_STOPWORDS and the
# tuned title threshold is left undisturbed).
_PROSE_STOPWORDS = frozenset({
    "page", "users", "user", "use", "uses", "using", "which", "when", "from", "into", "also", "more",
    "some", "them", "they", "their", "there", "would", "could", "should", "make", "makes", "may",
    "might", "seem", "seems", "about", "other", "each", "between", "than", "then", "because",
    "while", "where", "what",
})
# Plural stripping is handled first and on its own (see _stem), so these must not
# contain a plural rule: two rules that can both fire on one word are how the
# stemmer came to disagree with itself about "price" and "prices".
_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ied", "ed")
# English adds "es" rather than "s" after a sibilant. Without this, "classes"
# stemmed to "classe" while "class" stemmed to "class".
_SIBILANTS = "sxzhi"


def _stem(word: str) -> str:
    """Crude suffix stripping, enough that "control"/"controls" and
    "price"/"prices" compare equal. Two findings describing one problem rarely
    reuse the same inflections.

    The plural comes off first, once, and by English's own rules, because the
    length guard below made two of these rules disagree on exactly the pair they
    exist for: "prices" is six letters, so it cleared `len > len("es") + 3` and
    stemmed to "pric", while "price" is five, cleared nothing, and stayed "price".
    A live report threw away the one quote that was genuinely about its finding --
    "No price was visible anywhere." under a finding about text reading "Prices
    exclude VAT" -- because the two words shared no stem.
    """
    if len(word) > 4 and word.endswith("ies"):
        word = word[:-3] + "y"                       # policies -> policy
    elif len(word) > 3 and word.endswith("es") and word[-3] in _SIBILANTS:
        word = word[:-2]                             # classes -> class, boxes -> box
    elif len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]                             # prices -> price, links -> link
    for suffix in _SUFFIXES:
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word
# A pass criterion is a machine label; a report reads it as a sentence about the
# user. Keyed by (criterion id, result) so a fail criterion's "met" -- which means
# the failure actually happened -- never reads as a success.
_CRITERION_TITLES = {
    ("tasks-completed", "not-met"): "Users could not finish the tasks they came to do",
    ("tasks-completed", "blocked"): "The journey was blocked before the tasks could be judged",
    ("tasks-blocked", "met"): "The journey was blocked before completion",
    ("tasks-blocked", "blocked"): "The journey was blocked before completion",
}
# The same rule for the criteria that were met: an "elements to preserve" entry
# is a sentence about what works, not the engine's criterion id.
_MET_CRITERION_TITLES = {
    "tasks-completed": "Users can finish the tasks they came to do",
}
# Failures of the test harness itself. Real, worth reporting, but they are not
# usability findings about the product and must not be numbered among them.
_RUN_DIAGNOSTIC_PATTERNS = (
    re.compile(r"\bpi director\b", re.I),
    re.compile(r"\bdirector (did not|failed)\b", re.I),
    re.compile(r"\bprovider (error|timeout)\b", re.I),
    re.compile(r"\bagent (crashed|errored)\b", re.I),
)


def _is_run_diagnostic(finding: dict[str, Any]) -> bool:
    """True when a finding describes the harness failing rather than the product."""
    text = f"{finding.get('title', '')} {finding.get('summary', '')}"
    return any(pattern.search(text) for pattern in _RUN_DIAGNOSTIC_PATTERNS)


def step_budget(num_tasks: int) -> int:
    """journeytest.js's own stepBudget(): `min(40, max(12, tasks.length * 8))`
    (services/journey-worker/node/src/journeytest.js). Kept here, once, so
    SEC-1's diagnostic split and scripts/cycle/measure.py's own scoring agree
    on when a run hit this limit rather than reaching a real conclusion --
    the worksheet's own finding that 11 of 12 inconclusive runs in the
    cycle 44-51 record ended on exactly this number."""
    return min(40, max(12, num_tasks * 8))


def _actions_taken(journey: dict[str, Any]) -> int:
    """One `persona.expectation` event per action the persona decided to
    take -- the same count the report's own `scorecard.runs[].actionsTaken`
    carries (verified against last_runs/: 12 events, 12 actionsTaken)."""
    return sum(1 for event in (journey.get("timeline") or []) if event.get("type") == "persona.expectation")


def _budget_hit_run_ids(journeys: list[dict[str, Any]], num_tasks: int) -> set[str]:
    """Runs that ended inconclusive because the step budget ran out, not
    because the persona reached a real conclusion. See `step_budget()`."""
    budget = step_budget(num_tasks)
    return {
        journey.get("runId")
        for journey in journeys
        if ((journey.get("verdict") or {}).get("status") or "").lower() == "inconclusive"
        and _actions_taken(journey) >= budget
    }


def _is_budget_limited_finding(finding: dict[str, Any], budget_hit_run_ids: set[str]) -> bool:
    """SEC-1: true when a finding describes a run that hit its step budget
    rather than reaching a real conclusion -- the harness's own limit, not
    a usability claim about the product. Two independent shapes carry this,
    found by running a live snapshot through the fix rather than by
    inspection: JourneyTest's own `tasks-completed` criterion ("Users could
    not finish the tasks they came to do", `source: criteria`), and its
    `blockers` bucket's own "persona-stopped" id ("The visitor did not get
    there", `source: blockers`) -- the same run, reported twice, under two
    different titles, from two different parts of the same verdict. Both
    are scoped to the run actually being inconclusive-on-budget (`runId in
    budget_hit_run_ids`), matching scripts/cycle/measure.py's own check:
    `criterionResult: "blocked"` (a different failure -- the run could not
    even assess the criterion) and a genuine GIVE_UP (which ends a run
    "failed", not "inconclusive") are both left as real findings."""
    if finding.get("runId") not in budget_hit_run_ids:
        return False
    return (finding.get("criterionId") == "tasks-completed" and finding.get("criterionResult") == "not-met") or (
        finding.get("blockerId") == "persona-stopped"
    )


# A run's own instruments failing. Each is recorded by the persona director the
# moment it happens, and each makes the run weaker in a way a reader cannot infer
# from the findings: the measurement stopped, so an absence of findings means
# nothing. Matching on finding *text* (above) can never catch these -- they
# produce no finding at all, which is exactly the problem.
_INSTRUMENT_FAILURES = {
    "persona.perception_unavailable": (
        "The run stopped seeing the page through this person's eyes",
        "The perception service stopped answering, so the rest of this run reasoned about the "
        "accessibility tree instead of the rendered pixels. No eyesight finding -- text too small "
        "or too low-contrast for this person to read, anything they never looked at -- could be "
        "made after that point. Their absence from this report is not evidence that the page has "
        "none."),
    "persona.adherence_unavailable": (
        "Nothing checked whether the actions sounded like this person",
        "The adherence judge stopped answering, so from that point the persona's actions were "
        "taken as-is rather than scored against who they are and sent back when they did not fit. "
        "The run still browsed as this person's abilities and patience dictate; what stopped is "
        "the check on whether its choices read like them."),
    # CAP-4: a run that started signed in and lost that session mid-run reviews the
    # logged-out product without knowing it -- the worst failure available, because
    # nothing else here would say so. The director ends the run the moment it
    # notices rather than continuing to treat the logged-out page as evidence.
    "journey.session_expired": (
        "The authenticated session this run started with stopped holding",
        "The run began signed in and, partway through, the page it was on read as "
        "signed out again. Everything measured after that point would have been about "
        "the logged-out product, not the one this run was asked to review, so the "
        "director ended the run there instead of continuing. This is not a claim "
        "that the product failed -- it is a run-harness condition, and the findings "
        "this run could have made past that point are unknown, not absent."),
}


def _instrument_diagnostics(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run diagnostics for a run whose own instruments failed mid-flight.

    A live report came back with `run_diagnostics: []` on a run where the whole
    perception path had never executed. Nothing was wrong with the diagnostic
    mechanism: it filters *findings* by their wording, and an instrument that stops
    answering produces no finding to filter. So read the events the director writes
    when it notices, and report those.
    """
    diagnostics = []
    for journey in journeys:
        run_id = journey.get("runId")
        for event in journey.get("timeline") or []:
            entry = _INSTRUMENT_FAILURES.get(str(event.get("type") or ""))
            if not entry:
                continue
            title, summary = entry
            data = event.get("data") or {}
            reason = str(data.get("reason") or "").strip()
            diagnostics.append({
                "severity": "high", "category": "harness", "title": title,
                "summary": summary + (f" Reported reason: {reason}" if reason else ""),
                "recommendation": "Check the service is reachable from the worker and re-run; the "
                                  "findings this run could not make are still unknown, not absent.",
                "evidence": f"{event.get('type')} at step {data.get('sinceStep', '?')} of run {run_id}",
                "source": "instrument", "runId": run_id,
                "personaId": journey.get("profileId")})
    return diagnostics


def plural(count: int, word: str, many: str | None = None) -> str:
    """`1 run`, `2 runs` -- not `1 run(s)`.

    A report that writes "1 usability issue(s) were identified" is telling the
    reader, in its own first sentence, that it was assembled rather than written.

    Module level on purpose. This lived as a method on JobExecutor and fixed
    exactly one of the eighteen places that needed it, which is the same mistake
    in a different costume: a rule written where the problem was noticed rather
    than where it applies.
    """
    return f"{count} {word if count == 1 else (many or word + 's')}"


def verb(count: int, one: str, many: str) -> str:
    """`1 finding was discarded`, `2 findings were discarded`."""
    return one if count == 1 else many


def _coverage_diagnostics(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """How much of each run the instruments actually saw.

    `_instrument_diagnostics` reports an instrument that stopped answering, which
    fires once and ends the run's eyesight. It says nothing about a run that kept
    its eyesight and lost individual steps -- and that is the common case. Cycle 26
    lost four walks in one journey and shipped `run_diagnostics: []`, so a reader
    had no way to know the review was made on ten steps of twelve.

    This is not a failure report. The run worked; it saw less of the page than it
    tried to, and a reader weighing an absent finding deserves to know which.
    """
    diagnostics = []
    for journey in journeys:
        timeline = journey.get("timeline") or []
        steps = sum(1 for event in timeline if event.get("type") == "persona.expectation")
        looked = sum(1 for event in timeline if event.get("type") == "persona.perception")
        lost = [str((event.get("data") or {}).get("reason") or "").strip()
                for event in timeline if event.get("type") == "persona.perception_fallback"]
        undrawn = sum(1 for event in timeline if event.get("type") == "persona.reflection_unavailable")
        if not steps or (not lost and not undrawn):
            continue
        share = (steps - looked) / steps if steps else 0.0
        reasons = Counter(reason for reason in lost if reason)
        why = "; ".join(f"{reason} ({count}\u00d7)" for reason, count in reasons.most_common(3))
        parts = []
        if lost:
            parts.append(f"This person's eyes resolved the page on {looked} of {steps} steps. "
                         f"Where they did not, the run reasoned about the accessibility tree instead, "
                         f"so no eyesight finding could be made on those steps"
                         + (f" -- {why}" if why else "") + ".")
        if undrawn:
            parts.append(f"{plural(undrawn, 'action')} drew no conclusion at all, because the page could not "
                         f"be seen the same way before and after them. Comparing across two different "
                         f"kinds of looking invents gaps, so nothing was concluded rather than "
                         f"something guessed.")
        diagnostics.append({
            "severity": "high" if share > 0.34 else "medium" if share > 0 else "info",
            "category": "harness", "title": "Part of this run was made without eyesight",
            "summary": " ".join(parts),
            "recommendation": ("Read an absent eyesight finding on those steps as unknown rather than "
                               "absent. Re-running is cheap and the lost steps are usually transient."),
            "evidence": (f"{looked}/{steps} steps perceived, "
                         f"{plural(len(lost), 'walk')} unusable"
                         + (f", {plural(undrawn, 'comparison')} skipped" if undrawn else "")),
            "source": "coverage", "runId": journey.get("runId"),
            "personaId": journey.get("profileId")})
    return diagnostics


def _capture_name(path: str | None, kind: str = "", job_id: str = "") -> str:
    """The name a capture is known by, not where the container happened to write it.

    A live deck rendered "snapshot: /home/user/artifacts/journeys/2026-08-30T10-57-
    43-548Z-job_08147074e9f648a58d3c/snapshots/005-snapshot.txt" as its root-cause
    analysis. The absolute path says nothing to a reader and is meaningless once the
    container is gone.

    The capture's own file name is no better for finding the thing: the run writes
    "003-snapshot.txt" and the workspace lists the same capture as
    "browser-snapshot-<job>-003-snapshot.json" (JobExecutor._download_name). A live
    report cited "snapshot: 003-snapshot.txt" for its only finding, and no artifact
    in the session was called that -- the evidence existed and was unreachable by
    the name given for it. With the kind and job known, cite the name the artifact
    is actually listed under; otherwise fall back to the capture's own name, which
    at least names the capture."""
    if not path:
        return ""
    name = Path(str(path)).name
    if not kind or not job_id:
        return name
    return download_name(kind, job_id, Path(name).stem)


def _evidence_reference_summary(evidence: dict[str, Any] | None, job_id: str = "") -> str:
    """Render a JourneyTest EvidenceReference (screenshot/snapshot/observation/... path
    or text) into a single human-readable string for the report's ``evidence`` field.

    ``job_id`` is what lets a citation name the artifact a reader can actually
    download rather than the file name the run happened to use. It is optional
    because a finding is still worth reporting when it is not known."""
    if not evidence:
        return "No evidence reference recorded on this finding."
    parts = []
    if evidence.get("observation"):
        parts.append(evidence["observation"])
    if evidence.get("screenshot"):
        parts.append(f"screenshot: {_capture_name(evidence['screenshot'], 'browser.screenshot', job_id)}")
    if evidence.get("snapshot"):
        parts.append(f"snapshot: {_capture_name(evidence['snapshot'], 'browser.snapshot', job_id)}")
    if evidence.get("uiChangeTimeline"):
        parts.append("UI change timeline: "
                     f"{_capture_name(evidence['uiChangeTimeline'], 'browser.ui-change', job_id)}")
    if evidence.get("url"):
        parts.append(f"url: {evidence['url']}")
    if evidence.get("videoTimeMs") is not None:
        parts.append(f"video @ {evidence['videoTimeMs']}ms")
    return "; ".join(parts) if parts else "Evidence reference recorded without a readable field."


# What a citation in a report looks like: the name an evidence artifact is listed
# under (JobExecutor._download_name).
# A label a persona quoted while saying what it expected -- the human name for a
# control the action record only has a ref for.
_QUOTED_LABEL = re.compile(r"['\u2018\u201c\"]([^'\u2019\u201d\"]{2,60})['\u2019\u201d\"]")
# "Clicking the Annual button will..." -- the thing a sentence names as the one
# being acted on, when the persona did not put quotes round it.
_NAMED_CONTROL = re.compile(
    r"\b(?:click(?:ing)?|press(?:ing)?|select(?:ing)?|tapp?(?:ing)?)\s+(?:on\s+)?(?:the\s+)?"
    r"([\w'\u2019\u00b7][\w'\u2019\u00b7\- ]{0,40}?)\s+(?:button|link|tab|toggle|control|icon)\b",
    re.IGNORECASE)
_CITED_CAPTURE = re.compile(r"\bbrowser-(?:screenshot|snapshot|ui-change|video)-[\w.-]+", re.I)


def _grey_at_luminance(luminance: float) -> str:
    """The neutral grey with this relative luminance, as a hex the reader can try.

    A luminance is not a colour -- many colours share one -- so this is offered as
    a worked example of something dark enough rather than as the colour the page
    should use. The inverse of the sRGB transfer function, which is what the WCAG
    definition of relative luminance applies in the first place.
    """
    luminance = min(1.0, max(0.0, float(luminance)))
    channel = (luminance * 12.92 if luminance <= 0.0031308
               else 1.055 * (luminance ** (1 / 2.4)) - 0.055)
    # Down, never to nearest. Rounding to nearest returned #777777 for a target of
    # 0.1833 -- one step above it, at 0.1845, so the colour offered as the fix
    # would itself have failed the check. A suggestion that does not clear the bar
    # is worse than no suggestion.
    value = max(0, min(255, math.floor(channel * 255)))
    return f"#{value:02x}{value:02x}{value:02x}"


def contrast_fix(contrast: dict[str, Any]) -> str:
    """What to change on this page, from what was measured on it.

    "Raise the contrast to at least 4.5:1" restates the guideline the finding has
    already quoted; it is not a fix. The measurement knows both luminances and the
    arithmetic gives the target exactly, so the report can say how far the darker
    side has to move and offer a grey that gets there.
    """
    target = contrast.get("needsLuminanceBelow")
    ink, paper = contrast.get("inkLuminance"), contrast.get("paperLuminance")
    if target is None and ink is not None:
        # No colour, black included, reaches the requirement against this
        # background: telling anyone to darken the text is advice that cannot be
        # taken, and the background is what has to move.
        return ("No foreground colour can reach this ratio against the background it is on -- "
                "black text would still fall short. The background is what has to change here, "
                "not the text.")
    if target is None or ink is None or paper is None:
        return ""
    if ink <= target:
        return ""
    return (f"Measured on the pixels: the darker side sits at {ink:g} relative luminance and has "
            f"to reach {target:g} or below against a background at {paper:g}. "
            f"{_grey_at_luminance(target)} is a neutral that gets there -- any colour at or below "
            f"that luminance does.")


def cited_captures(report: dict[str, Any]) -> set[str]:
    """Every capture name this report asks a reader to go and look at.

    Read off the rendered citations rather than off the findings' fields, because
    the citation is what the reader actually has to resolve. A finding may carry a
    path that never became an artifact, and the report would still read as though
    the evidence were there.
    """
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.update(match.group(0) for match in _CITED_CAPTURE.finditer(value))
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(report)
    return found


def unresolvable_citations(report: dict[str, Any], available: set[str]) -> list[str]:
    """Capture names the report cites that this session does not actually hold.

    Evidence a reader cannot resolve from its citation is evidence the report did
    not really produce, and it is worse than no citation: it reads as corroborated.
    """
    return sorted(cited_captures(report) - available)


