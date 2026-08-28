"""Local job executor implementing useful control-plane behavior without Jules.

The interface intentionally keeps execution behind persisted jobs and artifacts so a
JourneyTest worker can replace this development executor without changing clients.
"""
from __future__ import annotations

from html import escape
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
            evidence_language, journey_status = "observed", "completed"
            limitations = [
                "Findings are JourneyTest's own evidence-grounded verdict (blockers/uxFindings/"
                "suggestedImprovements/failed pass-criteria) from a real browser run against the "
                "target URL, not text inferred from the task description.",
                "Deep Eyeson visual pain-point resolution with element attribution "
                "(spec.md section 20) is not yet wired to live JourneyTest evidence: "
                "services/eyeson-worker's evidence analyzer still requires the native "
                "fixture engine's elementMap/behavior-transition evidence contract, which "
                "live JourneyTest runs do not yet produce.",
            ]
        else:
            findings = [{"severity": "medium", "category": "ux", "title": f"Validate task clarity: {task}",
                "summary": "", "evidence": "Inferred from the configured task; JOURNEY_WORKER_URL is not "
                           "configured for this deployment, so no live browser evidence was collected.",
                "source": "task_text"} for task in tasks]
            evidence_language, journey_status = "inferred", "configured"
            limitations = ["JOURNEY_WORKER_URL is not configured for this deployment; no live "
                           "browser evidence was collected, so these findings are inferred from "
                           "the configured task text alone."]
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
        if journeys and not findings:
            findings.append({"severity": "low", "category": "ux", "title": "No pain points detected",
                "summary": "JourneyTest's verdict reported no blockers, UX findings, or failed pass "
                           "criteria for the configured tasks.",
                "evidence": "See journey_outcome.runs[].verdict for the full per-run verdict.",
                "source": "verdict"})
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
        findings = "".join(f"<li><strong>{escape(item['title'])}</strong><br>{escape(item['evidence'])}</li>"
                           for item in report.get("critical_pain_points", [])) or "<li>No findings.</li>"
        return f"""<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>AUX UX report</title><style>body{{font:18px system-ui;margin:0;background:#101827;color:#f8fafc}}section{{min-height:90vh;padding:5vw;display:grid;align-content:center}}section:nth-child(even){{background:#172554}}h1{{font-size:clamp(2.5rem,7vw,6rem)}}li{{margin:1rem 0}}</style></head><body><section><h1>UX analysis</h1><p>{escape(report.get('url') or '')}</p><p>{escape(report.get('executive_summary') or '')}</p></section><section><h2>Critical pain points</h2><ul>{findings}</ul></section><section><h2>Evidence status</h2><p>{escape(report.get('evidence_language') or 'unknown')}</p><p>{escape(' '.join(report.get('limitations', [])))}</p></section></body></html>"""

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
