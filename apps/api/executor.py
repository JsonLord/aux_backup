"""Local job executor implementing useful control-plane behavior without Jules.

The interface intentionally keeps execution behind persisted jobs and artifacts so a
JourneyTest worker can replace this development executor without changing clients.
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

from .store import Store

from apps.api.model_routing import built_in_allowed, providers_for
from apps.api.model_settings import ROLE_VISION
from services.report_service import ReportAssembler
# Still called by the run half, or imported from here by name elsewhere. The
# rest of the moved helpers are reached through services.report_service.
from services.report_service.helpers import (  # noqa: F401
    _coverage_diagnostics,
    _evidence_reference_summary,
    _grey_at_luminance,
    _instrument_diagnostics,
    _is_run_diagnostic,
    _reads_as_praise,
    _reads_as_timeout,
    _stem,
    cited_captures,
    contrast_fix,
    download_name,
    plural,
    unresolvable_citations,
    verb,
)

class JobExecutor(ReportAssembler):
    # Bound, not defined here: a module function so the report helpers can
    # reach it without importing this module back. Same shape as _plural.
    _download_name = staticmethod(download_name)

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
                        f"{plural(len(missing), 'capture')} cited in this report {verb(len(missing), 'was', 'were')} not kept as artifacts in "
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
                    f"{plural(len(repeated_captures), 'full-page capture')} came back as one viewport band repeated "
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
        run_diagnostics = (_instrument_diagnostics(journeys)
                           + _coverage_diagnostics(journeys) + run_diagnostics)
        findings, unverified = self._drop_unverifiable_quotes(findings, self._visible_text_corpus(journeys))
        if unverified:
            quoted = "; ".join(f"{item['title']!r} (quoted {', '.join(repr(q) for q in item['quotes'])})"
                               for item in unverified)
            limitations.append(
                f"{plural(len(unverified), 'finding')} {verb(len(unverified), 'was', 'were')} discarded because it quoted on-page text that the "
                f"run's own element snapshots do not contain: {quoted}. Claims about literal visible text "
                "are checked against journeytest-core's snapshots before they are reported.")
        if run_diagnostics:
            limitations.append(
                f"{plural(len(run_diagnostics), 'run diagnostic')} "
                f"{verb(len(run_diagnostics), 'was', 'were')} recorded (the test harness itself failing, "
                "not the product): see run_diagnostics. They are excluded from the usability findings.")
        thoughts_by_persona = {persona.get("id"): self._persona_thoughts(journey)
                               for journey, persona in zip(journeys, personas) if persona.get("id")}
        persona_names = {persona.get("id"): (persona.get("persona") or {}).get("name") or persona.get("name") or persona.get("id")
                         for persona in personas}
        self._attach_persona_evidence(findings, thoughts_by_persona, persona_names)
        self._attach_verdict_screenshots(findings, journeys)
        self._attach_redesigns(findings, data.get("url"), self._providers_for(job, ROLE_VISION))
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

    @staticmethod
    def _providers_for(job: dict[str, Any], role: str) -> list[tuple[str, str, str]]:
        """What this job may run on, for one role.

        The control plane resolves and the rest receive: the report half and both
        workers are handed a chain rather than opening the settings store, so a
        service never reaches into the control plane's database (AGENTS.md: talk
        over versioned HTTP contracts, job ids and artifacts).
        """
        return providers_for(job.get("workspace_id") or "local", role,
                             built_in_allowed=built_in_allowed(job))

    def _ui_adaptation(self, job: dict[str, Any]) -> str:
        data = job["metadata"]
        title, request = data.get("title", "Responsive UX prototype"), data.get("request", "Improve clarity and responsiveness")
        html = self._generate_ui_html(title, request, data.get("url"), data.get("previous_html"),
                                      self._providers_for(job, ROLE_VISION))
        if html:
            return html
        # Deterministic offline fallback (no OPENAI_API_KEY/BLABLADOR_API_KEY
        # configured, or the LLM call failed): a real generation was attempted
        # and could not be produced, not a claim of a designed prototype.
        return f"""<!doctype html><html><head><meta name=viewport content='width=device-width,initial-scale=1'><style>body{{font:16px system-ui;margin:auto;max-width:72rem;padding:clamp(1rem,4vw,4rem);color:#18202a}}main{{display:grid;gap:1rem}}section{{padding:1.5rem;border:1px solid #ccd5df;border-radius:1rem}}@media(min-width:48rem){{main{{grid-template-columns:2fr 1fr}}}}</style></head><body><h1>{escape(title)}</h1><main><section><h2>Adaptation request</h2><p>{escape(request)}</p></section><section><h2>Offline fallback</h2><p>No LLM credentials are configured (or generation failed), so this is a static placeholder rather than a generated prototype.</p></section></main></body></html>"""

    @staticmethod
    def _generate_ui_html(title: str, request: str, url: str | None, previous_html: str | None,
                          providers: list[tuple[str, str, str]] | None = None) -> str | None:
        """Ask the configured OpenAI-compatible model for a real, self-contained
        HTML prototype implementing `request`, optionally revising `previous_html`
        for iterative chat-based adaptation. Returns None (caller falls back) if no
        LLM credentials are configured or the call fails after retries -- this is
        never faked with a fixed template that ignores the actual request."""
        # "Is there anything this caller may call?" rather than "is a key set in
        # the environment?" -- a workspace with its own provider configured has a
        # model available whether or not the deployment does.
        if providers is not None and not providers:
            return None
        try:
            from services.persona_service.semantic import DirectLLMSemanticEngine
            engine = DirectLLMSemanticEngine(providers=providers)
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
