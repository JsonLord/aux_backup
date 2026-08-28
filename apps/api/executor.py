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
            artifacts = [self.store.create_artifact({"session_id": job["session_id"], "kind": kind,
                "content_type": content_type, "content": content,
                "metadata": {"job_id": job_id, "schema_version": "1.0", "download_name": self._download_name(kind, job_id)}})
                for kind, content_type, content in outputs]
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
        if worker_url:
            for persona in personas:
                payload = json.dumps({"runId": f"{job['job_id']}_{persona.get('id', len(journeys))}", "url": data.get("url"), "tasks": tasks, "profile": persona}).encode()
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
                    raise RuntimeError(f"Journey worker rejected run ({error.code}): {detail}") from error
        if worker_url:
            findings = self._pain_points_from_journeys(journeys)
            vision_findings, vision_error = self._vision_critique_journeys(journeys, tasks, personas, data.get("url"))
            findings.extend(vision_findings)
            evidence_language, journey_status = "observed", "completed"
            limitations = [
                "Findings are JourneyTest's own evidence-grounded verdict (blockers/uxFindings/"
                "suggestedImprovements/failed pass-criteria) from a real browser run against the "
                "target URL, not text inferred from the task description.",
            ]
            if vision_findings:
                limitations.append(
                    "Findings tagged source=eyeson-vision are a real vision-model critique of actual "
                    "JourneyTest screenshots (grounded against a small curated UX-heuristics corpus), "
                    "not the deterministic behavior-transition pain-point model in spec.md section 20 "
                    "(that model requires the native fixture engine's elementMap/behavior-transition "
                    "evidence contract, which live JourneyTest runs do not produce)."
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
        return {"schema_version": "1.0", "mode": "user_journey", "url": data.get("url"), "executive_summary": f"Prepared {len(tasks)} task scenarios for {len(personas)} synthetic users.", "synthetic_users": personas, "persona_artifacts": persona_artifacts, "journey_outcome": {"status": journey_status, "tasks": tasks, "runs": journeys}, "critical_pain_points": findings, "evidence_language": evidence_language, "limitations": limitations}

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

    @classmethod
    def _vision_critique_journeys(cls, journeys: list[dict[str, Any]], tasks: list[str],
                                   personas: list[dict[str, Any]], url: str | None) -> tuple[list[dict[str, Any]], str | None]:
        """Stage 2 of the two-stage UX feedback model (spec.md sections 19-21):
        independent of whether JourneyTest's own task-completion verdict (stage 1,
        _pain_points_from_journeys) found a blocker, ask a real vision model
        (services/eyeson-worker's new /v1/journey-evidence-analyses) to critique a
        bounded sample of the run's actual screenshots, referenced against
        journeytest-core's own semantic element snapshots so a finding can be tied
        to a specific place on the screenshot (cropped into `screenshotCrop`),
        grounded against a curated UX-heuristics corpus. Best-effort: a failure
        here never fails the run -- stage 1's findings still stand on their own.
        """
        worker_url = os.getenv("EYESON_WORKER_URL", "http://127.0.0.1:8081")
        try:
            limit = int(os.getenv("EYESON_VISION_SCREENSHOT_LIMIT", "3"))
        except (TypeError, ValueError):
            limit = 3
        task_summary = "; ".join(tasks)
        findings: list[dict[str, Any]] = []
        attempted, last_error = False, None
        for journey, persona in zip(journeys, personas):
            artifacts = journey.get("artifacts") or {}
            screenshots, snapshots = artifacts.get("screenshots") or [], artifacts.get("snapshots") or []
            if not screenshots:
                continue
            persona_summary = persona.get("minibio") or (persona.get("persona") or {}).get("name")
            for screenshot_path in cls._evenly_spaced(screenshots, max(1, limit)):
                attempted = True
                try:
                    image_bytes = Path(screenshot_path).read_bytes()
                except OSError as error:
                    last_error = str(error)
                    continue
                elements = cls._elements_for_screenshot(screenshot_path, snapshots)
                payload = json.dumps({
                    "imageBase64": base64.b64encode(image_bytes).decode("ascii"),
                    "elements": elements, "url": url, "task": task_summary, "personaSummary": persona_summary,
                }).encode()
                call = request.Request(f"{worker_url.rstrip('/')}/v1/journey-evidence-analyses",
                    data=payload, headers={"content-type": "application/json"}, method="POST")
                try:
                    with request.urlopen(call, timeout=float(os.getenv("EYESON_VISION_TIMEOUT", "90"))) as response:
                        result = json.loads(response.read())
                except (request.HTTPError, OSError, ValueError) as error:
                    last_error = str(error)
                    continue
                for item in result.get("findings", []):
                    crop = cls._crop_element_data_uri(image_bytes, item.get("box"))
                    grounding_refs = ((item.get("grounding") or {}).get("references")) or []
                    evidence_parts = [f"screenshot: {screenshot_path}"]
                    if item.get("elementSelector"):
                        evidence_parts.append(f"element: {item['elementSelector']}")
                    if grounding_refs:
                        evidence_parts.append("grounded in " + "; ".join(
                            f"{ref.get('source')}: {ref.get('principle') or ref.get('title')}" for ref in grounding_refs))
                    finding = {
                        "severity": item.get("severity", "medium"), "category": item.get("category", "usability"),
                        "title": item.get("title", "Vision critique finding"), "summary": item.get("description", ""),
                        "recommendation": item.get("recommendation"), "evidence": "; ".join(evidence_parts),
                        "source": "eyeson-vision", "runId": journey.get("runId"), "personaId": persona.get("id"),
                    }
                    if crop:
                        finding["screenshotCrop"] = crop
                    findings.append(finding)
        if not attempted:
            return [], None
        return cls._dedupe_vision_findings(findings), (last_error if not findings and last_error else None)

    _SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

    @classmethod
    def _dedupe_vision_findings(cls, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The same real issue (e.g. a page-wide rendering bug) can legitimately
        show up on more than one sampled screenshot from the same run, producing
        near-identical findings that read as noise rather than confirmation.
        Collapse findings sharing a (title, category) key -- keeping the highest
        severity and first crop seen, and folding every occurrence's evidence
        into one list -- instead of listing the same finding once per screenshot."""
        merged: dict[tuple[str, str], dict[str, Any]] = {}
        order: list[tuple[str, str]] = []
        for finding in findings:
            key = (finding["title"].strip().lower(), finding.get("category", ""))
            if key not in merged:
                merged[key] = {**finding, "evidence": [finding["evidence"]]}
                order.append(key)
                continue
            existing = merged[key]
            existing["evidence"].append(finding["evidence"])
            if cls._SEVERITY_RANK.get(finding.get("severity"), 0) > cls._SEVERITY_RANK.get(existing.get("severity"), 0):
                existing["severity"] = finding["severity"]
            if not existing.get("screenshotCrop") and finding.get("screenshotCrop"):
                existing["screenshotCrop"] = finding["screenshotCrop"]
        deduped = []
        for key in order:
            finding = merged[key]
            occurrences = finding.pop("evidence")
            finding["evidence"] = occurrences[0] if len(occurrences) == 1 else \
                f"seen on {len(occurrences)} screenshots -- " + " | ".join(occurrences)
            deduped.append(finding)
        return deduped

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
    def _download_name(kind: str, job_id: str) -> str:
        extension = {"ux.report": "json", "ux.presentation": "html", "journey.log": "json",
                     "ui.prototype": "html", "browser.screenshot": "png", "browser.snapshot": "json",
                     "browser.ui-change": "json", "browser.video": "webm"}[kind]
        return f"{kind.replace('.', '-')}-{job_id}.{extension}"

    @staticmethod
    def _presentation(report: dict[str, Any]) -> str:
        def render_finding(item: dict[str, Any]) -> str:
            image = (f'<img src="{escape(item["screenshotCrop"], quote=True)}" alt="Screenshot region for this finding" '
                     'style="max-width:min(100%,420px);border-radius:.5rem;border:1px solid #334155;margin-top:.5rem">'
                     if item.get("screenshotCrop") else "")
            recommendation = (f'<p style="opacity:.85"><strong>Recommendation:</strong> {escape(item["recommendation"])}</p>'
                              if item.get("recommendation") else "")
            badge = escape(str(item.get("severity", "")).upper())
            category = escape(str(item.get("category", "")))
            return (f'<li><strong>[{badge}] {escape(item["title"])}</strong> '
                    f'<span style="opacity:.6">({category})</span><br>'
                    f'{escape(item.get("summary") or item.get("evidence") or "")}{recommendation}{image}</li>')

        findings = "".join(render_finding(item) for item in report.get("critical_pain_points", [])) or "<li>No findings.</li>"
        return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>AUX UX report</title><style>body{{font:18px system-ui;margin:0;background:#101827;color:#f8fafc}}section{{min-height:90vh;padding:5vw;display:grid;align-content:center}}section:nth-child(even){{background:#172554}}h1{{font-size:clamp(2.5rem,7vw,6rem)}}li{{margin:1.5rem 0}}</style></head><body><section><h1>UX analysis</h1><p>{escape(report.get('url') or '')}</p><p>{escape(report.get('executive_summary') or '')}</p></section><section><h2>Critical pain points</h2><ul>{findings}</ul></section><section><h2>Evidence status</h2><p>{escape(report.get('evidence_language') or 'unknown')}</p><p>{escape(' '.join(report.get('limitations', [])))}</p></section></body></html>"""

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
                        outputs.append((kind, content_type, path.read_bytes()))
        return outputs
