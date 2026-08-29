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


def _evidence_reference_summary(evidence: dict[str, Any] | None) -> str:
    """Render a JourneyTest EvidenceReference (screenshot/snapshot/observation/... path
    or text) into a single human-readable string for the report's ``evidence`` field."""
    if not evidence:
        return "No evidence reference recorded on this finding."
    parts = []
    if evidence.get("observation"):
        parts.append(evidence["observation"])
    if evidence.get("screenshot"):
        parts.append(f"screenshot: {evidence['screenshot']}")
    if evidence.get("snapshot"):
        parts.append(f"snapshot: {evidence['snapshot']}")
    if evidence.get("uiChangeTimeline"):
        parts.append(f"UI change timeline: {evidence['uiChangeTimeline']}")
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
            findings.extend(vision_findings)
            preserve = self._merge_strengths(raw_strengths) + self._preserved_from_verdicts(journeys)
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
        thoughts_by_persona = {persona.get("id"): self._persona_thoughts(journey)
                               for journey, persona in zip(journeys, personas) if persona.get("id")}
        persona_names = {persona.get("id"): (persona.get("persona") or {}).get("name") or persona.get("name") or persona.get("id")
                         for persona in personas}
        self._attach_persona_evidence(findings, thoughts_by_persona, persona_names)
        self._attach_redesigns(findings, data.get("url"))
        if any(item.get("source", "").startswith("verdict")
               for thoughts in thoughts_by_persona.values() for item in thoughts):
            limitations.append(
                "Persona quotes on these findings come from each agent's own end-of-run verdict prose, "
                "not its live per-step reasoning: journeytest-core records only assistant `text` content "
                "blocks into the timeline, and the configured model returns its reasoning in `thinking` "
                "blocks, which are dropped before the event is written. The quotes are the agent's own "
                "words about what it hit; they are just written at the end of the run rather than during it."
            )
        return {"schema_version": "1.1", "mode": "user_journey", "url": data.get("url"),
                "executive_summary": self._executive_summary(data.get("url"), tasks, personas, findings, preserve),
                "synthetic_users": personas, "persona_artifacts": persona_artifacts,
                "journey_outcome": {"status": journey_status, "tasks": tasks, "runs": journeys},
                "critical_pain_points": findings,
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
                    "title": f"Flow completes: {criterion_id}",
                    "description": criterion.get("explanation") or "The agent completed this criterion.",
                    "elements": [], "personaIds": [], "routes": [], "screenshotRefs": [], "source": "verdict"})
                persona_id = journey.get("profileId") or journey.get("testerProfileId")
                if persona_id and persona_id not in entry["personaIds"]:
                    entry["personaIds"].append(persona_id)
        for entry in preserved.values():
            entry["observedByPersonas"] = len(entry["personaIds"])
        return list(preserved.values())

    @staticmethod
    def _attach_persona_evidence(findings: list[dict[str, Any]], thoughts_by_persona: dict[str, list[dict[str, Any]]],
                                 persona_names: dict[str, str]) -> None:
        """Give every finding the persona reasoning that stands behind it.

        This is what turns a synthesized finding from an assertion into a
        demonstrated one: the reader sees the persona's own words from the run that
        produced it. Stage-1 findings name one persona; synthesized stage-2 findings
        name every persona the aggregation grouped together.
        """
        for finding in findings:
            persona_ids = finding.get("affectedPersonaIds") or (
                [finding["personaId"]] if finding.get("personaId") else [])
            evidence = []
            for persona_id in persona_ids:
                reasoning = [item for item in thoughts_by_persona.get(persona_id, []) if item["kind"] == "reasoning"]
                if reasoning:
                    evidence.append({"personaId": persona_id, "personaName": persona_names.get(persona_id, persona_id),
                                     "quote": reasoning[-1]["text"], "elapsedMs": reasoning[-1].get("elapsedMs")})
            if evidence:
                finding["personaEvidence"] = evidence

    @staticmethod
    def _flow_groups(findings: list[dict[str, Any]], tasks: list[str]) -> list[dict[str, Any]]:
        """Group findings the way a usability report is read -- by the part of the
        product they belong to -- instead of one flat list. Categories are the only
        route-independent grouping this pipeline actually has (a single-URL run gives
        every finding the same route), so they stand in for the reference report's
        "Introduction flow" / "Landing page" sections."""
        groups: dict[str, dict[str, Any]] = {}
        for finding in findings:
            key = str(finding.get("category") or "usability")
            group = groups.setdefault(key, {"flow": key.replace("_", " ").title(), "category": key, "findings": []})
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
                    findings.append({
                        "severity": _JOURNEYTEST_SEVERITY_MAP.get(item.get("severity"), fallback_severity),
                        "category": item.get("category"),
                        "title": item.get("title") or f"{bucket} finding",
                        "summary": item.get("description") or "",
                        "recommendation": item.get("recommendation"),
                        "evidence": _evidence_reference_summary(item.get("evidence")),
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
                    "title": f"Pass criterion {result}: {criterion_id}",
                    "summary": criterion.get("explanation") or "",
                    "evidence": _evidence_reference_summary(criterion.get("evidence")),
                    "source": "criteria", "runId": run_id, "personaId": persona_id,
                })
        return findings

    @staticmethod
    def _evenly_spaced(items: list, limit: int) -> list:
        if len(items) <= limit or limit <= 0:
            return items
        step = len(items) / limit
        return [items[int(index * step)] for index in range(limit)]

    _SNAPSHOT_SUFFIX_PATTERN = re.compile(r"-(before|after|change-\d+)$")

    @classmethod
    def _stem(cls, path: str) -> str:
        name = Path(path).stem
        return cls._SNAPSHOT_SUFFIX_PATTERN.sub("", name)

    @classmethod
    def _elements_for_screenshot(cls, screenshot_path: str, snapshot_paths: list[str]) -> list[dict]:
        """Best-effort pairing of a screenshot with the semantic snapshot captured
        alongside it, by shared filename stem (journeytest-core's uiChangeRecording
        middleware names paired before/after/change-N screenshots and snapshots
        with a common stem). Returns [] rather than guessing when no exact stem
        match exists -- a page-wide vision finding with no element attribution is
        honest; a wrongly paired element attribution is not."""
        target_stem = cls._stem(screenshot_path)
        for snapshot_path in snapshot_paths:
            if cls._stem(snapshot_path) == target_stem:
                try:
                    snapshot = json.loads(Path(snapshot_path).read_text())
                except (OSError, json.JSONDecodeError):
                    return []
                return snapshot.get("elements", []) if isinstance(snapshot, dict) else []
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
    def _screenshot_data_uri(image_bytes: bytes, max_width: int = 900) -> str | None:
        """The whole screenshot a finding was critiqued from, downscaled for a slide.

        A vision finding about the page as a whole ("the layout repeats", "footer
        contrast is too low") legitimately has no single element to point at, so
        there is no region to crop -- and on a live run against example.com every
        finding was page-wide, leaving the deck's "Current design" panel empty.
        Showing the page the issue is about is far better than showing nothing.
        """
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                if image.width > max_width:
                    ratio = max_width / float(image.width)
                    image = image.resize((max_width, max(1, int(image.height * ratio))))
                buffer = BytesIO()
                image.convert("RGB").save(buffer, format="PNG")
                return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode('ascii')}"
        except (OSError, ValueError):
            return None

    _SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

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
                for step_index, screenshot_path in enumerate(cls._evenly_spaced(screenshots, max(1, limit))):
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
                        with request.urlopen(call, timeout=float(os.getenv("EYESON_VISION_TIMEOUT", "90"))) as response:
                            result = json.loads(response.read())
                    except (request.HTTPError, OSError, ValueError) as error:
                        last_error = str(error)
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

    @staticmethod
    def _merge_strengths(strengths: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Collapse per-screenshot strengths into the report's "elements to preserve"
        section: the same design decision seen by several personas is one item that
        names how many of them saw it, not one entry per screenshot."""
        merged: dict[str, dict[str, Any]] = {}
        for strength in strengths:
            key = str(strength.get("title", "")).strip().lower()
            if not key:
                continue
            entry = merged.setdefault(key, {"title": strength.get("title"), "description": strength.get("description"),
                                            "elements": strength.get("elements") or [], "personaIds": [],
                                            "routes": [], "screenshotRefs": []})
            for field, value in (("personaIds", strength.get("personaId")), ("routes", strength.get("route")),
                                 ("screenshotRefs", strength.get("screenshotRef"))):
                if value and value not in entry[field]:
                    entry[field].append(value)
        for entry in merged.values():
            entry["observedByPersonas"] = len(entry["personaIds"])
        return sorted(merged.values(), key=lambda item: -item["observedByPersonas"])

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
        blocks across the run, and zero events carrying `data.text`. So this reads
        `data.text` when the provider does emit text blocks, and otherwise falls
        back to the agent's own prose that *is* recorded -- its verdict summary and
        the descriptions it wrote for each finding -- rather than reporting that the
        persona thought nothing. Every item says which of the two it came from.
        """
        thoughts: list[dict[str, Any]] = []
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
        except (request.HTTPError, OSError, ValueError):
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
            }
            if crop:
                finding["screenshotCrop"] = crop
                finding["screenshotIsRegion"] = crop_is_region
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
            category = str(item.get("category") or "usability").replace("_", " ")
            slides.append(
                f'<section class="slide divider sub"><p class="secnum">02.{index}</p>'
                f'<h2>{escape(item.get("title", "Finding"))}</h2>'
                f'<p class="flow">{escape(category.title())}</p></section>')
            slides.append(cls._finding_slide(item, index, issue_label))

        # --- 03 Elements to preserve ---
        if preserve:
            slides.append(divider("03", "Elements to preserve"))
            for item in preserve:
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
:root{{color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;font:20px/1.5 system-ui,sans-serif;background:#0b1220;color:#f1f5f9;overflow:hidden}}
.deck{{height:100vh;width:100vw;position:relative}}
.slide{{position:absolute;inset:0;padding:5vw 6vw;display:none;flex-direction:column;justify-content:center;gap:.9rem;overflow-y:auto}}
.slide.active{{display:flex}}
.slide.title{{align-items:center;text-align:center;background:linear-gradient(160deg,#0b1220,#15233d)}}
.slide.divider{{align-items:flex-start;justify-content:center;background:linear-gradient(160deg,#0f1b30,#0b1220)}}
.slide.divider.sub{{background:linear-gradient(160deg,#101d33,#0b1220)}}
.secnum{{font-size:clamp(3rem,10vw,7rem);font-weight:700;color:#38bdf8;opacity:.9;margin:0;line-height:1}}
.secnum-inline{{display:inline-block;min-width:2.5rem;color:#38bdf8;font-weight:700}}
.eyebrow{{letter-spacing:.25em;text-transform:uppercase;font-size:.8rem;opacity:.65;margin:0}}
.slide h1{{font-size:clamp(2rem,5.5vw,3.8rem);margin:0}}
.slide h2{{font-size:clamp(1.4rem,3.6vw,2.4rem);margin:0}}
.slide h3{{font-size:1rem;letter-spacing:.08em;text-transform:uppercase;opacity:.65;margin:.6rem 0 .1rem}}
.contents{{list-style:none;padding:0;font-size:1.3rem;line-height:2.2}}
.badge{{align-self:flex-start;font-size:.8rem;letter-spacing:.05em;padding:.25rem .75rem;border-radius:999px;background:#1e293b;border:1px solid #334155}}
.badge.keep{{background:#052e1a;border-color:#15803d;color:#4ade80}}
.flow{{opacity:.6;letter-spacing:.1em;text-transform:uppercase;font-size:.85rem}}
.summary{{max-width:62rem}}
.affected{{opacity:.75;font-size:.95rem;margin:.1rem 0}}
.grounding{{opacity:.6;font-size:.82rem;max-width:62rem}}
.cols{{display:grid;grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));gap:1.2rem;align-items:start}}
.col h3{{margin-top:0}}
.col p,.col ul{{margin:.2rem 0;font-size:.98rem}}
.col ul{{padding-left:1.1rem}}
.shots{{display:grid;grid-template-columns:repeat(auto-fit,minmax(13rem,1fr));gap:1rem;margin-top:.4rem}}
.shot figcaption{{font-size:.78rem;letter-spacing:.08em;text-transform:uppercase;opacity:.6;margin-bottom:.3rem}}
.shot img{{width:100%;border-radius:.6rem;border:1px solid #334155;display:block}}
.shot iframe.redesign{{width:100%;height:16rem;border-radius:.6rem;border:1px solid #334155;background:#fff;display:block}}
details.code{{margin-top:.6rem;font-size:.8rem;opacity:.85}}
details.code summary{{cursor:pointer;opacity:.7;letter-spacing:.05em;text-transform:uppercase;font-size:.72rem}}
details.code pre{{max-height:14rem;overflow:auto;background:#0f1b30;border:1px solid #1e293b;border-radius:.5rem;padding:.7rem;margin:.4rem 0 0}}
figure{{margin:0}}
blockquote{{margin:.3rem 0;padding:.5rem .9rem;border-left:3px solid #38bdf8;background:#0f1b30;border-radius:.35rem;font-size:.93rem}}
blockquote cite{{display:block;opacity:.6;font-size:.78rem;font-style:normal;margin-top:.3rem}}
table.impact{{border-collapse:collapse;font-size:.95rem;max-width:62rem}}
table.impact th,table.impact td{{text-align:left;padding:.4rem .8rem;border-bottom:1px solid #1e293b}}
.sev{{font-size:.72rem;padding:.1rem .5rem;border-radius:999px;border:1px solid #334155}}
.sev-critical{{background:#450a0a;border-color:#b91c1c;color:#fca5a5}}
.sev-high{{background:#431407;border-color:#c2410c;color:#fdba74}}
.sev-medium{{background:#422006;border-color:#a16207;color:#fde047}}
.sev-low{{background:#0f2942;border-color:#0369a1;color:#7dd3fc}}
.nav{{position:fixed;bottom:1.5rem;right:1.5rem;display:flex;gap:.5rem;z-index:10}}
.nav button{{background:#1e293b;color:#f1f5f9;border:1px solid #334155;border-radius:.5rem;padding:.5rem 1rem;cursor:pointer;font-size:1rem}}
.nav button:hover{{background:#334155}}
.counter{{position:fixed;bottom:1.5rem;left:1.5rem;opacity:.6;font-size:.9rem}}
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
        category = str(item.get("category") or "usability").replace("_", " ")
        issue_text = item.get("summary") or item.get("evidence") or ""
        root_cause = item.get("rootCause") or item.get("mechanism") or item.get("evidence") or ""
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
            caption = "Current design" if item.get("screenshotIsRegion", True) else "Current design (full page)"
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
                f'&middot; {escape(category)}</span>'
                f'<h2>{escape(item.get("title", "Finding"))}</h2>{affected}'
                f'<div class="cols">'
                f'<div class="col"><h3>{escape(issue_label)}</h3><p>{escape(str(issue_text))}</p></div>'
                + (f'<div class="col"><h3>Root cause analysis</h3><p>{escape(str(root_cause))}</p></div>'
                   if root_cause and root_cause != issue_text else "")
                + (f'<div class="col"><h3>Recommendations: design solutions</h3><ul>{changes}</ul></div>'
                   if changes else "")
                + quote_block
                + f'</div>{shots}{grounding}</section>')

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
