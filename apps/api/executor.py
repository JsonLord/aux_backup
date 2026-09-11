"""Local job executor implementing useful control-plane behavior without Jules.

The interface intentionally keeps execution behind persisted jobs and artifacts so a
JourneyTest worker can replace this development executor without changing clients.
"""
from __future__ import annotations

import base64
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

from .store import Store


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
    return JobExecutor._download_name(kind, job_id, Path(name).stem)


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


class JobExecutor:
    def __init__(self, store: Store):
        self.store = store

    def run(self, job_id: str) -> None:
        job = self.store.claim_job(job_id)
        if not job:
            return
        dependencies = [self.store.get_job(item) for item in job["depends_on"]]
        if any(item is None or item["status"] != "succeeded" for item in dependencies):
            self.store.update_job(job_id, "waiting_on_dependency")
            self.store.event(job_id, "job.waiting_on_dependency", 0, {"depends_on": job["depends_on"]})
            return
        self.store.start_attempt(job_id, job["attempt"])
        self.store.event(job_id, "job.started", .05, {"attempt": job["attempt"]})
        try:
            if job["type"] == "combined_test":
                result = self._combined_test(job)
                captures = self._browser_outputs(result)
                # Every capture this session will actually hold, by the name a
                # reader would search for. Checked before the report is rendered,
                # because a citation that resolves to nothing is worse than no
                # citation: it reads as corroborated. A live report cited
                # "snapshot: 003-snapshot.txt" and no artifact in the session was
                # called that.
                available = {self._download_name(item[0], job_id,
                                                 (item[3] if len(item) > 3 else {}).get("capture_stem"))
                             for item in captures}
                missing = unresolvable_citations(result, available)
                if missing:
                    result.setdefault("limitations", []).append(
                        f"{len(missing)} capture(s) cited in this report were not kept as artifacts in "
                        f"this session, so they cannot be opened from it: {', '.join(missing[:6])}"
                        + ("..." if len(missing) > 6 else "")
                        + ". The finding still stands on its measurement; only the pointer to the "
                        "capture is broken.")
                outputs = [
                    ("ux.report", "application/json", result),
                    ("ux.presentation", "text/html", self._presentation(result)),
                    ("ux.slides", "text/html", self._slide_deck(result)),
                    ("journey.log", "application/json", {
                        "schema_version": "1.0",
                        "session_id": job["session_id"],
                        "job_id": job_id,
                        "runs": result.get("journey_outcome", {}).get("runs", []),
                    }),
                ]
                outputs.extend(captures)
            elif job["type"] == "ui_adaptation":
                result = self._ui_adaptation(job)
                outputs = [("ui.prototype", "text/html", result)]
            else:
                raise ValueError(f"unsupported job type: {job['type']}")
            artifacts = []
            for output in outputs:
                kind, content_type, content = output[0], output[1], output[2]
                extra = output[3] if len(output) > 3 else {}
                artifacts.append(self.store.create_artifact({"session_id": job["session_id"], "kind": kind,
                    "content_type": content_type, "content": content,
                    "metadata": {"job_id": job_id, "schema_version": "1.0", **extra,
                                 "download_name": self._download_name(kind, job_id, extra.get("capture_stem"))}}))
            artifact_ids = [artifact["artifact_id"] for artifact in artifacts]
            self.store.update_job(job_id, "running", output_artifacts=artifact_ids)
            for artifact in artifacts:
                self.store.event(job_id, "artifact.created", .95, {"artifact_id": artifact["artifact_id"], "kind": artifact["kind"]})
            self.store.finish_attempt(job_id, job["attempt"], "succeeded")
            self.store.event(job_id, "job.succeeded", 1, {"output_artifacts": artifact_ids})
            self._resume_dependents(job_id)
        except Exception as exc:
            error = {"code": "execution_failed", "message": str(exc), "retryable": False}
            self.store.finish_attempt(job_id, job["attempt"], "failed", error)
            self.store.event(job_id, "job.failed", 1, {"error": error})

    def _resume_dependents(self, completed_job_id: str) -> None:
        for waiting in self.store.waiting_jobs(completed_job_id):
            dependencies = [self.store.get_job(item) for item in waiting["depends_on"]]
            if dependencies and all(item and item["status"] == "succeeded" for item in dependencies):
                self.store.update_job(waiting["job_id"], "queued")
                self.store.event(waiting["job_id"], "job.dependencies_satisfied", 0, {"depends_on": waiting["depends_on"]})
                self.run(waiting["job_id"])

    def _combined_test(self, job: dict[str, Any]) -> dict[str, Any]:
        data = job["metadata"]
        persona_artifacts, tasks = data.get("persona_artifacts", []), data.get("tasks", [])
        personas = []
        for artifact_id in persona_artifacts:
            artifact = self.store.get_artifact(artifact_id)
            if not artifact or artifact["session_id"] != job["session_id"] or artifact["kind"] != "persona.profile":
                raise ValueError(f"invalid persona profile artifact: {artifact_id}")
            personas.append(json.loads(self.store.read_artifact(artifact_id)))
        if not personas or not tasks:
            raise ValueError("combined_test requires persona profile artifacts and non-empty metadata.tasks")
        journeys = []
        worker_url = os.getenv("JOURNEY_WORKER_URL")
        # services/journey-worker/node/src/safety.js blocks any task whose text
        # matches a destructive-action pattern (purchase, delete account, deploy
        # production, ...) against the real target URL unless
        # browserSafety.allowIrreversibleActions is explicitly set (spec.md
        # section 36: "require explicit configuration for purchases,
        # submissions or irreversible operations"). Read the caller's opt-in
        # from job metadata rather than never sending it -- previously this
        # field was never included, so any such task failed unconditionally
        # with no way to opt in.
        browser_safety = data.get("browserSafety") or {}
        # A run browses signed in when it is handed a session file. Without this
        # the credentials a workspace has stored were unreachable from a run, so
        # every run tested the logged-out product however many were saved.
        session_state_path, issued = self._prepare_run_session(job, data, personas)
        if worker_url:
            try:
                for persona in personas:
                    run_identity = issued.get(persona.get("id")) if issued else None
                    run_id = f"{job['job_id']}_{persona.get('id', len(journeys))}"
                    payload = json.dumps({"runId": run_id, "url": data.get("url"),
                        "tasks": tasks, "profile": persona, "browserSafety": browser_safety,
                        **({"sessionStatePath": session_state_path} if session_state_path else {}),
                        **({"identity": run_identity} if run_identity else {})}).encode()
                    call = request.Request(f"{worker_url.rstrip('/')}/v1/runs", data=payload, headers={"content-type": "application/json"}, method="POST")
                    try:
                        with request.urlopen(call, timeout=self._journey_run_timeout()) as response:
                            journey = json.loads(response.read())
                            journeys.append(self._usable_journey(journey))
                    except request.HTTPError as error:
                        detail = error.read().decode("utf-8", errors="replace")[:2000]
                        if error.code == 422 and "allowIrreversibleActions" in detail and not browser_safety.get("allowIrreversibleActions"):
                            raise RuntimeError(
                                "Journey worker rejected run (422): one of the configured tasks reads as a "
                                "potentially irreversible action (purchase, account deletion, submission, "
                                "production deploy, ...). This run did not opt in to allow it -- re-run with "
                                "\"Allow potentially irreversible actions\" checked (Gradio UI) or "
                                "allow_irreversible_actions: true (API) if the task is genuinely meant to "
                                f"perform it. Raw detail: {detail}") from error
                        raise RuntimeError(f"Journey worker rejected run ({error.code}): {detail}") from error
                    except (TimeoutError, request.URLError) as error:
                        # Ordered after HTTPError, which subclasses URLError -- a
                        # rejected run must keep its own message.
                        if not _reads_as_timeout(error):
                            raise
                        # The run itself is still going and will still write its
                        # result to disk; only this side of the socket gave up. The
                        # artifact tree is reachable from here whenever the API and
                        # the worker share a filesystem, which is how the Space runs
                        # them -- so read the verdict from there rather than throw it
                        # away with the connection.
                        salvaged = self._journey_from_disk(run_id)
                        if salvaged is None:
                            raise RuntimeError(
                                f"Journey worker did not answer within {self._journey_run_timeout():.0f}s "
                                f"and no result for {run_id} was found on disk. Raise JOURNEY_RUN_TIMEOUT "
                                f"if runs against this target legitimately take longer.") from error
                        journeys.append(self._usable_journey(
                            {**salvaged, "profileId": salvaged.get("profileId") or persona.get("id"),
                             "simulationProfile": salvaged.get("simulationProfile") or persona}))
            finally:
                # The session file is a live login. It exists for the runs that
                # need it and not a moment longer -- including when one of them
                # raises, which is exactly when it would otherwise be left behind.
                if session_state_path:
                    shutil.rmtree(Path(session_state_path).parent, ignore_errors=True)
        if worker_url:
            findings = self._pain_points_from_journeys(journeys, job["job_id"])
            # What the persona's eyes made of the page. Two finding classes that
            # exist nowhere else, because no check against the DOM can produce
            # either -- see _pain_points_from_perception.
            findings += self._pain_points_from_perception(journeys)
            # What the page looked like it would do and then did not. First-hand,
            # falsifiable, and invisible to every other source here.
            findings += self._pain_points_from_expectations(journeys)
            cohort_runs, screenshot_bytes, raw_strengths, vision_error, repeated_captures = \
                self._collect_vision_pain_points(journeys, tasks, personas, data.get("url"))
            vision_findings = self._synthesize_pain_points(cohort_runs, screenshot_bytes) if cohort_runs else []
            # The vision model has a "strengths" array and still puts praise in
            # "issues" -- a live run published "Familiar and clean layout" as a
            # medium-severity usability issue. Same rule as JourneyTest's mixed
            # uxFindings bucket, applied to the other stage.
            vision_praise = [item for item in vision_findings
                             if _reads_as_praise(item.get("title"), item.get("summary"))]
            vision_findings = [item for item in vision_findings if item not in vision_praise]
            # The vision model reads screenshots confidently, and two of the things
            # it says are checkable against what this run recorded. Where they
            # disagree the measurement wins, and the report says so rather than
            # quietly rewriting a severity.
            tempered = (self._temper_contradicted_findings(vision_findings, journeys)
                        + self._cap_claimed_impact(vision_findings, journeys))
            findings.extend(vision_findings)
            preserve = (self._merge_strengths(raw_strengths + self._praise_from_verdicts(journeys)
                                              + self._praise_as_strengths(vision_praise))
                        + self._preserved_from_verdicts(journeys))
            # A run kept by _usable_journey() saw real pages but did not get to the
            # end of the journey. Saying "completed" about it would overstate the
            # coverage behind every finding below, so the status carries the
            # difference and the limitation names what went wrong.
            degraded = [journey for journey in journeys if journey.get("harnessError")]
            evidence_language = "observed"
            journey_status = "partial" if degraded else "completed"
            limitations = [
                "Findings are JourneyTest's own evidence-grounded verdict (blockers/uxFindings/"
                "suggestedImprovements/failed pass-criteria) from a real browser run against the "
                "target URL, not text inferred from the task description.",
            ]
            limitations.extend(tempered)
            if vision_findings:
                limitations.append(
                    "Findings tagged source=eyeson-vision-synthesis are cross-persona-aggregated (spec.md "
                    "section 20/21 cohort/root-cause aggregation): a real vision-model critique of actual "
                    "JourneyTest screenshots, grounded against a small curated UX-heuristics corpus, then "
                    "synthesized across every persona that hit the same underlying issue -- never a single "
                    "persona's individual citation, even when only one persona ran."
                )
            elif vision_error:
                limitations.append(f"Vision-based UX critique was attempted but failed: {vision_error}")
            else:
                limitations.append(
                    "Vision-based UX critique (EYESON_WORKER_URL) is not configured for this deployment; "
                    "critical_pain_points reflect JourneyTest's own task-completion verdict only, not a "
                    "deeper visual/accessibility critique of the screenshots."
                )
            if repeated_captures:
                limitations.append(
                    f"{len(repeated_captures)} full-page capture(s) came back as one viewport band repeated "
                    "down a very tall image -- what a stitched screenshot produces when the page pins its "
                    "layout to the viewport. They were trimmed to the single band that is a faithful "
                    "screenshot before anything was asked about them, so findings from those captures "
                    "describe the top of the page rather than its full length. Untrimmed, a live run "
                    "reported the repetition itself as a critical defect in a site that does not have one.")
            for journey in degraded:
                persona_id = journey.get("profileId") or journey.get("testerProfileId") or "unknown persona"
                verdict_note = ("its verdict was recorded before the failure and is included"
                                if journey.get("verdict")
                                else "no verdict was reached, so this run contributes screenshots only")
                limitations.append(
                    f"The run for {persona_id} did not finish cleanly: {journey['harnessError']}. "
                    f"The evidence it had already collected is real and is used, but the journey was cut "
                    f"short -- {verdict_note}. Findings from this run cover only what it reached."
                )
        else:
            findings = [{"severity": "medium", "category": "ux", "title": f"Validate task clarity: {task}",
                "summary": "", "evidence": "Inferred from the configured task; JOURNEY_WORKER_URL is not "
                           "configured for this deployment, so no live browser evidence was collected.",
                "source": "task_text"} for task in tasks]
            preserve = []
            evidence_language, journey_status = "inferred", "configured"
            limitations = ["JOURNEY_WORKER_URL is not configured for this deployment; no live "
                           "browser evidence was collected, so these findings are inferred from "
                           "the configured task text alone."]
        if worker_url and not findings:
            # "Nothing found" and "the run never got far enough to find anything"
            # look identical from here, and only one of them is a clean bill of
            # health. When every run was cut short, say which one this is.
            cut_short = journey_status == "partial" and len(degraded) == len(journeys)
            findings.append({"severity": "low", "category": "ux",
                "title": "Journey ended early -- no findings collected" if cut_short else "No pain points detected",
                "summary": ("Every run was cut short before it produced a verdict, and the vision critique "
                            "found nothing in the screenshots it reached. This is not a clean result: the "
                            "tasks were not fully exercised. See limitations for what went wrong."
                            if cut_short else
                            "Neither JourneyTest's verdict nor the vision-based UX critique reported "
                            "any blockers, UX findings, or failed pass criteria for the configured tasks."),
                "evidence": "See journey_outcome.runs[].verdict for the full per-run verdict.",
                "source": "verdict"})
        # A harness failure is real but is not a usability finding about the product;
        # numbering it among the user issues (as "Pi director did not finish the
        # journey" was) misrepresents both.
        run_diagnostics = [finding for finding in findings if _is_run_diagnostic(finding)]
        findings = self._merge_similar_findings([finding for finding in findings if finding not in run_diagnostics])
        # Added after the split, not before: an instrument failure is a diagnostic by
        # construction and must never be merged into, or dropped by, the usability
        # findings it is reported alongside.
        run_diagnostics = _instrument_diagnostics(journeys) + run_diagnostics
        findings, unverified = self._drop_unverifiable_quotes(findings, self._visible_text_corpus(journeys))
        if unverified:
            quoted = "; ".join(f"{item['title']!r} (quoted {', '.join(repr(q) for q in item['quotes'])})"
                               for item in unverified)
            limitations.append(
                f"{len(unverified)} finding(s) were discarded because they quoted on-page text that the "
                f"run's own element snapshots do not contain: {quoted}. Claims about literal visible text "
                "are checked against journeytest-core's snapshots before they are reported.")
        if run_diagnostics:
            limitations.append(
                f"{len(run_diagnostics)} run diagnostic(s) were recorded (the test harness itself failing, "
                "not the product): see run_diagnostics. They are excluded from the usability findings.")
        thoughts_by_persona = {persona.get("id"): self._persona_thoughts(journey)
                               for journey, persona in zip(journeys, personas) if persona.get("id")}
        persona_names = {persona.get("id"): (persona.get("persona") or {}).get("name") or persona.get("name") or persona.get("id")
                         for persona in personas}
        self._attach_persona_evidence(findings, thoughts_by_persona, persona_names)
        self._attach_verdict_screenshots(findings, journeys)
        self._attach_redesigns(findings, data.get("url"))
        sources = {item.get("source", "") for thoughts in thoughts_by_persona.values() for item in thoughts}
        if any(source.startswith("persona.") for source in sources):
            limitations.append(
                "Persona quotes are the person's own account of the page, recorded by the persona director as "
                "it browsed: what they expected a control to do before they touched it "
                "(`persona.expectation`), what actually arrived and how it differed (`persona.reflection`), "
                "and how that left them (`persona.affect`, worded from the gap rather than declared). They "
                "are first-person statements about a page. They are not the model's completion tokens, which "
                "are its own working about refs and evidence capture and are kept out of the report's quotes "
                "for exactly that reason."
            )
        if "model.reasoning" in sources:
            limitations.append(
                "Persona quotes are the director model's own reasoning tokens for each request, captured "
                "from the completions responses themselves. journeytest-core records only assistant `text` "
                "content blocks into the timeline and drops the `thinking` blocks a reasoning model returns, "
                "so this is read one layer lower, where nothing discards it. It is what the model was "
                "actually thinking while it drove the browser -- not a summary of it, and not written after "
                "the fact."
            )
        if any(source.startswith("verdict") for source in sources):
            limitations.append(
                "Some persona quotes come from an agent's own end-of-run verdict prose rather than its live "
                "reasoning, because no reasoning was captured for that run. Those are retrospective review "
                "written after the fact -- the agent's own words about what it hit, but not what it was "
                "thinking at the time. Every quote carries the source it came from (`model.reasoning`, "
                "`timeline`, or `verdict*`); they are not interchangeable."
            )
        return {"schema_version": "1.1", "mode": "user_journey", "url": data.get("url"),
                "executive_summary": self._executive_summary(data.get("url"), tasks, personas,
                                                             findings, preserve, journeys),
                "synthetic_users": personas, "persona_artifacts": persona_artifacts,
                "journey_outcome": {"status": journey_status, "tasks": tasks, "runs": journeys},
                "critical_pain_points": findings,
                "run_diagnostics": run_diagnostics,
                "flow_groups": self._flow_groups(findings, tasks),
                "elements_to_preserve": preserve,
                "impact_analysis": self._impact_analysis(findings, personas),
                "persona_narration": [{"personaId": persona_id, "personaName": persona_names.get(persona_id, persona_id),
                                       "thoughts": thoughts} for persona_id, thoughts in thoughts_by_persona.items()],
                "evidence_language": evidence_language, "limitations": limitations}

    @staticmethod
    def _preserved_from_verdicts(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Pass criteria JourneyTest actually met are the other half of "what works":
        a flow the agent completed is a design decision worth preserving, stated in
        the run's own words rather than inferred."""
        preserved: dict[str, dict[str, Any]] = {}
        for journey in journeys:
            for criterion in (journey.get("verdict") or {}).get("criteria", []):
                criterion_id = criterion.get("id")
                if criterion_id in _FAIL_CRITERION_IDS or criterion.get("result") != "met":
                    continue
                entry = preserved.setdefault(criterion_id, {
                    # Same rule as the findings: state it as something about the
                    # user, not as the engine's own criterion label.
                    "title": _MET_CRITERION_TITLES.get(criterion_id, "The flow completes as intended"),
                    "description": criterion.get("explanation") or "Synthetic users completed this flow end to end.",
                    "elements": [], "personaIds": [], "routes": [], "screenshotRefs": [], "source": "verdict",
                    "criterionId": criterion_id})
                persona_id = journey.get("profileId") or journey.get("testerProfileId")
                if persona_id and persona_id not in entry["personaIds"]:
                    entry["personaIds"].append(persona_id)
        for entry in preserved.values():
            entry["observedByPersonas"] = len(entry["personaIds"])
        return list(preserved.values())

    # Fraction of a finding's content words a persona quote must cover before it is
    # published as evidence for that finding.
    _QUOTE_RELEVANCE = 0.35

    @classmethod
    def _attach_persona_evidence(cls, findings: list[dict[str, Any]], thoughts_by_persona: dict[str, list[dict[str, Any]]],
                                 persona_names: dict[str, str]) -> None:
        """Give every finding the persona reasoning that stands behind it.

        This is what turns a synthesized finding from an assertion into a
        demonstrated one: the reader sees the persona's own words from the run that
        produced it. Stage-1 findings name one persona; synthesized stage-2 findings
        name every persona the aggregation grouped together.

        The quote has to be about the finding. Taking the persona's *last* piece of
        reasoning regardless of subject put one sentence about tab navigation under
        all five findings of a live run, including "Missing input labels" -- which
        reads as evidence and is not. Each candidate quote is scored by how much of
        the finding it actually covers, and a finding the persona never discussed
        gets no quote rather than an unrelated one. On that run the one true pairing
        scored 0.86 and every wrong one 0.29 or less.
        """
        for finding in findings:
            # A finding that arrived with its own quotes keeps them. The
            # broken-promise finding pairs each quote to the exact step that
            # produced it -- the reflection recorded immediately after that
            # action -- and this matches by title similarity across the whole
            # run, which is strictly worse evidence for the same claim.
            #
            # Overwriting it put the persona's *expectation* under a finding as
            # evidence of what went wrong: "Clicking the Monthly toggle button
            # will display the specific monthly cost amounts" quoted as the
            # complaint, when the complaint the run recorded was "monthly cost
            # amounts for the tiers are not shown". A prediction presented as an
            # observation, and the expectation scored better only because the
            # title is made from it.
            if finding.get("personaEvidence"):
                continue
            persona_ids = finding.get("affectedPersonaIds") or (
                [finding["personaId"]] if finding.get("personaId") else [])
            subject = (cls._text_tokens(finding.get("title") or "")
                       | cls._text_tokens(finding.get("summary") or ""))
            evidence = []
            for persona_id in persona_ids:
                reasoning = [item for item in thoughts_by_persona.get(persona_id, []) if item["kind"] == "reasoning"]
                if not reasoning or not subject:
                    continue
                best = max(reasoning, key=lambda item: len(subject & cls._text_tokens(item["text"])))
                if len(subject & cls._text_tokens(best["text"])) / len(subject) < cls._QUOTE_RELEVANCE:
                    continue
                evidence.append({"personaId": persona_id, "personaName": persona_names.get(persona_id, persona_id),
                                 "quote": best["text"], "elapsedMs": best.get("elapsedMs")})
            if evidence:
                finding["personaEvidence"] = evidence

    @staticmethod
    def _flow_label(finding: dict[str, Any]) -> str:
        """Name the part of the product a finding belongs to, as a reviewer would."""
        route = finding.get("route") or finding.get("url")
        if route:
            try:
                from urllib.parse import urlparse
                path = (urlparse(str(route)).path or "/").rstrip("/")
            except ValueError:
                path = ""
            if not path:
                return "Landing page"
            return path.strip("/").replace("-", " ").replace("_", " ").replace("/", " · ").title()
        category = str(finding.get("category") or "usability")
        return category.replace("_", " ").title()

    @staticmethod
    def _flow_groups(findings: list[dict[str, Any]], tasks: list[str]) -> list[dict[str, Any]]:
        """Group findings the way a usability report is read -- by the part of the
        product they belong to -- instead of one flat list, the way a review names
        its sections "Sign up page" or "Landing page".

        Prefers the route the finding was actually observed on, which is the real
        product area; falls back to the category only when a finding has no route
        (a category name like "Ux" is taxonomy, not a place in the product)."""
        groups: dict[str, dict[str, Any]] = {}
        for finding in findings:
            key = JobExecutor._flow_label(finding)
            group = groups.setdefault(key, {"flow": key, "category": finding.get("category"), "findings": []})
            group["findings"].append(finding.get("title"))
        ordered = sorted(groups.values(), key=lambda item: -len(item["findings"]))
        for index, group in enumerate(ordered, start=1):
            group["section"] = f"02.{index}"
            group["findingCount"] = len(group["findings"])
        return ordered

    @classmethod
    def _impact_analysis(cls, findings: list[dict[str, Any]], personas: list[dict[str, Any]]) -> dict[str, Any]:
        """A designer-facing read of the findings: how bad, how widespread, and who
        it hits hardest -- the question "what do I fix first" answered from the run's
        own numbers rather than left as raw deltas in each finding."""
        by_severity: dict[str, int] = {}
        for finding in findings:
            severity = str(finding.get("severity") or "medium")
            by_severity[severity] = by_severity.get(severity, 0) + 1
        ranked = sorted(findings, key=lambda item: (
            -cls._SEVERITY_RANK.get(str(item.get("severity")), 1), -int(item.get("affectedPersonas") or 0)))
        traits: dict[str, int] = {}
        for finding in findings:
            for trait in finding.get("susceptibleTraits") or []:
                traits[trait] = traits.get(trait, 0) + 1
        return {
            "personasTested": len(personas),
            "findingsBySeverity": by_severity,
            "blockingCount": by_severity.get("critical", 0) + by_severity.get("high", 0),
            "priorityOrder": [{"title": item.get("title"), "severity": item.get("severity"),
                               "affectedPersonas": item.get("affectedPersonas"),
                               "category": item.get("category")} for item in ranked[:10]],
            "mostSusceptibleTraits": sorted(traits, key=lambda trait: -traits[trait])[:5],
        }

    @staticmethod
    def _executive_summary(url: str | None, tasks: list[str], personas: list[dict[str, Any]],
                           findings: list[dict[str, Any]], preserve: list[dict[str, Any]],
                           journeys: list[dict[str, Any]] | None = None) -> str:
        """State what was actually found, not what was merely prepared.

        A count is not a summary. "12 usability issues were identified, 3 of them
        high-severity" is true of almost any report and tells a reader nothing
        they can act on -- they still have to read all twelve to learn whether
        the site has a pricing problem or a checkout problem. So the worst
        finding is named, and the two classes that only this pipeline can produce
        are called out by name when they occur, because a reader will not know to
        look for them.
        """
        real = [finding for finding in findings
                if finding.get("title") != "No pain points detected"
                and str(finding.get("severity")) not in JobExecutor._NOT_A_PROBLEM]
        noted = [finding for finding in findings
                 if str(finding.get("severity")) in JobExecutor._NOT_A_PROBLEM]
        blocking = [finding for finding in real
                    if str(finding.get("severity")) in {"critical", "high"}]
        parts = [f"{len(personas)} synthetic user(s) attempted {len(tasks)} task(s) "
                 f"against {url or 'the target site'}."]
        # How far the runs actually got, before any count of what they found. A
        # live report opened "1 synthetic user(s) attempted 2 task(s) ... 10
        # usability issue(s) were identified" over a run that errored after a
        # single action on a 429 from the model endpoint. Every other part of the
        # report was honest about it -- journey_outcome.status said "partial", a
        # limitation named the error -- but the one line most readers read
        # presented a collapsed run as a finished review. A caveat five items into
        # a limitations array is a caveat nobody reads.
        cut_short = [journey for journey in (journeys or []) if journey.get("harnessError")]
        if cut_short:
            steps = sum(1 for journey in cut_short for event in journey.get("timeline") or []
                        if event.get("type") == "persona.expectation")
            parts.append(
                f"{len(cut_short)} of those run(s) stopped early and did not finish the tasks"
                + (f" -- one got {steps} action(s) in" if len(cut_short) == 1 and steps else "")
                + ", so what follows is what was seen before that, not a full review.")
        parts.append(f"{len(real)} usability issue(s) were identified"
                     + (f", {len(blocking)} of them high-severity or blocking." if blocking else "."))

        # The single thing to fix first, named rather than counted.
        worst = (blocking or real)
        if worst:
            parts.append(f"The most serious is: {worst[0].get('title')}.")

        unreadable = [f for f in real if f.get("source") == "perception.notPerceived"]
        missed = [f for f in real if f.get("source") == "perception.missed"]
        if unreadable:
            parts.append(f"{len(unreadable)} element(s) are present in the page but not legible "
                         "once these users' eyesight is applied to what was actually drawn.")
        if missed:
            parts.append(f"{len(missed)} thing(s) a user came for were readable and on screen, "
                         "and were never looked at -- a prominence problem rather than a wording one.")
        if noted:
            # Said, and deliberately not counted: the page is compliant in these
            # places and one unusual profile had trouble, which is worth knowing
            # and is not a defect.
            parts.append(f"{len(noted)} further observation(s) apply to one unusual profile each "
                         "rather than to the site.")
        if preserve:
            parts.append(f"{len(preserve)} design decision(s) are working and should be preserved.")
        return " ".join(parts)

    @staticmethod
    def _journey_run_timeout() -> float:
        """How long to wait for one Journey run before giving up on the socket.

        The old 600s default was below every real measurement taken against this
        stack: live runs of the same two-task journey finished in 855s and 1159s.
        A default that expires mid-run turns a working pipeline into a job that
        fails ten minutes in, so it is set past what runs actually take, and
        JOURNEY_RUN_TIMEOUT still overrides it for slower or faster targets.
        """
        try:
            return float(os.getenv("JOURNEY_RUN_TIMEOUT", "1800"))
        except (TypeError, ValueError):
            return 1800.0

    @staticmethod
    def _journey_artifact_root() -> Path:
        """Where the worker writes runs -- the same resolution the worker itself uses
        (services/journey-worker/node/src/journeytest.js)."""
        return Path(os.getenv("JOURNEY_ARTIFACT_ROOT", "/tmp/aux-journeys"))

    @classmethod
    def _journey_from_disk(cls, run_id: str) -> dict[str, Any] | None:
        """The run's own result file, when the HTTP answer never arrived.

        journeytest-core writes `<root>/<startedAt>-<runId>/run.json` as the run
        ends, so a verdict exists on disk whether or not the client is still
        listening. Both the directory and the file's own `runId` carry that
        timestamp prefix (a live file records "2026-09-10T00-33-40-422Z-live_fw_final"
        for a run submitted as "live_fw_final"), so the id we sent is a suffix of
        the one on disk, never an exact match. Newest first, because a re-run of the
        same id writes a second directory beside the first.
        """
        root = cls._journey_artifact_root()
        try:
            candidates = sorted((path for path in root.glob(f"*{run_id}/run.json")),
                                key=lambda path: path.stat().st_mtime, reverse=True)
        except OSError:
            return None
        for candidate in candidates:
            try:
                result = json.loads(candidate.read_text())
            except (OSError, ValueError):
                continue
            recorded = result.get("runId") if isinstance(result, dict) else None
            if isinstance(recorded, str) and (recorded == run_id or recorded.endswith(f"-{run_id}")):
                return result
        return None

    @staticmethod
    def _usable_journey(journey: dict[str, Any]) -> dict[str, Any]:
        """Keep what a run actually observed, even when the run ended badly.

        A JourneyTest run has three separable outcomes: the browsing itself, the
        director's verdict, and the bookkeeping around both (stopping the video,
        writing the report). Previously any `runStatus == "error"` failed the whole
        job -- so a run that browsed for fourteen minutes, took 37 screenshots and
        recorded a verdict was discarded because `record stop` could not find
        ffmpeg. Two live runs were lost exactly that way: their verdicts were
        already written to run.json while the job reported nothing but the error.

        So the error decides the *framing*, not whether the evidence survives:

        - a verdict, however the run ended, is the run's own answer and is used;
        - no verdict but screenshots on disk still support the vision critique,
          which reads pixels rather than the director's conclusion;
        - neither means nothing was observed, and that is the one case that fails.

        `harnessError` marks a run whose evidence is real but incomplete, so the
        report can say so rather than presenting a truncated run as a whole one.
        """
        error = journey.get("error") or {}
        if not error and journey.get("runStatus") != "error":
            return journey
        message = error.get("message") or "unknown JourneyTest error"
        screenshots = (journey.get("artifacts") or {}).get("screenshots") or []
        if not journey.get("verdict") and not screenshots:
            raise RuntimeError(f"JourneyTest run failed: {message}")
        return {**journey, "harnessError": message}

    # A profile far enough from the population norm that one of them failing to
    # read something is not, on its own, evidence about the site. Roughly the
    # bottom few percent of corrected vision -- not "wears glasses".
    _RARE_ACUITY = 0.45
    _RARE_CONTRAST = 0.35

    @staticmethod
    def _profile_is_a_small_minority(eyes: dict[str, Any]) -> bool:
        """Whether these eyes are unusual enough to need corroborating evidence."""
        try:
            acuity = float(eyes.get("acuity", 1.0))
            contrast = float(eyes.get("contrastSensitivity", 1.0))
        except (TypeError, ValueError):
            return False
        return acuity <= JobExecutor._RARE_ACUITY or contrast <= JobExecutor._RARE_CONTRAST

    @staticmethod
    def _persona_reasoning(journey: dict[str, Any], limit: int = 8) -> list[dict[str, str]]:
        """What the persona said, in their own words, about not getting what they came for.

        A finding is far more use with the reasoning behind it than without, and
        the run already records it: the reflection names the gap between what was
        expected and what arrived.

        Every gap in the run is collected, not the first two. Which of them belongs
        to a given finding is decided against that finding's own subject, once it
        exists (`_relevant_quotes`). Taking the first two put "Clicking 'How it
        works' did not navigate to a detailed service explanation" under a contrast
        finding about the site's logo in a live report -- the same mistake
        `_attach_persona_evidence` already carries a comment about, made again here.

        The persona's name comes along with the quote. Without it the report
        rendered every one of these as being said by nobody: `personaName` was
        never set, and the presentation falls back to "Synthetic user".
        """
        profile = journey.get("simulationProfile") or {}
        name = ((profile.get("persona") or {}).get("name")
                or profile.get("name") or journey.get("profileId")
                or journey.get("testerProfileId") or "Synthetic user")
        quotes: list[dict[str, str]] = []
        for event in journey.get("timeline") or []:
            if event.get("type") != "persona.reflection":
                continue
            data = event.get("data") or {}
            gap = (data.get("gap") or "").strip()
            if gap and data.get("matched") != "yes" and gap not in {item["quote"] for item in quotes}:
                quotes.append({"quote": gap, "personaName": name,
                               "personaId": journey.get("profileId")
                               or journey.get("testerProfileId")})
            if len(quotes) >= limit:
                break
        return quotes

    @classmethod
    def _what_stopped_them(cls, journey: dict[str, Any]) -> str:
        """The thing the run kept doing that never worked, in the run's own terms.

        A failed or blocked criterion arrived with no recommendation at all -- a
        critical finding reading "FIX: None". The run knows exactly what happened
        and nothing read it: a live persona clicked the same pricing toggle three
        separate times expecting a price to appear, was told "Clicking the button
        did not reveal any annual price information" each time, went from calm to
        fed up over twelve actions, and left.

        Returns the action that was tried repeatedly without its expectation being
        met, with the last thing the persona said about it. Empty when the run did
        not repeat itself -- there is no honest single cause to name then, and a
        guess would be worse than the silence it replaces.
        """
        attempts: dict[str, list[str]] = {}
        named: dict[str, str] = {}
        pending: dict[str, Any] | None = None
        expected = ""
        for event in journey.get("timeline") or []:
            kind, data = event.get("type"), event.get("data") or {}
            if kind == "persona.expectation":
                pending = data.get("action") or {}
                expected = str(data.get("expectation") or "")
            elif kind == "persona.reflection" and pending is not None:
                if str(data.get("matched") or "").lower() != "yes":
                    target = str(pending.get("target") or pending.get("content") or "").strip()
                    key = f"{pending.get('type', 'action')} {target}".strip()
                    attempts.setdefault(key, []).append(str(data.get("gap") or "").strip())
                    # "CLICK e17" is the ref the agent used; nobody reading a report
                    # knows what e17 is. The persona named the thing in its own
                    # expectation -- "Clicking the 'Annual - save 17%' button will
                    # reveal..." -- so prefer that label and keep the ref beside it.
                    label = _QUOTED_LABEL.search(expected)
                    if label and key not in named:
                        named[key] = label.group(1).strip()
                pending = None
        if not attempts:
            return ""
        action, gaps = max(attempts.items(), key=lambda item: len(item[1]))
        if len(gaps) < 2:
            return ""
        # The persona's sentences end in a full stop of their own; a quote closed
        # with one and then followed by another reads as a typo.
        said = next((gap for gap in reversed(gaps) if gap), "").rstrip(" .")
        verb, _, ref = action.partition(" ")
        # Whether this was a control, from the verb rather than from whether a
        # target string happens to be present: a SCROLL carries "down" as its
        # target, which is not a thing on the page to go and look at.
        control = verb.upper() in cls._PROMISING_ACTIONS
        what = f'the "{named[action]}" control' if action in named else (ref if control else "")
        attempt = (f"They tried to {verb.lower()} {what} {len(gaps)} times".replace("  ", " ")
                   if control else
                   f"They tried to {verb.lower()} their way to it {len(gaps)} times")
        follow = (" Start there -- that is where this visitor's patience went." if control else
                  " Whatever they were looking for was not where they kept looking for it.")
        return (attempt + " and it never did what they expected"
                + (f': "{said}"' if said else "") + "." + follow)

    # How much of the shorter of {what this finding is about} and {what the persona
    # said} the two must share before the quote is published as evidence for the
    # finding.
    _PERCEPTION_QUOTE_RELEVANCE = 0.2

    @classmethod
    def _relevant_quotes(cls, finding: dict[str, Any]) -> list[dict[str, str]]:
        """The quotes on this finding that are actually about it.

        A finding the persona never mentioned gets no quote rather than an
        unrelated one: an irrelevant quote under a finding does not read as
        "unrelated", it reads as evidence. A live report put "Clicking 'How it
        works' did not navigate to a detailed service explanation" and "No price or
        selection indicator appeared after clicking the annual button" under a
        contrast finding about the site's own logo.

        The subject is the element and the finding's title -- what the finding is
        *about* -- and deliberately not its summary. A perception summary is two
        sentences of measurement vocabulary (contrast ratios, WCAG minima, fixation
        budgets) that no persona ever utters, so including it only inflates the
        denominator: the one true pairing in the live case shared a single word out
        of some forty, scoring 0.025 against a 0.2 bar and being thrown away with
        the wrong ones.

        Containment, not Jaccard, and against the shorter side: "No price was
        visible anywhere." is six words about an element whose name is a
        twelve-word sentence, and asking either to cover most of the other would
        reject a quote that is plainly about it.
        """
        subject = (cls._text_tokens(finding.get("elementName") or "")
                   | cls._text_tokens(finding.get("title") or ""))
        if not subject:
            return []
        kept = []
        for quote in finding.get("personaEvidence") or []:
            words = cls._text_tokens(quote.get("quote") or "")
            if not words:
                continue
            shared = len(subject & words)
            if shared / min(len(subject), len(words)) >= cls._PERCEPTION_QUOTE_RELEVANCE:
                kept.append(quote)
        return kept[:2]

    # How much measured frustration a broken promise has to cost, summed across
    # everyone who hit it, before it is reported as more than a nuisance. Grounded
    # in the run's own affect rather than assigned from a table: what makes a
    # promise that is not kept serious is how much of a visitor's patience it
    # spends, and that is a number these runs already produce.
    _COSTLY_FRUSTRATION = 0.25
    _NOTICEABLE_FRUSTRATION = 0.10
    # The actions where "it promised something" is a sentence about the product.
    _PROMISING_ACTIONS = frozenset({"CLICK", "FILL", "SELECT", "SUBMIT", "TYPE"})

    # A vision finding claiming the page renders itself more than once.
    _CLAIMS_DUPLICATION = re.compile(
        r"\brepeat(?:s|ed|ing)?\b|\bduplicat(?:e|ed|ion)\b|\btwice\b|\bthree times\b|\bmultiple copies\b",
        re.I)
    # A vision finding claiming the page stopped the visitor doing the thing.
    _CLAIMS_BLOCKING = re.compile(
        r"\bprevent(?:s|ing|ed)?\b|\bblocks?\b|\bblocking\b|\bcannot (?:see|find|read)\b"
        r"|\bunable to\b|\bhide(?:s|n)? the actual\b", re.I)
    # A finding claiming something is simply not there.
    _CLAIMS_ABSENCE = re.compile(
        r"\bmissing\b|\bnot (?:present|shown|displayed|visible|listed)\b|\bno (?:price|prices|"
        r"pricing|cost|amount)\b|\bwithout (?:any )?(?:price|pricing|cost)\b|\bdoes not (?:show|"
        r"display|state|list)\b|\bnever (?:shows|displays)\b|\babsent\b|\bfails? to (?:show|"
        r"display)\b", re.I)
    # What this finding says is missing has to be the thing the run can prove it
    # saw. Money is that thing: a price is unambiguous to spot in free text, and
    # both live false findings were about one.
    _CLAIMS_ABSENT_MONEY = re.compile(
        r"\bpric(?:e|es|ing)\b|\bcosts?\b|\bamounts?\b|\bfigures?\b|\brates?\b"
        r"|[£$€]\s*\d", re.I)
    # A sum of money as it appears on a page: a currency mark against a number.
    _A_PRICE = re.compile(r"[£$€]\s?\d[\d,.]*", re.U)

    @classmethod
    def _contradicted_by_the_run(cls, finding: dict[str, Any],
                                 journeys: list[dict[str, Any]]) -> str:
        """What this run measured that this finding says did not happen.

        The vision model reads screenshots and is a confident reader. A live report
        led with "Repeated page layout rendering bug", severity critical -- "the
        entire header and hero section repeats three times vertically ... looks
        highly broken" -- and second with "Pricing cards are cut off ... preventing
        users from seeing the actual price", severity high. The capture was
        correct, every section rendered, and the same run's verdict reads "The page
        does state the pricing clearly. £200 per user per year for teams (or £100
        per user per year for individuals)".

        Two of its claims are checkable against what the run itself recorded, and
        where they disagree the measurement wins -- not because a vision model is
        worthless, but because a confident, specific, wrong claim at critical
        severity is the most damaging thing this report can carry.
        """
        text = f"{finding.get('title', '')} {finding.get('summary', '')}"
        # Nothing repeats if the element walk saw each thing once. Every element on
        # screen is listed by selector on every capture; a hero rendered three
        # times would be three entries.
        if cls._CLAIMS_DUPLICATION.search(text):
            captures = [event for journey in journeys
                        for event in journey.get("timeline") or []
                        if event.get("type") == "persona.perception"]
            seen = [(event.get("data") or {}).get("legible") or [] for event in captures]
            if seen and all(len(items) == len(set(items)) for items in seen if items):
                return ("the element walk recorded every element exactly once on all "
                        f"{len(captures)} capture(s) of this run, so nothing on the page was "
                        "rendered more than once")
        # Nothing is missing that this person read off the page. The persona
        # commits to what it can see before every action, and the verdict quotes
        # what it found; either is the run's own testimony that the thing was
        # there. Cycle 14 shipped "Missing pricing details on pricing cards" at
        # critical and "Promised more than it did: Monthly" at high, in a run
        # whose verdict reads "it lists two options -- £200 per user per year
        # ... and £100 per user per year". A report that contradicts itself in
        # two directions is worth less than one that says nothing.
        if cls._CLAIMS_ABSENCE.search(text) and cls._CLAIMS_ABSENT_MONEY.search(text):
            quoted = cls._prices_the_run_read(journeys)
            if quoted:
                shown = ", ".join(sorted(quoted)[:3])
                return ("this run read a price off the page with the persona's own eyes "
                        f"({shown}), so the page does state a cost")
        # Nothing was blocked if the run finished.
        if cls._CLAIMS_BLOCKING.search(text):
            finished = [journey for journey in journeys
                        if any(item.get("id") == "tasks-completed" and item.get("result") == "met"
                               for item in (journey.get("verdict") or {}).get("criteria", []))]
            if finished:
                said = str((finished[0].get("verdict") or {}).get("summary") or "").strip()
                return ("the run completed the tasks it came to do"
                        + (f' -- "{said[:180]}"' if said else ""))
        return ""

    @classmethod
    def _prices_the_run_read(cls, journeys: list[dict[str, Any]]) -> set[str]:
        """Every sum of money this run recorded as visible to the persona.

        Drawn only from what the run says the persona could see -- the `visible`
        line it commits to before each action, and the verdict it reached -- never
        from the page source or the accessibility tree. The claim being tested is
        "a visitor cannot see a price", so the rebuttal has to come from a visitor
        seeing one.
        """
        said: set[str] = set()
        for journey in journeys:
            for event in journey.get("timeline") or []:
                if event.get("type") != "persona.expectation":
                    continue
                said.update(cls._A_PRICE.findall(str((event.get("data") or {}).get("visible") or "")))
            said.update(cls._A_PRICE.findall(
                str((journey.get("verdict") or {}).get("summary") or "")))
        return said

    @staticmethod
    def _what_the_page_actually_cost(journeys: list[dict[str, Any]]) -> dict[str, float] | None:
        """The worst this page made anyone feel, measured rather than guessed.

        The behaviour controller records frustration and confusion after every
        step of every run. The peak across all of them is the most the page cost
        anybody who visited it -- and no single finding can have cost more than
        that, because that is the whole of it.

        None when no run recorded any affect: there is then nothing to cap
        against, and a ceiling nobody measured is not a ceiling.
        """
        peaks = [(state.get("frustration"), state.get("confusion"))
                 for journey in journeys
                 for event in journey.get("timeline") or []
                 if event.get("type") == "persona.affect"
                 for state in [(event.get("data") or {}).get("state") or {}]]
        numbers = [(f, c) for f, c in peaks
                   if isinstance(f, (int, float)) and isinstance(c, (int, float))]
        if not numbers:
            return None
        return {"frustration": max(f for f, _ in numbers), "confusion": max(c for _, c in numbers)}

    @classmethod
    def _cap_claimed_impact(cls, findings: list[dict[str, Any]],
                            journeys: list[dict[str, Any]]) -> list[str]:
        """Hold the vision model's guessed distress to what the run measured.

        The reviewer estimates frustration, confusion and trust erosion from a
        single screenshot, and those numbers reach the report as a finding's
        stated impact. Measured against the runs that produced them they are not
        close: a run whose peak frustration was 0.29, and which passed, carried
        three findings claiming 0.90, 0.90 and 0.60. A run that peaked at 0.20
        carried a finding claiming 0.90 -- and that finding was the one the
        element walk disproved.

        Capped rather than replaced. The model's relative ordering among findings
        may well carry signal, and a finding about something the persona never
        reached has no measured counterpart of its own. What it may not do is
        claim the page cost someone more than the page was ever measured to cost
        anyone.
        """
        ceiling = cls._what_the_page_actually_cost(journeys)
        notes = []
        if not ceiling:
            cls._state_impact(findings)
            return notes
        for finding in findings:
            claimed = finding.get("claimedImpact") or {}
            if not claimed:
                continue
            over = {name: (claimed[name], ceiling[name]) for name in ("frustration", "confusion")
                    if isinstance(claimed.get(name), (int, float)) and claimed[name] > ceiling[name]}
            if not over:
                continue
            for name, (_, limit) in over.items():
                claimed[name] = limit
            worst = max(over.items(), key=lambda item: item[1][0] - item[1][1])
            notes.append(
                f"{finding.get('title')!r} estimated {worst[0]} at {worst[1][0]:.2f} from a single "
                f"screenshot; the runs measured at most {worst[1][1]:.2f} across every step, so the "
                f"estimate is reported at the measured ceiling.")
        cls._state_impact(findings)
        return notes

    @staticmethod
    def _state_impact(findings: list[dict[str, Any]]) -> None:
        """Write each finding's evidence line from its numbers, after any capping.

        Rendered here rather than at synthesis so the sentence cannot disagree
        with the figures it describes -- which it would have, the moment a capped
        number sat behind prose written before the cap.
        """
        for finding in findings:
            impact = finding.get("claimedImpact")
            if not impact:
                continue
            finding["evidence"] = (
                f"synthesized from {finding.get('observations', 1)} observation(s) across "
                f"{finding.get('affectedPersonas', 1)} persona(s); estimated impact: "
                f"frustration {impact['frustration']:.2f}, confusion {impact['confusion']:.2f}, "
                f"trust erosion {impact['trust']:.2f}")

    @classmethod
    def _temper_contradicted_findings(cls, findings: list[dict[str, Any]],
                                      journeys: list[dict[str, Any]]) -> list[str]:
        """Cap a contradicted finding's severity and say so, in place.

        Kept rather than dropped: the visual observation behind it may be worth a
        look, and deleting a signal because one of its claims overreached is its own
        kind of dishonesty. What it may not do is lead the report.
        """
        notes = []
        for finding in findings:
            if finding.get("source") != "eyeson-vision-synthesis":
                continue
            against = cls._contradicted_by_the_run(finding, journeys)
            if not against:
                continue
            was = finding.get("severity")
            if was in ("critical", "high"):
                finding["severity"] = "medium"
            finding["summary"] = (f"{finding.get('summary', '').rstrip()} Reported by the vision "
                                  f"critique and not supported by this run: {against}.")
            finding["contradictedByRun"] = against
            notes.append(f"{finding.get('title')!r} was reported as {was} by the vision critique "
                         f"and is carried at {finding['severity']} instead, because {against}.")
        return notes

    @classmethod
    def _pain_points_from_expectations(cls, journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Things the page looked like it would do and then did not.

        The persona director commits to an expectation before every action, and
        then compares it against what arrived. A reflection that comes back
        `matched: "no"` is a first-hand, falsifiable observation of a control that
        promised something and did not deliver it -- the most common real usability
        defect there is, and one no check against the DOM can find, because the
        DOM has no opinion about what a link looked like it would do.

        Nothing read them. Three consecutive live runs against the same page each
        recorded that clicking "How it works" did not navigate anywhere and that
        the "Annual - save 17%" toggle showed no price, one of them abandoning the
        journey over it -- and all three reports said nothing about either. One
        said "No pain points detected" over a run that ended at 0.49 frustration
        and 0.52 confusion.

        Only a clear miss counts. `matched: "partly"` is the persona hedging, and
        a report built on hedges is a report that finds something everywhere.
        """
        groups: dict[str, dict[str, Any]] = {}
        for journey in journeys:
            run_id = journey.get("runId")
            persona_id = journey.get("profileId") or journey.get("testerProfileId")
            profile = journey.get("simulationProfile") or {}
            persona_name = ((profile.get("persona") or {}).get("name")
                            or profile.get("name") or persona_id or "Synthetic user")
            pending: dict[str, Any] | None = None
            expectation = ""
            unmet: dict[str, Any] | None = None
            previous = 0.0
            for event in journey.get("timeline") or []:
                kind, data = event.get("type"), event.get("data") or {}
                if kind == "persona.expectation":
                    pending, expectation = data.get("action") or {}, str(data.get("expectation") or "")
                    unmet = None
                elif kind == "persona.reflection" and pending is not None:
                    # A promise is made by a control. A READ that returns something
                    # other than expected is about what the persona could take in,
                    # which is the perception findings' subject and measured there
                    # properly; a SCROLL that does not reveal what was hoped for is
                    # a guess about a page, not a promise it made. Reporting those
                    # here would file "the paragraph at 321,417 promised more than
                    # it did", which is not a sentence about the product.
                    if (str(data.get("matched") or "").lower() == "no"
                            and str(pending.get("type") or "").upper() in cls._PROMISING_ACTIONS):
                        unmet = {"action": pending, "expectation": expectation,
                                 "gap": str(data.get("gap") or "").strip()}
                    pending = None
                elif kind == "persona.affect":
                    # The affect event that follows a reflection is what that
                    # reflection cost. Read here rather than assumed, because a
                    # miss a persona shrugs off and a miss that ends the journey
                    # are not the same finding.
                    frustration = float((data.get("state") or {}).get("frustration") or 0.0)
                    if unmet is not None:
                        label = cls._promise_label(unmet["expectation"], unmet["action"])
                        group = groups.setdefault(label, {
                            "label": label, "hits": 0, "cost": 0.0, "personas": [], "names": [],
                            "runs": [], "gaps": [], "expectations": [], "actions": []})
                        group["hits"] += 1
                        group["cost"] += max(0.0, frustration - previous)
                        if persona_id and persona_id not in group["personas"]:
                            group["personas"].append(persona_id)
                            group["names"].append(persona_name)
                        if run_id and run_id not in group["runs"]:
                            group["runs"].append(run_id)
                        if unmet["gap"]:
                            # Who said it travels with it. Pairing two parallel
                            # lists by position put one persona's sentence under
                            # another's name as soon as they contributed unequal
                            # numbers of them.
                            group["gaps"].append({"quote": unmet["gap"], "personaId": persona_id,
                                                  "personaName": persona_name})
                        if unmet["expectation"]:
                            group["expectations"].append(unmet["expectation"])
                        group["actions"].append(unmet["action"])
                        unmet = None
                    previous = frustration
        merged = cls._merge_promise_labels(groups)
        return [cls._broken_promise_finding(group) for group in
                sorted(merged, key=lambda item: -item["cost"])]

    @staticmethod
    def _merge_promise_labels(groups: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Fold labels that name the same control into one finding.

        One persona quotes "Annual - save 17%" and the next writes "the Annual
        button", and the page has one toggle. Left split, the report says a
        control was hit once when it was hit twice, and prices each half at half
        the patience it actually cost -- the exact thing severity is read from.

        Containment on whole words, keeping the longer name: the specific label is
        the one a reader can find on the page. Not fuzzy similarity -- "Annual" and
        "Monthly" are close by most string measures and are two different controls.
        """
        remaining = sorted(groups.values(), key=lambda item: -len(item["label"]))
        kept: list[dict[str, Any]] = []
        for group in remaining:
            words = group["label"].lower().split()
            host = next((item for item in kept
                         if words and item["label"].lower().split()[:len(words)] == words), None)
            if host is None:
                kept.append(group)
                continue
            host["hits"] += group["hits"]
            host["cost"] += group["cost"]
            for field in ("gaps", "expectations", "actions"):
                host[field].extend(group[field])
            for persona, name in zip(group["personas"], group["names"]):
                if persona not in host["personas"]:
                    host["personas"].append(persona)
                    host["names"].append(name)
            for run in group["runs"]:
                if run not in host["runs"]:
                    host["runs"].append(run)
        return kept

    @staticmethod
    def _promise_label(expectation: str, action: dict[str, Any]) -> str:
        """What the persona thought it was interacting with, named the way it named
        it.

        A ref groups nothing and means nothing: the same control is e6 in one run
        and e17 in another, and no reader knows what either is. Worse, a ref that
        leaks through splits one control into two findings -- a live replay
        produced both "Annual - save 17%" (high) and "e17" (low) for the same
        toggle, because one run happened to quote the label and the other wrote
        "the Annual button" without quotes.

        So: the quoted label first, then the phrase the sentence names as the
        thing being clicked, and the ref only when the persona said nothing useful
        at all.
        """
        quoted = _QUOTED_LABEL.search(expectation or "")
        if quoted:
            return quoted.group(1).strip()
        named = _NAMED_CONTROL.search(expectation or "")
        if named:
            return named.group(1).strip()
        target = str((action or {}).get("target") or (action or {}).get("content") or "").strip()
        return target or str((action or {}).get("type") or "the page").lower()

    @classmethod
    def _broken_promise_finding(cls, group: dict[str, Any]) -> dict[str, Any]:
        """One promise the page did not keep, priced by what it cost."""
        label, hits, cost = group["label"], group["hits"], group["cost"]
        personas = group["personas"]
        # Severity from the measured cost and from how many different people hit
        # it, not from which bucket the finding came out of. Several people losing
        # patience over one control is the page; one person losing a little is a
        # nuisance worth recording and not worth leading with.
        if len(personas) > 1 or cost >= cls._COSTLY_FRUSTRATION:
            severity = "high"
        elif hits > 1 or cost >= cls._NOTICEABLE_FRUSTRATION:
            severity = "medium"
        else:
            severity = "low"
        expected = group["expectations"][0] if group["expectations"] else ""
        happened = group["gaps"][-1]["quote"] if group["gaps"] else ""
        again = (f" {len(personas)} different personas expected the same thing of it."
                 if len(personas) > 1 else
                 f" They tried it {hits} times." if hits > 1 else "")
        return {
            "severity": severity, "category": "expectation",
            "title": f"Promised more than it did: {label}",
            # Both quotes carry the persona's own full stop; adding another reads
            # as a typo.
            "summary": (f"Before touching it they said what they expected: "
                        f"\"{expected.rstrip(' .')}.\" What arrived was not that -- "
                        f"\"{happened.rstrip(' .')}.\"{again} It cost "
                        f"{cost:.2f} of this visitor's patience on a 0-1 scale, measured across the "
                        f"run rather than assumed."),
            "recommendation": (f"Either make {label} do what it reads as doing, or stop it reading "
                               f"that way. This is not a wording problem in the copy around it: the "
                               f"visitor said out loud what they expected before they touched it, "
                               f"and the control itself is what set that expectation."),
            "evidence": (f"{hits} unmet expectation(s) across {len(group['runs']) or 1} run(s) and "
                         f"{len(personas) or 1} persona(s), costing {cost:.2f} frustration"),
            "evidenceScreenshot": None, "evidenceIsAsTheySawIt": False,
            "elementName": label, "observation": happened,
            "personaEvidence": group["gaps"][:2],
            "affectedPersonaIds": personas, "affectedPersonas": len(personas),
            "source": "persona.expectation",
            "runId": (group["runs"] or [None])[0], "personaId": (personas or [None])[0],
        }

    @classmethod
    def _pain_points_from_perception(cls, journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Findings from what the personas' eyes actually resolved on the page.

        Two classes exist nowhere else in the report, because no check against the
        DOM can produce either. A run records them on every step as
        `persona.perception` and nothing read them, so the pipeline measured two
        whole classes of defect and then said nothing about them.

          notPerceived   In the accessibility tree, and nothing legible where it
                         lives once this person's optics are applied to the
                         capture. Present but not perceivable.

          missedWhatTheyCameFor
                         Legible, on screen, and never looked at -- the answer to
                         "why did they not click the thing that was right there".

        What decides whether either is reported, and how, is not the persona.
        Filing every unreadable element as a high-severity accessibility defect
        would mean a run that happened to include one very short-sighted profile
        turned a compliant page into a failing one, and a reader would rightly
        stop believing the report. So three things are separated:

          * The **rendered contrast ratio**, measured on the page as drawn. This is
            a fact about the site, true for every visitor, and it is what makes a
            finding an accessibility defect -- cited against the WCAG threshold
            that applies, whatever the run's personas happened to be.
          * **Consistency** across personas. The same element missed by several
            different profiles is about the page; missed by one is about that one.
          * **How unusual the profile is.** An element that clears WCAG and was
            missed only by a profile in the bottom few percent of corrected vision
            is reported as what it is -- something that profile could not use -- and
            kept out of the numbered problems, because the page is objectively fine
            and one rare simulated visitor is not grounds to say otherwise.

        Grouped by element across every run, not per step and not per persona: the
        same low-contrast caption is unreadable on every step of every visit, and
        forty identical findings would bury the rest of the report.
        """
        groups: dict[tuple, dict[str, Any]] = {}
        # Every element that resolved on any capture of any run. A heading is not
        # drawn black on one step and invisible on the next: when the same element
        # reads legible once and blank once, the blank capture caught it mid-render,
        # and the one that found text is the one to believe. A live report published
        # "Fails WCAG AA contrast: 'Individual' -- 1.05:1, high" against a
        # pricing-card heading that is plainly dark, from a capture taken while the
        # card was still fading in.
        ever_legible = {selector
                        for journey in journeys
                        for event in journey.get("timeline") or []
                        if event.get("type") == "persona.perception"
                        for selector in ((event.get("data") or {}).get("legible") or [])}
        for journey in journeys:
            run_id = journey.get("runId")
            persona_id = journey.get("profileId") or journey.get("testerProfileId")
            reasoning = cls._persona_reasoning(journey)
            for event in journey.get("timeline") or []:
                if event.get("type") != "persona.perception":
                    continue
                data = event.get("data") or {}
                eyes = data.get("eyes") or {}
                scan = data.get("scan") or {}
                seen_image = data.get("seenImage")
                for kind, items in (("notPerceived", data.get("notPerceived") or []),
                                    ("missed", data.get("missedWhatTheyCameFor") or [])):
                    for item in items:
                        if kind == "notPerceived" and item.get("selector") in ever_legible:
                            continue
                        key = (kind, item.get("selector"))
                        group = groups.setdefault(key, {
                            "kind": kind, "item": item, "steps": 0, "personas": [], "eyes": {},
                            "scan": scan, "runIds": [], "reasoning": [], "seenImage": None,
                            "contrast": item.get("contrast") or {},
                        })
                        group["steps"] += 1
                        group["item"] = item
                        if persona_id and persona_id not in group["personas"]:
                            group["personas"].append(persona_id)
                            group["eyes"][persona_id] = eyes
                            group["reasoning"].extend(reasoning)
                        if run_id and run_id not in group["runIds"]:
                            group["runIds"].append(run_id)
                        group["seenImage"] = group["seenImage"] or seen_image
                        group["contrast"] = group["contrast"] or item.get("contrast") or {}

        findings: list[dict[str, Any]] = []
        for group in groups.values():
            finding = (cls._unreadable_finding(group) if group["kind"] == "notPerceived"
                       else cls._never_looked_at_finding(group))
            if not finding:
                continue
            # Which of the run's gaps belongs under this finding can only be
            # decided once the finding exists and has a subject. Done here rather
            # than in either builder, so one rule covers both and neither can drift.
            finding["personaEvidence"] = cls._relevant_quotes(finding)
            findings.append(finding)
        return cls._fold_undrawn(findings)

    # How many separate "declared but not drawn" elements a report will name before
    # it says the thing they have in common instead.
    _UNDRAWN_WORTH_NAMING = 3

    @classmethod
    def _fold_undrawn(cls, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """A page still settling is one observation, not one per element.

        A live run produced twelve "Declared but not drawn" entries -- the entire
        navigation bar, one at a time -- from a single capture taken mid-render.
        Each was individually correct and together they were noise that buried the
        three findings a reader needed. Twelve elements blank on one capture is a
        fact about the capture; twelve facts about twelve elements is what it looks
        like when nobody says so.

        A couple of them stay as they are: two or three genuinely undrawn elements
        are worth naming individually, and that is the case this finding was
        written for.
        """
        undrawn = [item for item in findings if item.get("source") == "perception.notDrawn"]
        if len(undrawn) <= cls._UNDRAWN_WORTH_NAMING:
            return findings
        rest = [item for item in findings if item.get("source") != "perception.notDrawn"]
        names = [str(item.get("elementName") or "").strip() for item in undrawn]
        shown = ", ".join(f'"{name}"' for name in names[:4] if name)
        lead = max(undrawn, key=lambda item: len(item.get("personaEvidence") or []))
        return rest + [{**lead,
            "title": f"{len(undrawn)} elements were declared and not drawn",
            "summary": (f"The page's accessibility tree placed {len(undrawn)} elements on screen "
                        f"and nothing was painted at any of them -- among others {shown}. That many "
                        f"at once is a statement about the capture rather than about the elements: "
                        f"almost certainly a page still animating in when it was photographed. It is "
                        f"reported as one observation because it is one event."),
            "recommendation": ("Nothing here needs fixing if the page animates its content in. If it "
                               "does not, the page is announcing a screenful of text to assistive "
                               "technology that a sighted visitor never sees."),
            "evidence": f"{len(undrawn)} regions the tree says hold something, all with no ink",
            "elementName": "", "elementBox": None,
            "affectedPersonaIds": sorted({persona for item in undrawn
                                          for persona in (item.get("affectedPersonaIds") or [])}),
        }]

    @staticmethod
    def _element_phrase(item: dict[str, Any]) -> str:
        name = (item.get("name") or "").strip()
        if name:
            return f'"{name[:70]}"'
        box = item.get("box") or {}
        return f"the {item.get('role') or 'element'} at {int(box.get('x', 0))},{int(box.get('y', 0))}"

    @classmethod
    def _unreadable_finding(cls, group: dict[str, Any]) -> dict[str, Any] | None:
        """An element nobody could read, classified by what actually justifies it."""
        item, contrast = group["item"], group["contrast"] or {}
        what = cls._element_phrase(item)
        personas = group["personas"]
        ratio, required = contrast.get("ratio"), contrast.get("required")
        fails_wcag = contrast.get("passes") is False
        rare_only = (len(personas) <= 1
                     and all(cls._profile_is_a_small_minority(eyes)
                             for eyes in group["eyes"].values() or [{}]))

        where = (f" Seen by {len(personas)} of the personas that visited."
                 if len(personas) > 1 else "")
        measured = (f" Its rendered contrast is {ratio}:1 against a WCAG AA minimum of "
                    f"{required}:1, measured on the page as drawn"
                    f" ({contrast.get('measured')})." if ratio else "")

        if item.get("nothingDrawn"):
            # The DOM says there is text here and the capture has no ink in it at
            # all. That is the two sources disagreeing about what exists, and it is
            # a different claim from "this text is hard to read" -- reporting it as
            # a measured contrast ratio states a number about pixels that are not
            # there. A live run filed "Fails WCAG AA contrast: 'Sourcing' --
            # 1.01:1" against a 486x21 region that was blank page below a chat
            # bubble, part of the site's animated mock-up conversation that had not
            # painted yet; the same element was reported 200px higher one step
            # later, which is what an animation looks like from here.
            #
            # Worth saying, because text a page declares and never draws is a real
            # thing to check -- and worth saying quietly, because the likeliest
            # explanation is a capture taken mid-animation rather than a defect.
            return {
                "severity": "info", "category": "profile-specific",
                "title": f"Declared but not drawn: {what}",
                "summary": (f"The page's accessibility tree places {what} at this position and nothing "
                            f"was painted there -- no ink at all, not faint ink. The likeliest "
                            f"explanation is a capture taken while the element was still animating "
                            f"in; the alternative is text the page declares and never renders. "
                            f"No contrast claim is made either way, because there are no pixels to "
                            f"measure.{where}"),
                "recommendation": ("Check this element renders on a settled page. If it is part of an "
                                   "animation, nothing is wrong; if it is not, the page is announcing "
                                   "text to assistive technology that a sighted visitor never sees."),
                "evidence": (f"no ink in a {int((item.get('box') or {}).get('width', 0))}x"
                             f"{int((item.get('box') or {}).get('height', 0))} region the tree says "
                             f"holds text, on {group['steps']} step(s)"),
                "evidenceScreenshot": group["seenImage"],
                "evidenceIsAsTheySawIt": bool(group["seenImage"]),
                "elementBox": item.get("box"), "elementName": item.get("name") or "",
                "contrastRatio": None, "wcagRequired": None, "wcagPasses": None,
                "observation": item.get("reason") or "",
                "personaEvidence": group["reasoning"],
                "affectedPersonaIds": personas, "affectedPersonas": len(personas),
                "source": "perception.notDrawn",
                "runId": (group["runIds"] or [None])[0], "personaId": (personas or [None])[0],
            }

        if fails_wcag:
            # A fact about the site rather than about whoever happened to look, so
            # it stands on its own however rare the profile that surfaced it.
            severity, category = "high", "accessibility"
            title = f"Fails WCAG AA contrast: {what}"
            summary = (f"{what} does not meet the contrast the guidelines require.{measured}"
                       f" A persona could not read it at all after their own eyesight was applied "
                       f"to the capture: {item.get('reason') or 'nothing stands out from its background'}."
                       f"{where}")
            # The arithmetic first, when the measurement supports it: a reader can
            # act on "the darker side has to reach 0.1833" and cannot act on "raise
            # the contrast", which only repeats the minimum the summary just gave.
            # The warning about CSS stays either way -- it is the part a developer
            # is most likely to get wrong, and it is true of every one of these.
            recommendation = " ".join(filter(None, [
                contrast_fix(contrast) or f"Raise the contrast to at least {required}:1.",
                "This is measured on what the browser actually drew, so checking the declared CSS "
                "colours is not enough -- an overlay, a gradient or an image behind the text will "
                "not show up there.",
            ]))
        elif len(personas) > 1:
            # The page clears the guideline and several different people still could
            # not read it, which is worth saying and is not a compliance claim.
            severity, category = "medium", "legibility"
            title = f"Hard to read for several personas: {what}"
            summary = (f"{what} clears the contrast guidelines.{measured} And "
                       f"{len(personas)} different personas still could not resolve it: "
                       f"{item.get('reason') or 'nothing stands out from its background'}. "
                       "Consistent across profiles, so it is about the element rather than about "
                       "one visitor.")
            recommendation = ("Meeting the minimum is not the same as being easy to read. Increase the "
                              "size or the weight, or give it more contrast than the guideline floor.")
        elif rare_only:
            # The honest version of a finding that cannot carry more weight than
            # this: kept out of the numbered problems, and still said.
            eyes = next(iter(group["eyes"].values()), {})
            severity, category = "info", "profile-specific"
            title = f"Unreadable for one low-vision profile only: {what}"
            summary = (f"{what} meets the contrast guidelines.{measured} One persona "
                       f"could not read it -- acuity {eyes.get('acuity')}, contrast sensitivity "
                       f"{eyes.get('contrastSensitivity')}, a profile in the bottom few percent of "
                       "corrected vision. No other persona had trouble with it. This is reported as "
                       "what it is rather than as a defect: the page is compliant here, and one rare "
                       "simulated visitor is not evidence that it is not.")
            recommendation = ("No change is required for compliance. If this audience matters to you, "
                              "the element would need to go well beyond the minimum.")
        else:
            severity, category = "low", "legibility"
            title = f"One persona could not read: {what}"
            summary = (f"{what} meets the contrast guidelines.{measured} One persona "
                       f"still could not resolve it: {item.get('reason') or 'it does not stand out'}. "
                       "Only one, so treat it as a hint rather than a finding.")
            recommendation = "Worth a look if it is important; not yet evidence of a problem."

        return {
            "severity": severity, "category": category, "title": title, "summary": summary,
            "recommendation": recommendation,
            "evidence": (f"contrast {ratio}:1 (needs {required}:1); internal "
                         f"{item.get('internalContrast')}, edge {item.get('edgeContrast')}, "
                         f"seen on {group['steps']} step(s) by {len(personas) or 1} persona(s)"),
            # The page as they saw it, not a clean capture: a clean one beside
            # "they could not read this" invites the reader to disagree, correctly.
            "evidenceScreenshot": group["seenImage"],
            "evidenceIsAsTheySawIt": bool(group["seenImage"]),
            "elementBox": item.get("box"),
            "contrastRatio": ratio, "wcagRequired": required, "wcagPasses": contrast.get("passes"),
            "observation": item.get("reason") or "",
            "personaEvidence": group["reasoning"],
            "elementName": item.get("name") or "",
            "affectedPersonaIds": personas, "affectedPersonas": len(personas),
            "source": "perception.notPerceived",
            "runId": (group["runIds"] or [None])[0], "personaId": (personas or [None])[0],
        }

    @classmethod
    def _never_looked_at_finding(cls, group: dict[str, Any]) -> dict[str, Any]:
        """The thing they came for, readable, on screen, and never looked at."""
        item, scan = group["item"], group["scan"] or {}
        what = cls._element_phrase(item)
        personas = group["personas"]
        together = (f" {len(personas)} different personas missed it, so it is the page rather than "
                    "one visitor." if len(personas) > 1 else "")
        return {
            # Several people coming for a thing and not seeing it is worse than one.
            "severity": "high" if len(personas) > 1 else "medium",
            "category": "findability",
            "title": f"On screen and never looked at: {what}",
            "summary": (f"{what} is what the persona came for, it was legible, and it was in the "
                        f"viewport -- and they never looked at it. They scan "
                        f"{scan.get('pattern') or 'the page'} with a budget of "
                        f"{scan.get('fixationBudget')} fixations: "
                        + "; ".join(scan.get("why") or []) + f".{together}"),
            "recommendation": ("Put it where this scan pattern actually goes, or make it compete: this "
                               "is a prominence problem, not a wording one. The element is present and "
                               "readable, so adding copy about it elsewhere will not help."),
            "evidence": (f"goal match {item.get('goalAffinity')}, never fixated across "
                         f"{group['steps']} step(s) and {len(personas) or 1} persona(s)"),
            "evidenceScreenshot": None, "evidenceIsAsTheySawIt": False,
            "elementBox": item.get("box"), "observation": "",
            "personaEvidence": group["reasoning"],
            "elementName": item.get("name") or "",
            "affectedPersonaIds": personas, "affectedPersonas": len(personas),
            "source": "perception.missed",
            "runId": (group["runIds"] or [None])[0], "personaId": (personas or [None])[0],
        }

    @staticmethod
    def _pain_points_from_journeys(journeys: list[dict[str, Any]], job_id: str = "") -> list[dict[str, Any]]:
        """Derive report findings from JourneyTest's own AgentVerdict for each real run
        (blockers, uxFindings, suggestedImprovements, and failed/blocked pass criteria) --
        this is the browser-runtime's authoritative, evidence-grounded verdict (spec.md
        section 3.1: JourneyTest "must own" task completion verdict), not a fixed
        placeholder. Falls back to a per-task inferred list only when there is no
        JourneyTest run to draw from (see the caller)."""
        findings: list[dict[str, Any]] = []
        for journey in journeys:
            run_id, persona_id = journey.get("runId"), journey.get("profileId") or journey.get("testerProfileId")
            verdict = journey.get("verdict") or {}
            for bucket, fallback_severity in (("blockers", "critical"), ("uxFindings", "medium"), ("suggestedImprovements", "low")):
                for item in verdict.get(bucket, []):
                    # `uxFindings` is a mixed bucket: praise the agent wrote there is
                    # a design decision to preserve, not a usability issue. It is
                    # picked up by _praise_from_verdicts() instead of being numbered
                    # among the problems (a live run filed "Clear value proposition"
                    # and "Prominent sign-up entry point" as issues before this).
                    if bucket == "uxFindings" and _reads_as_praise(item.get("title"), item.get("description")):
                        continue
                    findings.append({
                        "severity": _JOURNEYTEST_SEVERITY_MAP.get(item.get("severity"), fallback_severity),
                        "category": item.get("category"),
                        "title": item.get("title") or f"{bucket} finding",
                        "summary": item.get("description") or "",
                        "recommendation": item.get("recommendation"),
                        "evidence": _evidence_reference_summary(item.get("evidence"), job_id),
                        # The screenshot JourneyTest itself cited for this finding --
                        # the honest image to show beside it on a slide.
                        "evidenceScreenshot": (item.get("evidence") or {}).get("screenshot"),
                        "observation": (item.get("evidence") or {}).get("observation"),
                        "source": bucket, "runId": run_id, "personaId": persona_id,
                    })
            for criterion in verdict.get("criteria", []):
                result, criterion_id = criterion.get("result"), criterion.get("id")
                # journeyContract() (services/journey-worker/node/src/journeytest.js)
                # always emits exactly one pass criterion ("tasks-completed": bad
                # when not-met/blocked) and one fail criterion ("tasks-blocked": bad
                # when *met*, i.e. the failure condition actually occurred -- for a
                # fail criterion, "not-met" is the GOOD outcome and must not be
                # reported as a pain point.
                # "blocked" (the run couldn't even assess the criterion) is bad
                # regardless of criterion polarity; only "met" vs. "not-met" flip
                # between pass and fail criteria.
                if criterion_id in _FAIL_CRITERION_IDS:
                    is_pain_point = result in ("met", "blocked")
                else:
                    is_pain_point = result in ("not-met", "blocked")
                if not is_pain_point:
                    continue
                findings.append({
                    "severity": "critical" if result == "blocked" or criterion_id in _FAIL_CRITERION_IDS else "high",
                    "category": "blocker" if result == "blocked" or criterion_id in _FAIL_CRITERION_IDS else "ux",
                    # "Pass criterion not-met: tasks-completed" is a machine label.
                    # A usability report states what happened to the user.
                    "title": _CRITERION_TITLES.get((criterion_id, result))
                             or f"Criterion {result}: {criterion_id}",
                    "summary": criterion.get("explanation") or "",
                    # A critical finding with no fix at all is a finding a reader
                    # cannot act on. The run's own record says where to look: the
                    # thing they kept trying that never answered.
                    "recommendation": (
                        stopped_them
                        if (stopped_them := JobExecutor._what_stopped_them(journey)) else
                        "Follow this run's timeline back from the last action that did what the "
                        "persona expected; the steps after it are where the journey came apart."),
                    "evidence": _evidence_reference_summary(criterion.get("evidence"), job_id),
                    "evidenceScreenshot": (criterion.get("evidence") or {}).get("screenshot"),
                    "observation": (criterion.get("evidence") or {}).get("observation"),
                    "criterionId": criterion_id, "criterionResult": result,
                    "source": "criteria", "runId": run_id, "personaId": persona_id,
                })
        return findings

    # A finding that quotes on-page text is making a checkable claim, and a vision
    # model will occasionally invent one: a live run reported "Leftover debug text
    # 'navbar.' visible on page" when that string only ever occurs mid-sentence in
    # real copy ("...in the sidebar or navbar. You will be redirected..."). The
    # snapshots journeytest-core writes alongside every screenshot carry the real
    # visible text, so the claim can simply be checked.
    _QUOTED_TEXT = re.compile(r"""['"\u201c\u2018]([^'"\u201c\u201d\u2018\u2019]{2,60})['"\u201d\u2019]""")

    # journeytest-core's ".txt" snapshots are accessibility-tree dumps, one node per
    # line with its visible text quoted:
    #   - button "Sign in with HF" [ref=e9]
    _ACCESSIBILITY_NODE_TEXT = re.compile(r'"([^"]*)"')

    @classmethod
    def _visible_text_corpus(cls, journeys: list[dict[str, Any]]) -> list[str]:
        """Every piece of text journeytest-core actually saw on the page, one entry
        per captured node, across every snapshot of every run.

        Both snapshot kinds count. The ".json" DOM captures carry only interactive
        elements, so checking a quote against those alone would reject a true finding
        that quotes a heading or a paragraph; the ".txt" accessibility trees include
        the non-interactive nodes too.
        """
        corpus: list[str] = []
        for journey in journeys:
            for snapshot_path in (journey.get("artifacts") or {}).get("snapshots") or []:
                try:
                    body = Path(snapshot_path).read_text()
                except OSError:
                    continue
                try:
                    snapshot = json.loads(body)
                except json.JSONDecodeError:
                    corpus.extend(text.strip() for text in cls._ACCESSIBILITY_NODE_TEXT.findall(body)
                                  if text.strip())
                    continue
                if not isinstance(snapshot, dict):
                    continue
                for element in snapshot.get("elements") or []:
                    text = str((element or {}).get("text") or "").strip()
                    if text:
                        corpus.append(text)
        return corpus

    @classmethod
    def _quote_is_on_page(cls, quote: str, corpus: list[str]) -> bool:
        """A quoted literal is credible when it is a whole captured text, or begins
        one ("Sign up" quoted from a "Sign up free" button). A match that starts
        mid-element is a fragment of a sentence, not a visible string in its own
        right -- which is exactly the shape of the invented "navbar." finding.
        """
        needle = quote.strip().casefold()
        if not needle:
            return False
        return any(text.casefold() == needle or text.casefold().startswith(needle) for text in corpus)

    @classmethod
    def _drop_unverifiable_quotes(cls, findings: list[dict[str, Any]], corpus: list[str]
                                  ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Remove findings whose quoted on-page text is not on the page.

        Only runs when there is a corpus to check against -- with no snapshots
        captured, nothing is verifiable and nothing is dropped. Findings that quote
        no literal text at all are untouched: this checks a specific kind of claim,
        it does not second-guess the critique.
        """
        if not corpus:
            return findings, []
        kept, rejected = [], []
        for finding in findings:
            quotes = cls._QUOTED_TEXT.findall(f"{finding.get('title', '')} {finding.get('summary', '')}")
            unverified = [quote for quote in quotes if not cls._quote_is_on_page(quote, corpus)]
            if unverified:
                rejected.append({"title": finding.get("title"), "quotes": unverified,
                                 "source": finding.get("source"), "runId": finding.get("runId")})
                continue
            kept.append(finding)
        return kept, rejected

    @classmethod
    def _attach_verdict_screenshots(cls, findings: list[dict[str, Any]], journeys: list[dict[str, Any]]) -> None:
        """Show the page a stage-1 finding is about.

        Only the vision-synthesis findings carried an image before, so every slide
        built from JourneyTest's own verdict (blockers, uxFindings, failed pass
        criteria) rendered with an empty "Current design" panel. The verdict already
        cites the screenshot it drew each finding from -- use it. Where it cites
        none, fall back to the run's own framing shots: the state the run ended in
        for a blocker or a failed criterion, the state it started in for an
        observation about the page.
        """
        screenshots_by_run = {journey.get("runId"): (journey.get("artifacts") or {}).get("screenshots") or []
                              for journey in journeys}
        for finding in findings:
            if finding.get("screenshotCrop"):
                continue
            path = finding.get("evidenceScreenshot")
            if not path or not Path(path).is_file():
                run_screenshots = screenshots_by_run.get(finding.get("runId")) or []
                preferred = "final-view" if finding.get("source") in ("blockers", "criteria") else "initial-view"
                path = (next((item for item in run_screenshots if Path(item).stem == preferred), None)
                        or (run_screenshots[-1] if run_screenshots else None))
            if not path:
                continue
            try:
                image_bytes = Path(path).read_bytes()
            except OSError:
                continue
            # Crop to the element when the finding knows where it is. A finding
            # about one unreadable caption, illustrated with the whole page, makes
            # the reader hunt for what it is talking about -- and on a capture
            # degraded to that persona's eyesight, hunting is exactly what they
            # cannot do.
            box = finding.get("elementBox")
            crop = cls._crop_element_data_uri(image_bytes, box) if box else None
            is_region = bool(crop)
            if not crop:
                crop = cls._screenshot_data_uri(image_bytes)
            if crop:
                finding["screenshotCrop"] = crop
                finding["screenshotIsRegion"] = is_region
                finding["screenshotRef"] = path

    @staticmethod
    def _praise_as_strengths(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reshape synthesized findings that turned out to be praise into the record
        _merge_strengths groups, keeping every persona the synthesis credited."""
        strengths = []
        for finding in findings:
            persona_ids = finding.get("affectedPersonaIds") or (
                [finding["personaId"]] if finding.get("personaId") else [None])
            for persona_id in persona_ids:
                strengths.append({"title": finding.get("title") or "Design decision that works",
                                  "description": finding.get("summary") or "",
                                  "elements": finding.get("elements") or [], "personaId": persona_id,
                                  "route": finding.get("route"), "screenshotRef": finding.get("screenshotRef"),
                                  "source": "eyeson-vision-synthesis"})
        return strengths

    @staticmethod
    def _praise_from_verdicts(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The other half of the `uxFindings` bucket: what the agent said works.

        Shaped like the vision-critique strengths so it flows through the same
        _merge_strengths() grouping into "elements to preserve" -- one design
        decision named once, with the personas who observed it, rather than one
        entry per run.
        """
        praise: list[dict[str, Any]] = []
        for journey in journeys:
            persona_id = journey.get("profileId") or journey.get("testerProfileId")
            for item in (journey.get("verdict") or {}).get("uxFindings", []):
                if not _reads_as_praise(item.get("title"), item.get("description")):
                    continue
                praise.append({"title": item.get("title") or "Design decision that works",
                               "description": item.get("description") or "",
                               "elements": [], "personaId": persona_id,
                               "route": None, "screenshotRef": None, "source": "verdict.uxFindings"})
        return praise

    @staticmethod
    def _evenly_spaced(items: list, limit: int) -> list:
        if len(items) <= limit or limit <= 0:
            return items
        step = len(items) / limit
        return [items[int(index * step)] for index in range(limit)]

    # journeytest-core writes, per action, a screenshot triple
    # (001-click-e21-before.png / -after.png / -change-001.png) plus the semantic
    # DOM capture as 001-click-e21-before-dom.json / -after-dom.json. The ".txt"
    # snapshots beside them are the agent's own text rendering, not JSON, and carry
    # no element geometry.
    _DOM_SNAPSHOT_SUFFIX = "-dom"
    _ACTION_PHASE_PATTERN = re.compile(r"^(?P<action>.+?)-(?:before|after|change-\d+)$")

    @classmethod
    def _stem(cls, path: str) -> str:
        """The action a capture belongs to, with its phase suffix removed."""
        match = cls._ACTION_PHASE_PATTERN.match(Path(path).stem)
        return match.group("action") if match else Path(path).stem

    @classmethod
    def _dom_snapshots(cls, snapshot_paths: list[str]) -> dict[str, str]:
        """The JSON DOM snapshots among a run's snapshot artifacts, keyed by the
        screenshot stem they describe (i.e. with the "-dom" marker removed)."""
        snapshots = {}
        for snapshot_path in snapshot_paths:
            path = Path(snapshot_path)
            if path.suffix != ".json":
                continue
            stem = path.stem
            if stem.endswith(cls._DOM_SNAPSHOT_SUFFIX):
                stem = stem[: -len(cls._DOM_SNAPSHOT_SUFFIX)]
            snapshots[stem] = snapshot_path
        return snapshots

    @staticmethod
    def _read_snapshot_elements(snapshot_path: str) -> list[dict]:
        try:
            snapshot = json.loads(Path(snapshot_path).read_text())
        except (OSError, json.JSONDecodeError):
            return []
        return snapshot.get("elements", []) if isinstance(snapshot, dict) else []

    @classmethod
    def _elements_for_screenshot(cls, screenshot_path: str, snapshot_paths: list[str]) -> list[dict]:
        """The real semantic elements (selector/role/text/boundingBox) captured for
        the page state a screenshot shows.

        Pairing is by name, in decreasing order of directness:

        1. The DOM snapshot taken for exactly this capture
           (001-click-e21-after.png -> 001-click-e21-after-dom.json).
        2. The same action's other phase -- a "change-001" frame has no DOM capture
           of its own, so the action's post-action DOM ("-after"), else its
           pre-action DOM ("-before"), describes the same page.
        3. For the un-numbered framing shots journeytest-core takes around the run
           ("initial-view", "final-view"), the first and last DOM capture
           respectively: those are literally the page before the first action and
           after the last one.

        Returns [] when none of those hold, rather than attributing a finding to
        elements from a different page state.

        Before this, none of them held for *any* screenshot: the previous stem rule
        stripped "-before"/"-after" from the screenshot but left "-dom" on the
        snapshot, so the two never matched and every vision finding was produced
        with an empty element list -- which is why every crop in a live run came
        back as a full page rather than the region a finding was about.
        """
        dom_snapshots = cls._dom_snapshots(snapshot_paths)
        if not dom_snapshots:
            return []
        stem = Path(screenshot_path).stem
        if stem in dom_snapshots:
            return cls._read_snapshot_elements(dom_snapshots[stem])
        match = cls._ACTION_PHASE_PATTERN.match(stem)
        if match:
            for phase in ("after", "before"):
                candidate = f"{match.group('action')}-{phase}"
                if candidate in dom_snapshots:
                    return cls._read_snapshot_elements(dom_snapshots[candidate])
            return []
        # Capture order, not alphabetical order: within one action "-before" comes
        # first, and "001-click-e21-after" sorts ahead of "001-click-e21-before".
        def capture_order(key: str) -> tuple[str, int]:
            phase = cls._ACTION_PHASE_PATTERN.match(key)
            return (phase.group("action"), 0 if key.endswith("-before") else 1) if phase else (key, 1)

        ordered = [dom_snapshots[key] for key in sorted(dom_snapshots, key=capture_order)]
        if stem == "initial-view":
            return cls._read_snapshot_elements(ordered[0])
        if stem == "final-view":
            return cls._read_snapshot_elements(ordered[-1])
        return []

    @staticmethod
    def _vision_image_budget() -> int:
        """Encoded image bytes the vision request may carry.

        The observed rejection was HTTP 413 "request entity too large", which is
        what a reverse proxy in front of the model router answers when the body
        passes its cap -- nginx defaults that cap to 1 MB. Budgeting the image
        well under it leaves room for the prompt and the element list in the
        same body.
        """
        return int(os.getenv("EYESON_VISION_MAX_IMAGE_BYTES", "450000"))

    @staticmethod
    def _repeated_band_height(image, min_repeats: int = 3) -> int | None:
        """The height of the band a full-page capture repeated, if it did.

        A full-page screenshot is stitched from viewport-sized captures, and on a
        page whose layout is pinned to the viewport -- a fixed hero, a scroll-
        locked section -- every capture comes back showing the same thing. The
        stitcher pastes them anyway, so the "page" is one band repeated down a
        very tall image.

        This is not a hypothetical. A live run against a real customer site
        produced a 1280x8620 capture holding the same header-and-hero band about
        fourteen times, and the vision model did exactly what it should with the
        evidence it was given: it reported a CRITICAL "infinite repeating page
        content ... makes the site look completely broken" defect. The site is
        fine. The capture was not, and the finding went into a customer-facing
        report as the single thing to fix first.

        What identifies the artifact is not that some band recurs -- plenty of
        real pages repeat a card or a row -- but that the image resembles itself
        more at a distance of a whole band than at a distance of one row. On that
        real capture the mean difference across the band period was 2.7 per
        channel value against 14.9 row-to-row: the page has more variation
        between adjacent lines than between what should be different sections of
        it. A page with genuinely varied content cannot do that.

        Returns the band height in the image's own pixels, or None.
        """
        from PIL import Image, ImageChops, ImageStat

        # Only stitched captures: a viewport screenshot is nothing like this tall.
        if image.height < image.width * 3:
            return None
        # A small greyscale copy is enough to tell bands apart and keeps the
        # comparison to a handful of whole-image operations.
        probe_height = 640
        probe = image.convert("L").resize((32, probe_height), Image.LANCZOS)

        def difference(offset: int) -> float:
            """Mean absolute difference between the image and itself, shifted."""
            above = probe.crop((0, 0, 32, probe_height - offset))
            below = probe.crop((0, offset, 32, probe_height))
            return ImageStat.Stat(ImageChops.difference(above, below)).mean[0]

        adjacent = difference(1)
        if adjacent <= 0:
            return None     # a blank capture repeats nothing
        scores = {period: difference(period) for period in range(8, probe_height // min_repeats + 1)}
        coarse = min(scores, key=scores.get)
        # More self-similar a band apart than a row apart, and near-identical in
        # absolute terms -- the signature of a stitch, not of repetitive design.
        if scores[coarse] > adjacent / 2 or scores[coarse] > 6:
            return None

        # The coarse pass says the image repeats, but not always at the band's own
        # height: a band repeats at two and three times its height too, and
        # squeezing the page into 640 rows puts the true period at a fractional
        # number of them, where a harmonic that lands nearer a whole row scores
        # better. So the height is settled at the image's own resolution, over the
        # only candidates it can be -- whole divisions of what the coarse pass
        # found -- and the smallest that still matches wins.
        tall = image.convert("L").resize((32, image.height), Image.LANCZOS)

        def band_difference(height: int) -> float:
            """How much the top band differs from the band directly below it."""
            above = tall.crop((0, 0, 32, height))
            below = tall.crop((0, height, 32, height * 2))
            return ImageStat.Stat(ImageChops.difference(above, below)).mean[0]

        coarse_height = max(1, int(round(coarse * image.height / probe_height)))
        candidates = []
        for division in range(1, 13):
            height = int(round(coarse_height / division))
            if height < 8 or height * min_repeats > image.height:
                continue
            candidates.append((height, band_difference(height)))
        if not candidates:
            return None
        closest = min(score for _, score in candidates)
        tolerance = max(closest * 1.5, closest + 0.5)
        return min(height for height, score in candidates if score <= tolerance)

    @classmethod
    def _trim_repeated_capture(cls, image_bytes: bytes) -> tuple[bytes, int | None]:
        """One band of a capture that repeated itself, or the capture unchanged.

        The first band is a faithful screenshot of what the browser showed; the
        rest is the stitcher repeating it. Keeping the first band and dropping
        the repeats is what stops a capture artifact from being reported as a
        defect in the page.
        """
        try:
            from PIL import Image
        except ImportError:
            return image_bytes, None
        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                image = opened.convert("RGB")
                band = cls._repeated_band_height(image)
                if not band or band >= image.height:
                    return image_bytes, None
                buffer = BytesIO()
                image.crop((0, 0, image.width, band)).save(buffer, format="PNG", optimize=True)
                return buffer.getvalue(), image.height
        except (OSError, ValueError):
            return image_bytes, None

    @classmethod
    def _vision_image_payload(cls, image_bytes: bytes) -> tuple[str, str]:
        """Shrink a screenshot until the vision endpoint will accept it.

        JourneyTest writes full-page captures -- one nova-test page was 2.4 MB
        and 12000px tall (see _screenshot_data_uri) -- and base64 adds a third on
        top of that. Sent unmodified the router answered 413, and because the
        worker retried a request that could never succeed, the run surfaced a
        generic "failed after 3 attempts" 502 with the real cause buried.

        Scales the whole page down rather than cropping it: the prompt lists
        every detected element and tells the model not to invent anything it
        cannot see, so a crop would hide elements it is being asked about.

        Returns (base64, mime). Falls back to the original bytes when Pillow is
        missing so such an environment degrades to today's behavior instead of
        losing the critique.
        """
        try:
            from PIL import Image
        except ImportError:
            return base64.b64encode(image_bytes).decode("ascii"), "image/png"

        budget = cls._vision_image_budget()
        if len(image_bytes) <= budget:
            return base64.b64encode(image_bytes).decode("ascii"), "image/png"

        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                image = opened.convert("RGB")
                # Vision models resample to a few hundred pixels per tile, so
                # width beyond a normal desktop viewport buys nothing.
                max_width = int(os.getenv("EYESON_VISION_MAX_IMAGE_WIDTH", "1400"))
                if image.width > max_width:
                    ratio = max_width / float(image.width)
                    image = image.resize((max_width, max(1, int(image.height * ratio))), Image.LANCZOS)

                best = None
                for quality in (82, 70, 58, 45):
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                    best = buffer.getvalue()
                    if len(best) <= budget:
                        return base64.b64encode(best).decode("ascii"), "image/jpeg"

                # Still over budget: a very tall page needs fewer pixels, not
                # just coarser ones. Halve until it fits or gets too small to read.
                while len(best) > budget and image.width > 320 and image.height > 320:
                    image = image.resize((max(320, image.width // 2), max(320, image.height // 2)), Image.LANCZOS)
                    buffer = BytesIO()
                    image.save(buffer, format="JPEG", quality=70, optimize=True, progressive=True)
                    best = buffer.getvalue()
                return base64.b64encode(best).decode("ascii"), "image/jpeg"
        except (OSError, ValueError):
            return base64.b64encode(image_bytes).decode("ascii"), "image/png"

    @staticmethod
    def _crop_element_data_uri(image_bytes: bytes, box: dict[str, Any] | None,
                               max_edge: int = 1200) -> str | None:
        """Crop the specific region a vision finding refers to out of the full
        screenshot, so the UI can show exactly what the finding is about instead
        of just a wall of text. Returns None (caller shows no image) rather than
        raising -- a missing crop is a lesser failure than losing the finding."""
        if not box:
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            x, y, width, height = float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
            with Image.open(BytesIO(image_bytes)) as image:
                pad = 12
                left, top = max(0, int(x - pad)), max(0, int(y - pad))
                right, bottom = min(image.width, int(x + width + pad)), min(image.height, int(y + height + pad))
                if right <= left or bottom <= top:
                    return None
                cropped = image.crop((left, top, right, bottom))
                # A finding can point at a large region (a hero, a whole nav
                # column), and an uncapped crop is emitted at natural size --
                # which is how a slide ended up with an image taller than the
                # screen. Small crops, where sharp text matters, are untouched.
                longest = max(cropped.width, cropped.height)
                if longest > max_edge:
                    ratio = max_edge / float(longest)
                    cropped = cropped.resize(
                        (max(1, int(cropped.width * ratio)), max(1, int(cropped.height * ratio))),
                        Image.LANCZOS)
                buffer = BytesIO()
                cropped.save(buffer, format="PNG")
                return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
        except (KeyError, TypeError, ValueError, OSError):
            return None

    @staticmethod
    def _screenshot_data_uri(image_bytes: bytes, max_width: int = 760, quality: int = 72,
                             max_height: int = 1500) -> str | None:
        """The whole screenshot a finding was critiqued from, downscaled for a slide.

        A vision finding about the page as a whole ("the layout repeats", "footer
        contrast is too low") legitimately has no single element to point at, so
        there is no region to crop, and a stage-1 verdict finding cites the page it
        was drawn from rather than a control on it. Showing the page the issue is
        about is far better than showing nothing.

        Encoded as JPEG rather than PNG: these are photographic full-page captures,
        and inlining them as base64 PNG made a real seven-finding deck 1.78 MB
        (131-261 KB per image) -- enough to make the deck slow to load in the tab it
        is rendered in. Element crops stay PNG, where sharp text matters and the
        images are small. A full-page capture of a long page is also taller than any
        slide panel can show legibly (2.4 MB and 12000px for one nova-test page), so
        the visible top of the page is kept rather than scaling the whole thing down
        to an unreadable strip.
        """
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                if image.width > max_width:
                    ratio = max_width / float(image.width)
                    image = image.resize((max_width, max(1, int(image.height * ratio))), Image.LANCZOS)
                if max_height and image.height > max_height:
                    image = image.crop((0, 0, image.width, max_height))
                buffer = BytesIO()
                image.convert("RGB").save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
                return f"data:image/jpeg;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
        except (OSError, ValueError):
            return None

    # "info" sits below "low" on purpose. It is what a finding is downgraded to
    # when the page is objectively compliant and only one unusual profile had
    # trouble -- said out loud, and never counted or ranked among the problems.
    _SEVERITY_RANK = {"info": -1, "low": 0, "medium": 1, "high": 2, "critical": 3}

    # Severities that are not usability issues and must not be counted as such.
    _NOT_A_PROBLEM = frozenset({"info"})

    @classmethod
    def _prepare_run_session(cls, job, data, personas):
        """Everything a run needs in order to be somebody.

        Returns the session file to browse with, and any accounts issued for this
        run. Both are optional: a run with neither browses the logged-out product
        as an anonymous visitor, which is still the common case.

        A failure here is not allowed to take the run down with it. A run that
        browses signed out is a worse run; a run that does not happen is no run
        at all, and the reason is recorded either way.
        """
        from .credentials import CredentialError, CredentialStore, KIND_SELF_ISSUED, issue_identity

        workspace_id = job.get("workspace_id") or "local"
        session_state_path, issued = None, {}
        credential_id = str(data.get("credentialId") or "").strip()
        wants_signup = bool(data.get("issueAccounts") or data.get("signUp"))
        if not credential_id and not wants_signup:
            return None, issued

        store = CredentialStore()
        if credential_id:
            try:
                session_state_path = store.write_state_file(
                    credential_id, Path(cls._run_session_dir(job)), workspace_id=workspace_id)
            except CredentialError as error:
                data.setdefault("warnings", []).append(f"Signed-out run: {error}")

        if wants_signup:
            for persona in personas:
                persona_id = persona.get("id") or "persona"
                identity = issue_identity(persona_id, data.get("url") or "")
                issued[persona_id] = identity
                try:
                    # Written down before the run, not after: an account invented
                    # mid-run and never recorded is one nobody can get back into.
                    store.put(workspace_id=workspace_id, label=f"{persona_id} @ {data.get('url') or 'target'}",
                              kind=KIND_SELF_ISSUED, origin=data.get("url") or "",
                              username=identity["email"], secret=identity["password"])
                except CredentialError as error:
                    data.setdefault("warnings", []).append(
                        f"Account issued but not stored, so it cannot be reused: {error}")
        return session_state_path, issued

    @staticmethod
    def _run_session_dir(job) -> str:
        """A run-scoped directory for the session file, under the artifact tree."""
        root = Path(os.getenv("ARTIFACT_ROOT", "data/artifacts")) / "sessions" / str(job["job_id"])
        root.mkdir(parents=True, exist_ok=True)
        return str(root)

    @staticmethod
    def _vision_timeout() -> float:
        """Long enough to outlast the worker's own retries.

        visionCritique.js makes up to 3 attempts at a 60s timeout with backoff
        between them -- about 186s in the worst case. Waiting the previous 90s cut
        the worker off mid-retry and turned a slow-but-recoverable model call into
        a client-side timeout with nothing to show for it.
        """
        return float(os.getenv("EYESON_VISION_TIMEOUT", "200"))

    @staticmethod
    def _worker_error(error: Exception) -> str:
        """What the worker actually said went wrong.

        `str(HTTPError)` is only "HTTP Error 422: Unprocessable Entity"; the reason
        is in the response body. A live run's report carried exactly that string as
        its entire explanation of why the vision critique produced nothing, which
        reads as a malformed request and named neither the real cause nor where to
        look for it.
        """
        if not isinstance(error, request.HTTPError):
            return str(error)
        try:
            detail = json.loads(error.read())
            message = detail.get("message") or detail.get("error") or ""
        except (OSError, ValueError, AttributeError):
            message = ""
        return f"HTTP {error.code} from the eyeson worker: {message}" if message else str(error)

    @classmethod
    def _collect_vision_pain_points(cls, journeys: list[dict[str, Any]], tasks: list[str],
                                     personas: list[dict[str, Any]], url: str | None
                                     ) -> tuple[list[dict[str, Any]], dict[str, bytes], list[dict[str, Any]],
                                                str | None, list[str]]:
        """Critique a bounded, evenly-spaced sample of each run's real screenshots
        with a real vision model (services/eyeson-worker's /v1/journey-evidence-
        analyses), referenced against journeytest-core's own semantic element
        snapshots. Returns (cohort_runs, screenshot_bytes_by_ref, error) --
        cohort_runs is one entry per persona, each carrying the full UXPainPoint
        records that persona's screenshots produced, ready for
        _synthesize_pain_points' cross-persona aggregation. Best-effort: a
        failure here never fails the run -- stage 1's findings still stand on
        their own."""
        worker_url = os.getenv("EYESON_WORKER_URL", "http://127.0.0.1:8081")
        try:
            limit = int(os.getenv("EYESON_VISION_SCREENSHOT_LIMIT", "3"))
        except (TypeError, ValueError):
            limit = 3
        task_summary = "; ".join(tasks)
        cohort_runs: list[dict[str, Any]] = []
        screenshot_bytes: dict[str, bytes] = {}
        strengths: list[dict[str, Any]] = []
        repeated_captures: list[str] = []
        attempted, last_error = False, None
        for journey, persona in zip(journeys, personas):
            artifacts = journey.get("artifacts") or {}
            screenshots, snapshots = artifacts.get("screenshots") or [], artifacts.get("snapshots") or []
            pain_points: list[dict[str, Any]] = []
            if screenshots:
                persona_summary = persona.get("minibio") or (persona.get("persona") or {}).get("name")
                # Critique the screenshots that have a semantic DOM capture in
                # preference to the ones that do not: with an element list the model
                # can name the exact control a finding is about, which is what lets
                # the report crop the region instead of showing the whole page.
                paired = [path for path in screenshots if cls._elements_for_screenshot(path, snapshots)]
                sampled = cls._evenly_spaced(paired or screenshots, max(1, limit))
                for step_index, screenshot_path in enumerate(sampled):
                    attempted = True
                    try:
                        image_bytes = Path(screenshot_path).read_bytes()
                    except OSError as error:
                        last_error = str(error)
                        continue
                    # A capture that repeated itself is trimmed to the one band
                    # that is real, before either the model or the report sees it.
                    image_bytes, repeated_from = cls._trim_repeated_capture(image_bytes)
                    if repeated_from:
                        repeated_captures.append(screenshot_path)
                    screenshot_bytes[screenshot_path] = image_bytes
                    elements = cls._elements_for_screenshot(screenshot_path, snapshots)
                    image_b64, image_mime = cls._vision_image_payload(image_bytes)
                    payload = json.dumps({
                        "imageBase64": image_b64, "imageMimeType": image_mime,
                        "elements": elements, "url": url, "task": task_summary, "personaSummary": persona_summary,
                        "runId": journey.get("runId"), "userId": persona.get("id"),
                        "stepId": f"vision-{step_index + 1}", "screenshotRef": screenshot_path,
                    }).encode()
                    call = request.Request(f"{worker_url.rstrip('/')}/v1/journey-evidence-analyses",
                        data=payload, headers={"content-type": "application/json"}, method="POST")
                    try:
                        with request.urlopen(call, timeout=cls._vision_timeout()) as response:
                            result = json.loads(response.read())
                    except (request.HTTPError, OSError, ValueError) as error:
                        last_error = cls._worker_error(error)
                        continue
                    pain_points.extend(result.get("painPoints", []))
                    for strength in result.get("strengths", []):
                        strengths.append({**strength, "personaId": persona.get("id"),
                                          "personaName": (persona.get("persona") or {}).get("name") or persona.get("name")})
            cohort_runs.append({
                "runId": journey.get("runId"), "profileId": persona.get("id"),
                "iterationId": journey.get("runId"), "verdict": (journey.get("verdict") or {}).get("status"),
                "simulationProfile": {"behavior": persona.get("behavior", {})}, "painPoints": pain_points,
            })
        if not attempted:
            return [], {}, [], None, []
        return (cohort_runs, screenshot_bytes, strengths,
                last_error if not any(run["painPoints"] for run in cohort_runs) and last_error else None,
                repeated_captures)

    @classmethod
    def _text_tokens(cls, text: str) -> set[str]:
        """Content words of a sentence or paragraph, stemmed -- for comparing the
        prose of two findings rather than their titles."""
        words = (word.strip("'") for word in re.findall(r"[a-z0-9']+", str(text).lower()))
        return {_stem(word) for word in words
                if len(word) > 2 and word not in _TITLE_STOPWORDS and word not in _PROSE_STOPWORDS}

    @staticmethod
    def _jaccard(left: set[str], right: set[str]) -> float:
        union = left | right
        return len(left & right) / len(union) if union else 0.0

    @staticmethod
    def _title_tokens(title: str, drop: frozenset[str] = frozenset()) -> set[str]:
        # Strip quote artifacts: a title like "Generic link text ('Learn more')"
        # otherwise yields "'learn" and "more'", which match nothing.
        tokens = (token.strip("'") for token in re.findall(r"[a-z0-9']+", str(title).lower()))
        return {token for token in tokens
                if len(token) > 2 and token not in _TITLE_STOPWORDS and token not in drop}

    @classmethod
    def _cluster_by_title(cls, items: list[dict[str, Any]], threshold: float = 0.5,
                          drop: frozenset[str] = frozenset(),
                          related=None) -> list[list[dict[str, Any]]]:
        """Group items whose titles describe the same thing.

        aggregateCohort groups pain points on an exact match of the vision model's
        free-form mechanism text, so one issue phrased three ways stays three
        issues -- a real run produced "Visually styled link is not interactive",
        "Visually apparent link is not interactive" and "Visually apparent link is
        not programmatically detected" as separate numbered findings. Single-linkage
        clustering on title-token overlap collapses those without needing another
        model call: an item joins a cluster if it is close to *any* member, which
        chains the three together even though the first and last are not
        individually close.

        `related` overrides the pairwise test entirely, for callers that have a
        better signal than the title alone.
        """
        tokens = [cls._title_tokens(item.get("title", ""), drop) for item in items]
        if related is None:
            def related(left, right, left_index, right_index):
                return cls._jaccard(tokens[left_index], tokens[right_index]) >= threshold
        # Connected components, not a greedy single pass: with three phrasings A, B
        # and C where A~C and B~C but A!~B, a greedy pass puts C in A's cluster and
        # strands B. Only the transitive closure gets all three into one issue.
        parent = list(range(len(items)))

        def find(node: int) -> int:
            while parent[node] != node:
                parent[node] = parent[parent[node]]
                node = parent[node]
            return node

        for left in range(len(items)):
            for right in range(left + 1, len(items)):
                if related(items[left], items[right], left, right):
                    parent[find(left)] = find(right)

        grouped: dict[int, list[dict[str, Any]]] = {}
        for index, item in enumerate(items):
            grouped.setdefault(find(index), []).append(item)
        # Preserve input order of first appearance so output stays deterministic.
        return [grouped[root] for root in dict.fromkeys(find(index) for index in range(len(items)))]

    @classmethod
    def _merge_similar_findings(cls, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """One real issue, stated once -- with everything each phrasing contributed.

        The threshold is a third rather than a half: a live run produced "Generic
        link text ('Learn more')", "Ambiguous link text" and "Non-descriptive link
        text" as three numbered issues, and the closest of those pairs overlaps on
        two tokens of six. Unrelated findings sit far below even that -- "Low
        contrast footer text" against "Primary navigation hidden in a dropdown"
        shares nothing at all -- so the looser threshold buys the real merges
        without collapsing distinct issues.

        The title alone is not enough. A live run against leon4gr45-nova-test
        published "Ambiguous navigation hierarchy" and "Redundant and confusing
        navigation layers" as two issues; both say the page offers several
        overlapping ways to navigate, but they share one content token in six, well
        under the title threshold. Their descriptions overlap far more, so the
        descriptions are compared as well.

        The prose threshold is calibrated against five real reports: across every
        pair of findings in them, true duplicates score 0.196-0.667 (including two
        verbatim repeats and the nova-test pair at 0.231) and the closest unrelated
        pair scores 0.159. 0.18 sits in that gap.
        """
        def same_issue(left: dict[str, Any], right: dict[str, Any], left_index: int, right_index: int) -> bool:
            # Two findings that name two different elements are two findings,
            # whatever their titles have in common. Every measured finding titles
            # itself the same way -- "Fails WCAG AA contrast: X", "Declared but not
            # drawn: X" -- so the boilerplate alone clears the title threshold and a
            # live run's nineteen perception findings collapsed into three, losing
            # "£200" and "Let's talk" into "Individual". They are different elements
            # with different fixes, and a page with ten pale labels has ten of them.
            here, there = left.get("elementName"), right.get("elementName")
            if here and there and here != there:
                return False
            if cls._jaccard(cls._title_tokens(left.get("title", "")),
                            cls._title_tokens(right.get("title", ""))) >= 0.33:
                return True
            return cls._jaccard(cls._text_tokens(left.get("summary") or ""),
                                cls._text_tokens(right.get("summary") or "")) >= 0.18

        merged: list[dict[str, Any]] = []
        for cluster in cls._cluster_by_title(findings, related=same_issue):
            if len(cluster) == 1:
                merged.append(cluster[0])
                continue
            # Lead with the most severe phrasing; it is the one a reader should see.
            primary = max(cluster, key=lambda item: cls._SEVERITY_RANK.get(str(item.get("severity")), 1))
            combined = dict(primary)
            persona_ids, alternatives, evidence = [], [], []
            for item in cluster:
                for persona_id in (item.get("affectedPersonaIds") or []):
                    if persona_id not in persona_ids:
                        persona_ids.append(persona_id)
                for alternative in (item.get("alternatives") or []):
                    if alternative.get("proposedChange") not in {existing.get("proposedChange") for existing in alternatives}:
                        alternatives.append(alternative)
                for quote in (item.get("personaEvidence") or []):
                    if quote.get("quote") not in {existing.get("quote") for existing in evidence}:
                        evidence.append(quote)
                for field in ("screenshotCrop", "screenshotIsRegion", "redesignHtml", "grounding", "rootCause"):
                    if not combined.get(field) and item.get(field):
                        combined[field] = item[field]
            if alternatives:
                combined["alternatives"] = alternatives
            if evidence:
                combined["personaEvidence"] = evidence
            if persona_ids:
                combined["affectedPersonaIds"] = persona_ids
                combined["affectedPersonas"] = len(persona_ids)
            combined["mergedFrom"] = [item.get("title") for item in cluster if item is not primary]
            merged.append(combined)
        return merged

    @classmethod
    def _merge_strengths(cls, strengths: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse per-screenshot strengths into the report's "elements to preserve"
        section: the same design decision seen by several personas is one item that
        names how many of them saw it, not one entry per screenshot.

        Grouped by title *similarity*, not exact text -- a real run produced "Clear
        and concise page purpose", "Clear purpose statement" and "Clear and concise
        purpose statement" as three separate items, which is one observation said
        three ways.
        """
        entries = []
        # Praise is mostly interchangeable adjectives -- "High visual contrast and
        # readability" and "Excellent visual contrast and simplicity" are one
        # observation. Dropping the quality words leaves the design property those
        # phrasings actually share, which is what should group them.
        # A quarter, not a third: "Clear visual status indicators" and "Effective use
        # of state indicators" -- one ACTIVE badge, described twice in a live run --
        # share one token in four once the quality words are dropped. Measured across
        # four real reports, 0.25 merges exactly the true repeats and nothing else.
        #
        # Deliberately *not* the description-similarity signal that merges findings:
        # on the same run it scores that true pair at 0.067 while scoring the ACTIVE
        # badge against a wholly separate progress stepper at 0.350, because both
        # descriptions happen to talk about the user's current location. Praise
        # describes a design property in whatever words come to hand; the shared
        # noun in the title is the more reliable signal here.
        for cluster in cls._cluster_by_title(
                [item for item in strengths if str(item.get("title", "")).strip()],
                threshold=0.25, drop=_QUALITY_ADJECTIVES):
            # Prefer the fullest description; the shortest phrasing is rarely the
            # most informative one.
            primary = max(cluster, key=lambda item: len(str(item.get("description") or "")))
            entry = {"title": primary.get("title"), "description": primary.get("description"),
                     "elements": primary.get("elements") or [], "personaIds": [], "routes": [], "screenshotRefs": [],
                     "alsoDescribedAs": [item.get("title") for item in cluster if item is not primary]}
            for item in cluster:
                for field, value in (("personaIds", item.get("personaId")), ("routes", item.get("route")),
                                     ("screenshotRefs", item.get("screenshotRef"))):
                    if value and value not in entry[field]:
                        entry[field].append(value)
            entry["observedByPersonas"] = len(entry["personaIds"])
            entries.append(entry)
        return sorted(entries, key=lambda item: -item["observedByPersonas"])

    @classmethod
    def _persona_thoughts(cls, journey: dict[str, Any], limit: int = 12) -> list[dict[str, Any]]:
        """The persona's own account of driving the browser.

        journeytest-core records every assistant turn as an `agent.message.end`
        timeline event, whose own `summary` is the fixed literal "Assistant message
        ended" -- so anything rendering `summary` alone (as every view here
        previously did) shows no thinking at all. The reasoning, when it is
        recorded, is in `data.text`.

        It is often not recorded. Its `piSdkDirector` builds that text from only
        the assistant message's `content.type === "text"` blocks; a reasoning model
        returns its thinking in `thinking` blocks instead, which are dropped before
        the event is written. Verified against a live two-persona run: 12 `thinking`
        blocks across the run, and zero events carrying `data.text`.

        So the journey worker now captures the model's reasoning from the
        completions responses themselves, below the layer that discards it
        (services/journey-worker/node/src/reasoningCapture.js), and returns it on
        the run as `reasoning`. Those are the model's real thinking tokens for that
        request -- what it was actually thinking while it drove the browser -- and
        they are preferred over everything else here.

        The two fallbacks remain for a run that has none: `data.text` when the
        provider emits ordinary text blocks, and otherwise the agent's own
        end-of-run prose (its verdict summary and finding descriptions). That last
        one is retrospective review written after the fact, not live thought, so it
        reads as generic UX commentary -- every item is labelled with which of the
        three it came from, and nothing else in the report may present them as
        equivalent.
        """
        # A persona run has a better account of itself than the model's completion
        # tokens: the director records what the person expected before acting and
        # what they made of what arrived. Those are sentences about the page in the
        # person's voice. The completion tokens are the model talking to itself
        # about machinery -- "We'll click 'How it works' link (ref=e3)", "we need
        # screenshot evidence", first person plural, about refs. A live report
        # published exactly that as Friedrich Wolf's evidence for its only finding,
        # including the model arguing with itself ("However, the snapshot does not
        # show any price numbers. So we can say..."). So where a persona spoke, the
        # persona is quoted, and the machinery becomes the fallback it always was
        # for the agent director.
        persona_said = cls._persona_voice(journey)
        thoughts: list[dict[str, Any]] = list(persona_said)
        if not persona_said:
            thoughts.extend(
                {"kind": "reasoning", "source": "model.reasoning", "text": str(item.get("text") or "").strip(),
                 "elapsedMs": item.get("elapsedMs"), "model": item.get("model")}
                for item in (journey.get("reasoning") or [])
                if str(item.get("text") or "").strip())
        for event in journey.get("timeline") or []:
            event_type, data = event.get("type", ""), event.get("data") or {}
            elapsed, task_id = event.get("elapsedMs"), event.get("taskId")
            if event_type == "agent.message.end" and not persona_said:
                text = str(data.get("text") or "").strip()
                if text:
                    thoughts.append({"kind": "reasoning", "source": "timeline", "text": text,
                                     "elapsedMs": elapsed, "taskId": task_id,
                                     "toolCalls": data.get("toolCalls") or []})
            elif event_type == "agent.message.error":
                text = str(data.get("errorMessage") or "").strip()
                if text:
                    thoughts.append({"kind": "error", "source": "timeline", "text": text,
                                     "elapsedMs": elapsed, "taskId": task_id})
            elif event_type.startswith("browser.") and event_type not in _QUIET_BROWSER_EVENTS:
                summary = str(event.get("summary") or "").strip()
                if summary:
                    thoughts.append({"kind": "action", "source": "timeline", "text": summary,
                                     "elapsedMs": elapsed, "taskId": task_id})
        if not any(item["kind"] == "reasoning" for item in thoughts):
            thoughts.extend(cls._verdict_thoughts(journey))
        if len(thoughts) <= limit:
            return thoughts
        # Keep the reasoning: it is what makes a finding legible to a designer.
        reasoning = [item for item in thoughts if item["kind"] != "action"]
        if len(reasoning) >= limit:
            return reasoning[:limit]
        actions = [item for item in thoughts if item["kind"] == "action"]
        kept = reasoning + actions[: limit - len(reasoning)]
        return sorted(kept, key=lambda item: item.get("elapsedMs") or 0)

    @staticmethod
    def _persona_voice(journey: dict[str, Any]) -> list[dict[str, Any]]:
        """What the person said about the page, from the persona director's own
        thought record.

        Three of its events are the person speaking about what is in front of
        them, and they are what a report should quote:

        - ``persona.expectation`` -- what they expected the thing they are about to
          click to do. It is the sentence that makes the next step falsifiable.
        - ``persona.reflection`` -- what actually arrived, and the gap. When the gap
          is non-empty it is the single most useful sentence in the run: a
          first-person statement of a page not doing what it looked like it would.
        - ``persona.affect`` -- how that left them, in words derived from the
          reflection rather than declared by the model.

        Everything else the director records is measurement (perception counts,
        adherence scores, affect numbers) and belongs in the report as numbers, not
        as a quote. ``persona.perception``'s narrative is deliberately excluded:
        "looked at 4 of 31 things" is an observation about the person, not the
        person's own words.
        """
        said: list[dict[str, Any]] = []
        for event in journey.get("timeline") or []:
            event_type, data = event.get("type", ""), event.get("data") or {}
            elapsed = event.get("elapsedMs")
            if event_type == "persona.reflection":
                # The gap first: "the page loaded, but the numbers I came for are
                # not on it" is the finding. `observed` alone is only a description.
                text = str(data.get("gap") or data.get("observed") or "").strip()
            elif event_type == "persona.expectation":
                text = str(data.get("expectation") or "").strip()
            elif event_type == "persona.affect":
                text = str(data.get("feeling") or "").strip()
            else:
                continue
            if text:
                said.append({"kind": "reasoning", "source": event_type, "text": text,
                             "elapsedMs": elapsed, "taskId": event.get("taskId")})
        return said

    @staticmethod
    def _verdict_thoughts(journey: dict[str, Any]) -> list[dict[str, Any]]:
        """The agent's own prose about the run, from the verdict it wrote.

        Used when the provider's reasoning never reached the timeline (see
        `_persona_thoughts`). This is still the agent's account in its own words --
        it is simply written at the end of the run rather than during it, and is
        labelled `source="verdict"` so a reader is never told a retrospective
        summary was a live thought.
        """
        verdict = journey.get("verdict") or {}
        thoughts: list[dict[str, Any]] = []
        summary = str(verdict.get("summary") or "").strip()
        if summary:
            thoughts.append({"kind": "reasoning", "source": "verdict", "text": summary, "elapsedMs": None})
        for bucket in ("blockers", "uxFindings"):
            for finding in verdict.get(bucket) or []:
                description = str(finding.get("description") or "").strip()
                if description:
                    thoughts.append({"kind": "reasoning", "source": f"verdict.{bucket}",
                                     "text": description, "elapsedMs": None})
        return thoughts

    @classmethod
    def _synthesize_pain_points(cls, cohort_runs: list[dict[str, Any]], screenshot_bytes: dict[str, bytes]) -> list[dict[str, Any]]:
        """Cross-persona synthesis (spec.md's cohort/root-cause aggregation,
        services/eyeson-worker/node/src/aggregate.js's aggregateCohort -- real,
        tested code that existed but was never wired to a live evidence source
        before this). Groups every persona's vision-critique pain points by
        shared route/elements/category/mechanism into root causes and returns
        the SYNTHESIZED result: every finding here describes how many personas
        hit it, the average estimated behavioral impact, and combined
        alternatives -- never a single persona's individual citation, even when
        only one persona ran (that just produces a root cause with one affected
        user, through the same synthesis path, not a special case)."""
        worker_url = os.getenv("EYESON_WORKER_URL", "http://127.0.0.1:8081")
        payload = json.dumps({"runs": cohort_runs}).encode()
        call = request.Request(f"{worker_url.rstrip('/')}/v1/cohort-aggregation",
            data=payload, headers={"content-type": "application/json"}, method="POST")
        try:
            with request.urlopen(call, timeout=float(os.getenv("EYESON_VISION_TIMEOUT", "90"))) as response:
                root_causes = json.loads(response.read()).get("rootCauses", [])
        except (request.HTTPError, OSError, ValueError) as error:
            # Cross-persona synthesis failing silently turned every vision finding
            # into nothing at all, with no trace of why.
            print(f"[executor] cohort aggregation failed: {cls._worker_error(error)}", flush=True)
            return []
        pain_point_by_id = {point["id"]: point for run in cohort_runs for point in run["painPoints"]}
        findings = []
        for root_cause in root_causes:
            member_points = [pain_point_by_id[pid] for pid in root_cause["painPointIds"] if pid in pain_point_by_id]
            if not member_points:
                continue
            representative = member_points[0]
            severity = max((point.get("severity", "medium") for point in member_points),
                           key=lambda value: cls._SEVERITY_RANK.get(value, 1))
            affected = len(root_cause["affectedUsers"])
            impact = root_cause["averageStateImpact"]
            crop, crop_is_region = None, False
            element = (representative.get("elements") or [{}])[0]
            screenshot = screenshot_bytes.get(representative.get("screenshotRef"))
            if element.get("box") and screenshot:
                crop = cls._crop_element_data_uri(screenshot, element["box"])
                crop_is_region = crop is not None
            if crop is None and screenshot:
                # Page-wide finding (no element to point at): show the page itself.
                crop = cls._screenshot_data_uri(screenshot)
            alternatives = root_cause.get("alternatives") or []
            recommendation = alternatives[0]["proposedChange"] if alternatives else None
            susceptible_traits = [trait for trait, correlation in (root_cause.get("personaSusceptibility") or {}).items()
                                   if isinstance(correlation, (int, float)) and abs(correlation) >= 0.6]
            summary_parts = [representative.get("summary", "")]
            if affected > 1:
                summary_parts.append(f"Seen across {affected} of the tested personas "
                                      f"({root_cause['affectedIterations'].__len__()} run(s)).")
            if susceptible_traits:
                summary_parts.append(f"More pronounced for personas with distinctive {', '.join(susceptible_traits)}.")
            finding = {
                "severity": severity, "category": root_cause.get("category", "usability"),
                "title": representative.get("title", "Synthesized UX finding"),
                "summary": " ".join(part for part in summary_parts if part),
                "recommendation": recommendation,
                "alternatives": [{"proposedChange": alt["proposedChange"], "rationale": alt.get("rationale"),
                                  "effort": alt.get("effort")} for alt in alternatives],
                # aggregateCohort's root-cause groups don't carry grounding (it isn't
                # part of the JS aggregation output); every member pain point shares
                # the same diagnosis.category as the group signature, so the curated
                # UX-heuristics references are identical across them -- take it from
                # the representative rather than losing it at this synthesis step.
                "grounding": representative.get("grounding"),
                # Kept as numbers as well as prose, because a number a reader is
                # shown is a number something should have been able to check.
                "claimedImpact": {"frustration": impact["frustration"],
                                  "confusion": impact["confusion"], "trust": -impact["trust"]},
                "observations": len(member_points),
                "affectedPersonas": affected, "affectedPersonaIds": list(root_cause["affectedUsers"]),
                "susceptibleTraits": susceptible_traits, "source": "eyeson-vision-synthesis",
                # Real element semantics (selector/role/text/box) from the snapshot the
                # critique referenced -- what grounds a redesign in the actual DOM
                # rather than in a guess at it.
                "elements": representative.get("elements") or [],
                "route": representative.get("route"),
            }
            if crop:
                finding["screenshotCrop"] = crop
                finding["screenshotIsRegion"] = crop_is_region
                # Without this the crop could not be traced back to the capture it
                # was taken from (it was recorded only for stage-1 findings).
                finding["screenshotRef"] = representative.get("screenshotRef")
            findings.append(finding)
        return findings

    def _ui_adaptation(self, job: dict[str, Any]) -> str:
        data = job["metadata"]
        title, request = data.get("title", "Responsive UX prototype"), data.get("request", "Improve clarity and responsiveness")
        html = self._generate_ui_html(title, request, data.get("url"), data.get("previous_html"))
        if html:
            return html
        # Deterministic offline fallback (no OPENAI_API_KEY/BLABLADOR_API_KEY
        # configured, or the LLM call failed): a real generation was attempted
        # and could not be produced, not a claim of a designed prototype.
        return f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><style>body{{font:16px system-ui;margin:auto;max-width:72rem;padding:clamp(1rem,4vw,4rem);color:#18202a}}main{{display:grid;gap:1rem}}section{{padding:1.5rem;border:1px solid #ccd5df;border-radius:1rem}}@media(min-width:48rem){{main{{grid-template-columns:2fr 1fr}}}}</style></head><body><h1>{escape(title)}</h1><main><section><h2>Adaptation request</h2><p>{escape(request)}</p></section><section><h2>Offline fallback</h2><p>No LLM credentials are configured (or generation failed), so this is a static placeholder rather than a generated prototype.</p></section></main></body></html>"""

    @classmethod
    def _attach_redesigns(cls, findings: list[dict[str, Any]], url: str | None) -> None:
        """Generate the "Re-design" half of each finding as real, inspectable HTML.

        The reference review deck pairs a photo of the current design with a mockup
        of the proposed one. The current half is ground truth here (a real cropped
        screenshot); this produces the other half as an actual HTML/CSS fragment
        rather than another image, so a designer or engineer can read and lift the
        markup instead of eyeballing a picture.

        It is grounded in what the run genuinely observed -- the real element
        selectors, roles, text and geometry captured in journeytest-core's semantic
        snapshot, plus the finding's own diagnosis and proposed changes -- not in a
        vision model's reconstruction of the pixels. Bounded to the worst findings
        (EYESON_REDESIGN_LIMIT, default 3) because each one is a live model call.
        """
        try:
            limit = int(os.getenv("EYESON_REDESIGN_LIMIT", "3"))
        except (TypeError, ValueError):
            limit = 3
        if limit <= 0:
            return
        ranked = sorted(findings, key=lambda item: -cls._SEVERITY_RANK.get(str(item.get("severity")), 1))
        for finding in ranked[:limit]:
            if finding.get("title") == "No pain points detected":
                continue
            fragment = cls._generate_redesign_fragment(finding, url)
            if fragment:
                finding["redesignHtml"] = fragment

    @staticmethod
    def _generate_redesign_fragment(finding: dict[str, Any], url: str | None) -> str | None:
        """One finding -> a self-contained HTML fragment implementing its fix.

        Returns None when no model is configured or the call fails: an absent
        redesign is honest, a templated one that ignores the finding is not.
        """
        if not (os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY")):
            return None
        try:
            from services.persona_service.semantic import DirectLLMSemanticEngine
            engine = DirectLLMSemanticEngine()
        except (ImportError, ValueError):
            return None
        elements = "\n".join(
            f'- selector="{element.get("elementId") or element.get("elementSelector", "")}" '
            f'role={element.get("role", "")} box={json.dumps(element.get("box") or {})}'
            for element in (finding.get("elements") or [])[:8]) or "(no specific element; page-wide finding)"
        changes = "\n".join(f"- {alternative.get('proposedChange')}"
                            for alternative in (finding.get("alternatives") or [])
                            if alternative.get("proposedChange")) or (finding.get("recommendation") or "")
        system_prompt = (
            "You are a senior frontend engineer producing the corrected version of ONE UI component "
            "for a usability review slide. Respond with ONLY an HTML fragment: a single root <div> "
            "containing an inline <style> scoped by a wrapper class, and the corrected markup. "
            "No <html>, <head> or <body>, no markdown fences, no commentary, no external requests "
            "or fonts. It must be self-contained, accessible (semantic elements, labelled controls, "
            "sufficient contrast) and must visibly implement the fix, not describe it. Keep it "
            "compact -- this is one component on a slide, not a whole page.")
        user_prompt = "\n\n".join([
            f"Target site: {url or 'unknown'}",
            f"Usability issue: {finding.get('title', '')}",
            f"What the user hit: {finding.get('summary') or finding.get('evidence') or ''}",
            f"Root cause: {finding.get('rootCause') or finding.get('mechanism') or 'not stated'}",
            f"Real elements observed in the page (from the browser's own semantic snapshot):\n{elements}",
            f"Changes to implement:\n{changes}",
            "Produce the corrected component implementing those changes.",
        ])
        try:
            content = engine.complete_text(system_prompt, user_prompt)
        except RuntimeError:
            return None
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
            stripped = re.sub(r"\n?```\s*$", "", stripped).strip()
        # A fragment, not a document: reject a full page, and reject prose.
        if "<html" in stripped.lower() or "<" not in stripped:
            return None
        return stripped or None

    @staticmethod
    def _generate_ui_html(title: str, request: str, url: str | None, previous_html: str | None) -> str | None:
        """Ask the configured OpenAI-compatible model for a real, self-contained
        HTML prototype implementing `request`, optionally revising `previous_html`
        for iterative chat-based adaptation. Returns None (caller falls back) if no
        LLM credentials are configured or the call fails after retries -- this is
        never faked with a fixed template that ignores the actual request."""
        if not (os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY")):
            return None
        try:
            from services.persona_service.semantic import DirectLLMSemanticEngine
            engine = DirectLLMSemanticEngine()
        except (ImportError, ValueError):
            return None
        system_prompt = ("You are a senior frontend engineer producing a single, complete, "
                          "self-contained HTML document (inline <style> and <script> only, no "
                          "external network requests) for a UX prototype. Respond with ONLY the "
                          "HTML document -- no markdown fences, no commentary before or after it. "
                          "It must be responsive, accessible (semantic landmarks, sufficient "
                          "contrast, labeled interactive elements), and visually implement the "
                          "requested change or design, not just describe it in text.")
        parts = [f"Prototype title: {title}", f"Requested change: {request}"]
        if url:
            parts.append(f"Target site being redesigned/adapted: {url}")
        if previous_html:
            parts.append("Revise the following existing prototype to satisfy the requested change "
                         "above, preserving anything not affected by the request:\n\n"
                         f"```html\n{previous_html}\n```")
        try:
            content = engine.complete_text(system_prompt, "\n\n".join(parts))
        except RuntimeError:
            return None
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
            stripped = re.sub(r"\n?```\s*$", "", stripped)
            stripped = stripped.strip()
        return stripped if "<html" in stripped.lower() else None

    @staticmethod
    def _download_name(kind: str, job_id: str, capture_stem: str | None = None) -> str:
        extension = {"ux.report": "json", "ux.presentation": "html", "ux.slides": "html", "journey.log": "json",
                     "ui.prototype": "html", "browser.screenshot": "png", "browser.snapshot": "json",
                     "browser.ui-change": "json", "browser.video": "webm"}[kind]
        # A run captures many screenshots; naming them all after the job alone made
        # them indistinguishable. The capture's own stem is what tells them apart
        # (and pairs a snapshot with its screenshot).
        suffix = f"-{re.sub(r'[^A-Za-z0-9_.-]', '_', capture_stem)}" if capture_stem else ""
        return f"{kind.replace('.', '-')}-{job_id}{suffix}.{extension}"

    @staticmethod
    def _presentation(report: dict[str, Any]) -> str:
        def render_finding(item: dict[str, Any]) -> str:
            image = (f'<img src="{escape(item["screenshotCrop"], quote=True)}" alt="Screenshot region for this finding" '
                     'style="max-width:min(100%,420px);max-height:52vh;object-fit:contain;object-position:top;'
                     'border-radius:.5rem;border:1px solid #334155;margin-top:.5rem">'
                     if item.get("screenshotCrop") else "")
            recommendation = (f'<p style="opacity:.85"><strong>Recommendation:</strong> {escape(item["recommendation"])}</p>'
                              if item.get("recommendation") else "")
            references = (item.get("grounding") or {}).get("references") or []
            grounding = (f'<p style="opacity:.6;font-size:.85em"><strong>Grounded in:</strong> ' +
                         "; ".join(f'{escape(ref.get("source", ""))} — {escape(ref.get("principle") or ref.get("title") or "")}'
                                   for ref in references) + '</p>') if references else ""
            badge = escape(str(item.get("severity", "")).upper())
            category = escape(str(item.get("category", "")))
            # The persona's own reasoning from the run that produced this finding --
            # what makes it demonstrated rather than asserted.
            quotes = "".join(
                f'<blockquote style="margin:.4rem 0;padding:.4rem .8rem;border-left:3px solid #38bdf8;opacity:.9">'
                f'{escape(str(evidence.get("quote", ""))[:400])}'
                f'<br><span style="opacity:.6;font-size:.8em">— {escape(str(evidence.get("personaName") or "Synthetic user"))}</span>'
                f'</blockquote>' for evidence in (item.get("personaEvidence") or [])[:2])
            return (f'<li><strong>[{badge}] {escape(item["title"])}</strong> '
                    f'<span style="opacity:.6">({category})</span><br>'
                    f'{escape(item.get("summary") or item.get("evidence") or "")}{recommendation}{grounding}{quotes}{image}</li>')

        findings = "".join(render_finding(item) for item in report.get("critical_pain_points", [])) or "<li>No findings.</li>"
        preserve_items = "".join(
            f'<li><strong>{escape(str(item.get("title", "")))}</strong>'
            + (f' <span style="opacity:.6">(noted by {item["observedByPersonas"]} persona(s))</span>'
               if item.get("observedByPersonas") else "")
            + f'<br>{escape(str(item.get("description") or ""))}</li>'
            for item in (report.get("elements_to_preserve") or []))
        preserve_section = (f'<section><h2>Elements to preserve</h2><p style="opacity:.7">Design decisions that are '
                            f'working and should survive a redesign.</p><ul>{preserve_items}</ul></section>'
                            if preserve_items else "")
        impact = report.get("impact_analysis") or {}
        priority_rows = "".join(
            f'<li><strong>{position}. {escape(str(entry.get("title") or ""))}</strong> '
            f'<span style="opacity:.6">({escape(str(entry.get("severity") or ""))}'
            + (f', {entry["affectedPersonas"]} persona(s)' if entry.get("affectedPersonas") else "") + ')</span></li>'
            for position, entry in enumerate(impact.get("priorityOrder") or [], start=1))
        impact_section = (f'<section><h2>What to fix first</h2><ol>{priority_rows}</ol></section>'
                          if priority_rows else "")
        return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>AUX UX report</title><style>body{{font:18px system-ui;margin:0;background:#101827;color:#f8fafc}}section{{min-height:90vh;padding:5vw;display:grid;align-content:center}}section:nth-child(even){{background:#172554}}h1{{font-size:clamp(2.5rem,7vw,6rem)}}li{{margin:1.5rem 0}}</style></head><body><section><h1>UX analysis</h1><p>{escape(report.get('url') or '')}</p><p>{escape(report.get('executive_summary') or '')}</p></section><section><h2>Critical pain points</h2><ul>{findings}</ul></section>{impact_section}{preserve_section}<section><h2>Evidence status</h2><p>{escape(report.get('evidence_language') or 'unknown')}</p><p>{escape(' '.join(report.get('limitations', [])))}</p></section></body></html>"""

    @classmethod
    def _slide_deck(cls, report: dict[str, Any]) -> str:
        """A real, navigable, self-contained usability-review deck.

        Follows the anatomy of a hand-made UX review deck (title, contents, an
        introduction stating method and scope, numbered per-issue sections, then a
        closing "elements to preserve" section) rather than dumping findings as a
        list, because that is the shape a designer or stakeholder actually reads.

        Two things this deck can show that a heuristic review cannot, and which are
        the whole point of the two-stage pipeline:
          * every issue is *observed* -- a synthetic user really drove a browser
            through it -- so the section is headed "Observed user issue" rather than
            the "Predicted user issue" a design walkthrough would have to say;
          * each one carries the persona's own reasoning from the run that produced
            it (journeytest-core's `agent.message.end` text), so the claim is
            demonstrated in the user's words instead of asserted.
        """
        findings = [item for item in report.get("critical_pain_points", [])
                    if item.get("title") != "No pain points detected"]
        preserve = report.get("elements_to_preserve") or []
        impact = report.get("impact_analysis") or {}
        observed = (report.get("evidence_language") or "") == "observed"
        issue_label = "Observed user issue" if observed else "Predicted user issue"
        url = report.get("url") or ""
        tasks = (report.get("journey_outcome") or {}).get("tasks") or []
        slides: list[str] = []

        def divider(number: str, title: str) -> str:
            return (f'<section class="slide divider"><p class="secnum">{escape(number)}</p>'
                    f'<h2>{escape(title)}</h2></section>')

        # --- 01 Title, contents, introduction ---
        slides.append(
            f'<section class="slide title"><p class="eyebrow">Usability review</p>'
            f'<h1>{escape(url) or "UX analysis"}</h1>'
            f'<p class="summary">{escape(report.get("executive_summary") or "")}</p>'
            f'<p class="stamp">{"Observed" if observed else "Inferred"} evidence &middot; '
            f'{escape(str(impact.get("personasTested", len(report.get("synthetic_users") or []))))} synthetic user(s)</p></section>')

        contents = [("01", "Introduction"), ("02", "User issues")]
        if preserve:
            contents.append(("03", "Elements to preserve"))
        contents_items = "".join(f'<li><span class="secnum-inline">{num}</span>{escape(label)}</li>'
                                 for num, label in contents)
        slides.append(f'<section class="slide"><h2>Contents</h2><ol class="contents">{contents_items}</ol></section>')

        slides.append(divider("01", "Introduction"))
        method = ("Synthetic users with compiled behaviour and ability profiles drove a real browser "
                  "through the tasks below. Each issue below was seen in that run, then critiqued "
                  "against a curated corpus of WCAG and Nielsen Norman usability heuristics."
                  if observed else
                  "No live browser evidence was collected for this run; the issues below are inferred "
                  "from the configured task text alone.")
        task_items = "".join(f"<li>{escape(task)}</li>" for task in tasks) or "<li>No tasks configured.</li>"
        severity_counts = impact.get("findingsBySeverity") or {}
        counts_line = ", ".join(f"{count} {severity}" for severity, count
                                in sorted(severity_counts.items(), key=lambda pair: -pair[1]))
        slides.append(
            f'<section class="slide"><h2>How this review was made</h2>'
            f'<p class="summary">{escape(method)}</p>'
            f'<h3>Tasks attempted</h3><ul>{task_items}</ul>'
            + (f'<p class="affected">{escape(str(len(findings)))} issue(s) found'
               + (f" &mdash; {escape(counts_line)}" if counts_line else "") + '</p>' if findings else "")
            + '</section>')

        # --- 02 Issues: a numbered sub-divider then the finding itself ---
        slides.append(divider("02", "User issues"))
        for index, item in enumerate(findings, start=1):
            slides.append(
                f'<section class="slide divider sub"><p class="secnum">02.{index}</p>'
                f'<h2>{escape(item.get("title", "Finding"))}</h2>'
                f'<p class="flow">{escape(cls._flow_label(item))}</p></section>')
            slides.append(cls._finding_slide(item, index, issue_label))

        # --- 03 Elements to preserve ---
        if preserve:
            slides.append(divider("03", "Elements to preserve"))
            # Editorial restraint, as in a hand-made review: show the most widely
            # observed, and say plainly how many were found rather than listing
            # every phrasing.
            shown = preserve[:6]
            if len(preserve) > len(shown):
                slides.append(
                    f'<section class="slide"><h2>What is working</h2>'
                    f'<p class="summary">{escape(str(len(preserve)))} design decisions were noted as working. '
                    f'The {escape(str(len(shown)))} seen by the most synthetic users follow.</p></section>')
            for item in shown:
                seen = item.get("observedByPersonas") or 0
                seen_line = (f'<p class="affected">Noted by {seen} of the tested persona(s)</p>' if seen else "")
                slides.append(
                    f'<section class="slide preserve"><span class="badge keep">KEEP</span>'
                    f'<h2>{escape(item.get("title", "Works well"))}</h2>{seen_line}'
                    f'<p class="summary">{escape(item.get("description") or "")}</p></section>')

        if not findings and not preserve:
            slides.append('<section class="slide"><h2>No findings</h2>'
                          '<p class="summary">No pain points were reported for this run.</p></section>')

        # --- Priorities + credits ---
        priorities = impact.get("priorityOrder") or []
        if priorities:
            rows = "".join(
                f'<tr><td>{position}</td><td>{escape(str(entry.get("title") or ""))}</td>'
                f'<td><span class="sev sev-{escape(str(entry.get("severity") or "medium"))}">'
                f'{escape(str(entry.get("severity") or "")).upper()}</span></td>'
                # The dash is markup, so it goes outside escape(): passing it
                # through turned an em dash into a literal "&mdash;" in the
                # rendered table.
                f'<td>{escape(str(entry["affectedPersonas"])) if entry.get("affectedPersonas") else "&mdash;"}</td></tr>'
                for position, entry in enumerate(priorities, start=1))
            slides.append(
                '<section class="slide"><h2>What to fix first</h2>'
                '<table class="impact"><thead><tr><th>#</th><th>Issue</th><th>Severity</th>'
                '<th>Personas</th></tr></thead><tbody>' + rows + '</tbody></table></section>')

        slides.append('<section class="slide title"><h1>Usability review</h1>'
                      f'<p class="summary">Generated by AUX from a live browser run against '
                      f'{escape(url) or "the target site"}.</p></section>')

        deck = "".join(slides)
        return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>
<title>Usability review slides</title><style>
:root{{color-scheme:light}}
*{{box-sizing:border-box}}
body{{margin:0;font:20px/1.55 "Helvetica Neue",Helvetica,Arial,system-ui,sans-serif;background:#eceff3;color:#16202c;overflow:hidden}}
.deck{{height:100vh;width:100vw;position:relative;background:#fff}}
.slide{{position:absolute;inset:0;padding:4.5vh 6vw;display:none;flex-direction:column;justify-content:center;gap:.7rem;overflow-y:auto;background:#fff}}
.slide.active{{display:flex}}
.slide.title{{align-items:flex-start;justify-content:center;background:#12303f;color:#fff}}
.slide.title h1{{color:#fff}}
.slide.divider{{align-items:flex-start;justify-content:center;background:#f4f6f8}}
.slide.divider.sub{{background:#fff;border-left:10px solid #12303f}}
.secnum{{font-size:clamp(3.2rem,11vw,8rem);font-weight:800;color:#12303f;opacity:.13;margin:0 0 -1.2rem;line-height:1;letter-spacing:-.04em}}
.slide.divider.sub .secnum{{opacity:.28;font-size:clamp(2rem,5vw,3.4rem);margin-bottom:.2rem}}
.secnum-inline{{display:inline-block;min-width:3rem;color:#12303f;font-weight:800;opacity:.45}}
.eyebrow{{letter-spacing:.3em;text-transform:uppercase;font-size:.72rem;opacity:.6;margin:0 0 .6rem}}
.slide h1{{font-size:clamp(2rem,5vw,3.6rem);margin:0;font-weight:700;letter-spacing:-.02em}}
.slide h2{{font-size:clamp(1.4rem,3.2vw,2.3rem);margin:0;font-weight:700;letter-spacing:-.01em;color:#12303f}}
.slide h3{{font-size:.74rem;letter-spacing:.16em;text-transform:uppercase;color:#12303f;opacity:.55;margin:0 0 .25rem;font-weight:700}}
.contents{{list-style:none;padding:0;font-size:1.35rem;line-height:2.3;font-weight:600;color:#12303f}}
.badge{{align-self:flex-start;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:#5b6b7c}}
.badge.keep{{color:#0f7b4f;font-weight:700}}
.flow{{color:#5b6b7c;letter-spacing:.18em;text-transform:uppercase;font-size:.8rem;margin:.3rem 0 0;font-weight:600}}
.summary{{max-width:60rem;color:#39485a}}
.affected{{color:#5b6b7c;font-size:.9rem;margin:.1rem 0}}
.grounding{{color:#7c8896;font-size:.76rem;max-width:62rem;margin:.5rem 0 0;border-top:1px solid #e3e8ee;padding-top:.5rem}}
/* Text on the left, the evidence it is about on the right -- the layout a
   usability review is read in. */
.finding{{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:1.6rem;align-items:start;margin-top:.5rem}}
@media (max-width:60rem){{.finding{{grid-template-columns:1fr}}}}
.cols{{display:flex;flex-direction:column;gap:.85rem;min-width:0}}
.col p,.col ul{{margin:0;font-size:.95rem;color:#39485a}}
.col ul{{padding-left:1.05rem}}
.col li{{margin:.15rem 0}}
.evidence{{display:flex;flex-direction:column;gap:.7rem;min-width:0}}
.shots{{display:grid;grid-template-columns:1fr;gap:.7rem}}
.shot figcaption{{font-size:.68rem;letter-spacing:.16em;text-transform:uppercase;color:#5b6b7c;margin-bottom:.28rem;font-weight:700}}
.shot img{{width:100%;height:auto;max-height:42vh;object-fit:contain;object-position:top;border-radius:.35rem;border:1px solid #d6dde5;display:block;background:#fff}}
.shot iframe.redesign{{width:100%;height:14rem;border-radius:.35rem;border:1px solid #d6dde5;background:#fff;display:block}}
figure{{margin:0}}
blockquote{{margin:0;padding:.55rem .85rem;border-left:3px solid #12303f;background:#f4f6f8;border-radius:0 .3rem .3rem 0;font-size:.88rem;color:#39485a}}
blockquote cite{{display:block;color:#7c8896;font-size:.72rem;font-style:normal;margin-top:.3rem}}
details.code{{margin-top:.2rem;font-size:.78rem}}
details.code summary{{cursor:pointer;color:#5b6b7c;letter-spacing:.14em;text-transform:uppercase;font-size:.66rem;font-weight:700}}
details.code pre{{max-height:11rem;overflow:auto;background:#12303f;color:#e6edf3;border-radius:.35rem;padding:.65rem;margin:.35rem 0 0;font-size:.72rem;line-height:1.45}}
/* Last in the stylesheet on purpose. These override single-class rules like
   .shot img, so an equally specific rule appearing later would win and the
   whole block would do nothing -- which is exactly what happened when it sat
   at the top: the measured overflow did not move by a pixel.

   A slide scrolls rather than clips, which sounds safe and is not: content past
   the fold is simply absent when somebody presents this, and nothing says so.
   Measured on a deck of long findings with a screenshot each, every finding
   slide lost 49px at 1024x600 -- the size of an older projector and of a
   half-height window. Type and padding come down only on a short viewport, so a
   normal laptop keeps the size the deck was designed at. */
@media (max-height: 720px) {{
  body{{font-size:17.5px;line-height:1.45}}
  .slide{{padding:3.5vh 5vw;gap:.5rem}}
  .shot img{{max-height:36vh}}
}}
@media (max-height: 620px) {{
  body{{font-size:16px;line-height:1.4}}
  .slide{{padding:1.4vh 4.5vw;gap:.35rem}}
  /* The screenshot gives up the space, not the words. Shrinking the type far
     enough to fit a 42vh image on a 600px-tall screen would take it below
     legibility from the back of a room, which is what a deck is for. */
  .shot img{{max-height:24vh}}
  details.code pre{{max-height:7rem}}
  blockquote{{padding:.4rem .7rem;font-size:.84rem}}
}}
table.impact{{border-collapse:collapse;font-size:.92rem;max-width:62rem;color:#39485a}}
table.impact th{{text-align:left;padding:.4rem .8rem;border-bottom:2px solid #12303f;font-size:.7rem;letter-spacing:.14em;text-transform:uppercase;color:#12303f}}
table.impact td{{text-align:left;padding:.45rem .8rem;border-bottom:1px solid #e3e8ee}}
.sev{{font-size:.66rem;padding:.12rem .5rem;border-radius:2px;letter-spacing:.1em;font-weight:700}}
.sev-critical{{background:#fbe3e3;color:#a01b1b}}
.sev-high{{background:#fdeadb;color:#a3510e}}
.sev-medium{{background:#fdf4d9;color:#8a6206}}
.sev-low{{background:#e2eef8;color:#1c5680}}
.nav{{position:fixed;bottom:1.4rem;right:1.4rem;display:flex;gap:.4rem;z-index:10}}
.nav button{{background:#12303f;color:#fff;border:none;border-radius:.3rem;padding:.45rem 1rem;cursor:pointer;font-size:1rem}}
.nav button:hover{{background:#1d4459}}
.counter{{position:fixed;bottom:1.55rem;left:1.5rem;color:#7c8896;font-size:.8rem;letter-spacing:.1em}}
</style></head><body>
<div class="deck">{deck}</div>
<div class="nav"><button id="prev" aria-label="Previous slide">&larr;</button><button id="next" aria-label="Next slide">&rarr;</button></div>
<div class="counter" id="counter"></div>
<script>
const slides=document.querySelectorAll('.slide');let current=0;
function show(index){{current=Math.max(0,Math.min(slides.length-1,index));slides.forEach((s,i)=>s.classList.toggle('active',i===current));document.querySelector('#counter').textContent=(current+1)+' / '+slides.length;}}
document.querySelector('#next').onclick=()=>show(current+1);
document.querySelector('#prev').onclick=()=>show(current-1);
document.addEventListener('keydown',(e)=>{{if(e.key==='ArrowRight'||e.key===' ')show(current+1);if(e.key==='ArrowLeft')show(current-1);}});
document.querySelector('.deck').addEventListener('click',(e)=>{{if(e.target.tagName!=='BUTTON'&&e.target.tagName!=='IMG')show(current+1);}});
show(0);
</script>
</body></html>"""

    @staticmethod
    def _finding_slide(item: dict[str, Any], index: int, issue_label: str) -> str:
        """One issue, in the three-part shape a usability report uses: what the user
        hit, why it happens, and what to change -- beside the evidence for it."""
        severity = str(item.get("severity") or "medium")
        flow = JobExecutor._flow_label(item)
        issue_text = item.get("summary") or item.get("evidence") or ""
        # Never the `evidence` string: for a stage-1 verdict finding that is a bare
        # capture reference, and a slide headed "Root cause analysis" showing
        # "snapshot: 005-snapshot.txt" says nothing. The verdict's own observation is
        # real prose about what was seen; with neither, the column is left out.
        root_cause = item.get("rootCause") or item.get("mechanism") or item.get("observation") or ""
        alternatives = item.get("alternatives") or ([{"proposedChange": item["recommendation"]}]
                                                     if item.get("recommendation") else [])
        changes = "".join(f"<li>{escape(str(alt.get('proposedChange', '')))}</li>"
                          for alt in alternatives if alt.get("proposedChange"))
        affected = (f'<p class="affected">Reproduced by {item["affectedPersonas"]} of the tested persona(s)</p>'
                    if item.get("affectedPersonas") else "")
        references = (item.get("grounding") or {}).get("references") or []
        grounding = ('<p class="grounding"><strong>Grounded in:</strong> ' + "; ".join(
            f'{escape(str(ref.get("source", "")))} &mdash; {escape(str(ref.get("principle") or ref.get("title") or "")) }'
            for ref in references) + "</p>") if references else ""

        # Current design | Re-design, the pairing a redesign proposal is read in.
        panels = []
        if item.get("screenshotCrop"):
            # "(page context)" rather than "(full page)": a page-wide capture is shown
            # from the top down to the height a slide panel can render legibly.
            caption = "Current design" if item.get("screenshotIsRegion", True) else "Current design (page context)"
            panels.append(f'<figure class="shot"><figcaption>{caption}</figcaption>'
                          f'<img src="{escape(item["screenshotCrop"], quote=True)}" alt="The part of the page this issue is about"></figure>')
        # The re-design is real, running HTML rather than a picture of one: rendered
        # in an iframe so its own CSS cannot leak into the deck, with the markup
        # itself shown underneath so it can be read and lifted.
        if item.get("redesignHtml"):
            fragment = item["redesignHtml"]
            document = ("<!doctype html><meta charset=utf-8>"
                        "<style>body{margin:0;padding:12px;font:14px/1.5 system-ui,sans-serif;background:#fff;color:#111}</style>"
                        + fragment)
            panels.append('<figure class="shot"><figcaption>Re-design (live HTML)</figcaption>'
                          f'<iframe class="redesign" sandbox="allow-same-origin" '
                          f'srcdoc="{escape(document, quote=True)}" title="Proposed redesign of this component"></iframe>'
                          '</figure>')
        shots = f'<div class="shots">{"".join(panels)}</div>' if panels else ""
        if item.get("redesignHtml"):
            shots += (f'<details class="code"><summary>Re-design markup</summary>'
                      f'<pre><code>{escape(item["redesignHtml"])}</code></pre></details>')

        # The persona's own words -- what makes this observed rather than predicted.
        quotes = "".join(
            f'<blockquote>{escape(str(evidence.get("quote", ""))[:400])}'
            f'<cite>{escape(str(evidence.get("personaName") or evidence.get("personaId") or "Synthetic user"))}</cite></blockquote>'
            for evidence in (item.get("personaEvidence") or [])[:2])
        quote_block = f'<div class="col"><h3>In the user\'s words</h3>{quotes}</div>' if quotes else ""

        return (f'<section class="slide" data-severity="{escape(severity)}">'
                f'<span class="badge"><span class="sev sev-{escape(severity)}">{escape(severity.upper())}</span> '
                f'&middot; {escape(flow)}</span>'
                f'<h2>{escape(item.get("title", "Finding"))}</h2>{affected}'
                f'<div class="finding"><div class="cols">'
                f'<div class="col"><h3>{escape(issue_label)}</h3><p>{escape(str(issue_text))}</p></div>'
                + (f'<div class="col"><h3>Root cause analysis</h3><p>{escape(str(root_cause))}</p></div>'
                   if root_cause and root_cause != issue_text else "")
                + (f'<div class="col"><h3>Recommendations: design solutions</h3><ul>{changes}</ul></div>'
                   if changes else "")
                + quote_block
                + f'</div><div class="evidence">{shots}</div></div>{grounding}</section>')

    @staticmethod
    def _browser_outputs(report: dict[str, Any]):
        kinds = {
            "screenshots": ("browser.screenshot", "image/png"),
            "snapshots": ("browser.snapshot", "application/json"),
            "uiChanges": ("browser.ui-change", "application/json"),
            "video": ("browser.video", "video/webm"),
        }
        outputs = []
        for run in report.get("journey_outcome", {}).get("runs", []):
            artifacts = run.get("artifacts") or {}
            for field, (kind, content_type) in kinds.items():
                values = artifacts.get(field) or []
                if isinstance(values, str): values = [values]
                for value in values:
                    path = Path(value)
                    if path.is_file():
                        # Carry the capture's own stem and run id. Without them every
                        # screenshot in a run was stored under the identical
                        # download_name, so they were indistinguishable in the UI and
                        # a snapshot could not be paired with the screenshot it
                        # describes (they share a stem, which is how the vision stage
                        # matches them).
                        outputs.append((kind, content_type, path.read_bytes(),
                                        {"source_path": str(path), "capture_stem": path.stem,
                                         "run_id": run.get("runId")}))
        return outputs
