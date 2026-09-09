"""Local job executor implementing useful control-plane behavior without Jules.

The interface intentionally keeps execution behind persisted jobs and artifacts so a
JourneyTest worker can replace this development executor without changing clients.
"""
from __future__ import annotations

import base64
from html import escape
from io import BytesIO
import json
import os
from pathlib import Path
import re
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
_SUFFIXES = ("ations", "ation", "ings", "ing", "ers", "er", "ies", "ied", "es", "ed", "s")


def _stem(word: str) -> str:
    """Crude suffix stripping, enough that "navigation"/"navigate",
    "control"/"controls" and "confusion"/"confusing" compare equal. Two findings
    describing one problem rarely reuse the same inflections."""
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


def _capture_name(path: str | None) -> str:
    """The name a capture is known by, not where the container happened to write it.

    A live deck rendered "snapshot: /home/user/artifacts/journeys/2026-08-30T10-57-
    43-548Z-job_08147074e9f648a58d3c/snapshots/005-snapshot.txt" as its root-cause
    analysis. The absolute path says nothing to a reader and is meaningless once the
    container is gone; the capture's own name ("005-snapshot.txt") is what the
    evidence artifacts in the workspace are listed under."""
    return Path(str(path)).name if path else ""


def _evidence_reference_summary(evidence: dict[str, Any] | None) -> str:
    """Render a JourneyTest EvidenceReference (screenshot/snapshot/observation/... path
    or text) into a single human-readable string for the report's ``evidence`` field."""
    if not evidence:
        return "No evidence reference recorded on this finding."
    parts = []
    if evidence.get("observation"):
        parts.append(evidence["observation"])
    if evidence.get("screenshot"):
        parts.append(f"screenshot: {_capture_name(evidence['screenshot'])}")
    if evidence.get("snapshot"):
        parts.append(f"snapshot: {_capture_name(evidence['snapshot'])}")
    if evidence.get("uiChangeTimeline"):
        parts.append(f"UI change timeline: {_capture_name(evidence['uiChangeTimeline'])}")
    if evidence.get("url"):
        parts.append(f"url: {evidence['url']}")
    if evidence.get("videoTimeMs") is not None:
        parts.append(f"video @ {evidence['videoTimeMs']}ms")
    return "; ".join(parts) if parts else "Evidence reference recorded without a readable field."


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
                outputs.extend(self._browser_outputs(result))
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
        if worker_url:
            for persona in personas:
                payload = json.dumps({"runId": f"{job['job_id']}_{persona.get('id', len(journeys))}", "url": data.get("url"),
                    "tasks": tasks, "profile": persona, "browserSafety": browser_safety}).encode()
                call = request.Request(f"{worker_url.rstrip('/')}/v1/runs", data=payload, headers={"content-type": "application/json"}, method="POST")
                try:
                    with request.urlopen(call, timeout=float(os.getenv("JOURNEY_RUN_TIMEOUT", "600"))) as response:
                        journey = json.loads(response.read())
                        if journey.get("runStatus") == "error" or journey.get("error"):
                            message = (journey.get("error") or {}).get("message", "unknown JourneyTest error")
                            raise RuntimeError(f"JourneyTest run failed: {message}")
                        journeys.append(journey)
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
        if worker_url:
            findings = self._pain_points_from_journeys(journeys)
            cohort_runs, screenshot_bytes, raw_strengths, vision_error = self._collect_vision_pain_points(
                journeys, tasks, personas, data.get("url"))
            vision_findings = self._synthesize_pain_points(cohort_runs, screenshot_bytes) if cohort_runs else []
            # The vision model has a "strengths" array and still puts praise in
            # "issues" -- a live run published "Familiar and clean layout" as a
            # medium-severity usability issue. Same rule as JourneyTest's mixed
            # uxFindings bucket, applied to the other stage.
            vision_praise = [item for item in vision_findings
                             if _reads_as_praise(item.get("title"), item.get("summary"))]
            vision_findings = [item for item in vision_findings if item not in vision_praise]
            findings.extend(vision_findings)
            preserve = (self._merge_strengths(raw_strengths + self._praise_from_verdicts(journeys)
                                              + self._praise_as_strengths(vision_praise))
                        + self._preserved_from_verdicts(journeys))
            evidence_language, journey_status = "observed", "completed"
            limitations = [
                "Findings are JourneyTest's own evidence-grounded verdict (blockers/uxFindings/"
                "suggestedImprovements/failed pass-criteria) from a real browser run against the "
                "target URL, not text inferred from the task description.",
            ]
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
            findings.append({"severity": "low", "category": "ux", "title": "No pain points detected",
                "summary": "Neither JourneyTest's verdict nor the vision-based UX critique reported "
                           "any blockers, UX findings, or failed pass criteria for the configured tasks.",
                "evidence": "See journey_outcome.runs[].verdict for the full per-run verdict.",
                "source": "verdict"})
        # A harness failure is real but is not a usability finding about the product;
        # numbering it among the user issues (as "Pi director did not finish the
        # journey" was) misrepresents both.
        run_diagnostics = [finding for finding in findings if _is_run_diagnostic(finding)]
        findings = self._merge_similar_findings([finding for finding in findings if finding not in run_diagnostics])
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
                "executive_summary": self._executive_summary(data.get("url"), tasks, personas, findings, preserve),
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
                           findings: list[dict[str, Any]], preserve: list[dict[str, Any]]) -> str:
        """State what was actually found, not what was merely prepared."""
        blocking = sum(1 for finding in findings
                       if str(finding.get("severity")) in {"critical", "high"}
                       and finding.get("title") != "No pain points detected")
        real = [finding for finding in findings if finding.get("title") != "No pain points detected"]
        parts = [f"{len(personas)} synthetic user(s) attempted {len(tasks)} task(s) against {url or 'the target site'}."]
        parts.append(f"{len(real)} usability issue(s) were identified"
                     + (f", {blocking} of them high-severity or blocking." if blocking else "."))
        if preserve:
            parts.append(f"{len(preserve)} design decision(s) are working and should be preserved.")
        return " ".join(parts)

    @staticmethod
    def _pain_points_from_journeys(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                        "evidence": _evidence_reference_summary(item.get("evidence")),
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
                    "evidence": _evidence_reference_summary(criterion.get("evidence")),
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
            crop = cls._screenshot_data_uri(image_bytes)
            if crop:
                finding["screenshotCrop"] = crop
                finding["screenshotIsRegion"] = False
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
    def _crop_element_data_uri(image_bytes: bytes, box: dict[str, Any] | None) -> str | None:
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

    _SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

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
                                     ) -> tuple[list[dict[str, Any]], dict[str, bytes], list[dict[str, Any]], str | None]:
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
                    screenshot_bytes[screenshot_path] = image_bytes
                    elements = cls._elements_for_screenshot(screenshot_path, snapshots)
                    payload = json.dumps({
                        "imageBase64": base64.b64encode(image_bytes).decode("ascii"),
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
            return [], {}, [], None
        return (cohort_runs, screenshot_bytes, strengths,
                last_error if not any(run["painPoints"] for run in cohort_runs) and last_error else None)

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
        thoughts: list[dict[str, Any]] = [
            {"kind": "reasoning", "source": "model.reasoning", "text": str(item.get("text") or "").strip(),
             "elapsedMs": item.get("elapsedMs"), "model": item.get("model")}
            for item in (journey.get("reasoning") or [])
            if str(item.get("text") or "").strip()
        ]
        for event in journey.get("timeline") or []:
            event_type, data = event.get("type", ""), event.get("data") or {}
            elapsed, task_id = event.get("elapsedMs"), event.get("taskId")
            if event_type == "agent.message.end":
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
                "evidence": f"synthesized from {len(member_points)} observation(s) across {affected} persona(s); "
                            f"estimated impact: frustration {impact['frustration']:.2f}, "
                            f"confusion {impact['confusion']:.2f}, trust erosion {-impact['trust']:.2f}",
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
                     'style="max-width:min(100%,420px);border-radius:.5rem;border:1px solid #334155;margin-top:.5rem">'
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
                f'<td>{escape(str(entry.get("affectedPersonas") or "&mdash;"))}</td></tr>'
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
.shot img{{width:100%;border-radius:.35rem;border:1px solid #d6dde5;display:block;background:#fff}}
.shot iframe.redesign{{width:100%;height:14rem;border-radius:.35rem;border:1px solid #d6dde5;background:#fff;display:block}}
figure{{margin:0}}
blockquote{{margin:0;padding:.55rem .85rem;border-left:3px solid #12303f;background:#f4f6f8;border-radius:0 .3rem .3rem 0;font-size:.88rem;color:#39485a}}
blockquote cite{{display:block;color:#7c8896;font-size:.72rem;font-style:normal;margin-top:.3rem}}
details.code{{margin-top:.2rem;font-size:.78rem}}
details.code summary{{cursor:pointer;color:#5b6b7c;letter-spacing:.14em;text-transform:uppercase;font-size:.66rem;font-weight:700}}
details.code pre{{max-height:11rem;overflow:auto;background:#12303f;color:#e6edf3;border-radius:.35rem;padding:.65rem;margin:.35rem 0 0;font-size:.72rem;line-height:1.45}}
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
