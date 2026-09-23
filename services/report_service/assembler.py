"""Turning a finished run into findings, a report and a deck.

Moved verbatim from apps/api/executor.py (BE-2): every method and class
constant here was a member of JobExecutor and is unchanged. It stays a class
rather than becoming module functions so the move is provably a move -- every
`cls.` and `self.` reference still resolves, through the MRO instead of within
one class body. JobExecutor inherits it.

Two references still point back at the run half -- `cls._vision_timeout()` and
`cls._worker_error()`, both about talking to the vision service. They resolve
through the subclass. Turning them into arguments is a design change, not a
move, so it is not done here.
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



from services.report_service.helpers import (  # noqa: F401  (used by moved code)
    download_name,
    _reads_as_timeout,
    _reads_as_praise,
    _stem,
    _is_run_diagnostic,
    _instrument_diagnostics,
    plural,
    verb,
    _coverage_diagnostics,
    _capture_name,
    _evidence_reference_summary,
    _grey_at_luminance,
    contrast_fix,
    cited_captures,
    unresolvable_citations,
    _CITED_CAPTURE,
    _CRITERION_TITLES,
    _FAIL_CRITERION_IDS,
    _INSTRUMENT_FAILURES,
    _JOURNEYTEST_SEVERITY_MAP,
    _MET_CRITERION_TITLES,
    _NAMED_CONTROL,
    _PRAISE_MARKERS,
    _PROBLEM_MARKERS,
    _PROSE_STOPWORDS,
    _QUALITY_ADJECTIVES,
    _QUIET_BROWSER_EVENTS,
    _QUOTED_LABEL,
    _RUN_DIAGNOSTIC_PATTERNS,
    _SIBILANTS,
    _SUFFIXES,
    _TITLE_STOPWORDS,
)


class ReportAssembler:
    """The report half of JobExecutor. Mixed in, not instantiated alone."""


    @classmethod
    def assemble_report(cls, *, url: str, tasks: list[str], personas: list[dict[str, Any]],
                        persona_artifacts: list[str], journeys: list[dict[str, Any]],
                        worker_configured: bool, job_id: str | None = None,
                        vision: list[tuple[str, str, str]] | None = None,
                        redesign: list[tuple[str, str, str]] | None = None,
                        send_vision_options: bool = False,
                        redact_selectors: list[str] | None = None) -> dict[str, Any]:
        """Build a ux.report from journeys that have already been dispatched.

        RUN-0: extracted from JobExecutor._combined_test, which still owns
        dispatch (persona/task loading, session/credential/hat setup, the
        concurrent pool of live worker calls) and now only resolves the handful
        of `job`/`data` reads this body used to make directly -- `job_id`,
        `url`, the vision/redesign provider chains, and whether a `send_options`
        vision call is allowed -- into plain arguments, then calls this. Nothing
        here reads `job`, `data`, `self.store`, or makes a job-scoped decision
        of its own: every `self.` became `cls.`, unchanged otherwise, so this is
        provably the same code as before the move (BE-2's own rule for a split
        like this).

        This is what RUN-3's offline replay calls directly, with
        `vision=redesign=[]` and `worker_configured=True`, so a saved run's
        report can be rebuilt from `journeys`/`personas` alone, no live worker
        and no model traffic: `_collect_vision_pain_points`/`_attach_redesigns`
        treat an empty provider list as "nothing configured" the same way a live
        job with no vision worker does.

        `redact_selectors` defaults to `[]` rather than `None` reaching the
        calls below, matching `_combined_test`'s own resolution (a signed-out
        run computes `[]`, never `None`).
        """
        vision = vision or []
        redesign = redesign if redesign is not None else vision
        redact_selectors = redact_selectors or []
        if worker_configured:
            findings = cls._pain_points_from_journeys(journeys, job_id)
            # What the persona's eyes made of the page. Two finding classes that
            # exist nowhere else, because no check against the DOM can produce
            # either -- see _pain_points_from_perception.
            findings += cls._pain_points_from_perception(journeys)
            # CAP-0: whether this run produced a "never looked at" finding, so the
            # limitations note below can say what changed about that class rather
            # than staying silent about it.
            has_missed_findings = any(finding.get("source") == "perception.missed" for finding in findings)
            # What the page looked like it would do and then did not. First-hand,
            # falsifiable, and invisible to every other source here.
            findings += cls._pain_points_from_expectations(journeys)
            # D7: controls close enough to read as one group that do different
            # kinds of things -- a relationship between elements, not a property
            # of one, so no per-element check above finds it.
            findings += cls._grouped_controls_with_differing_actions(journeys)
            # D4 (partial): a deterministic sweep for targets below the WCAG
            # minimum size, so coverage of this one does not depend on a persona
            # stumbling onto it. See _small_touch_targets for why the other four
            # checks this section named (heading order, alt text, form labels,
            # focus visibility) are not attempted here.
            findings += cls._small_touch_targets(journeys)
            cohort_runs, screenshot_bytes, raw_strengths, vision_error, repeated_captures = \
                cls._collect_vision_pain_points(
                    journeys, tasks, personas, url,
                    vision,
                    send_options=send_vision_options,
                    redact_selectors=redact_selectors)
            vision_findings = cls._synthesize_pain_points(cohort_runs, screenshot_bytes) if cohort_runs else []
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
            tempered = (cls._temper_contradicted_findings(vision_findings, journeys)
                        + cls._cap_claimed_impact(vision_findings, journeys))
            findings.extend(vision_findings)
            preserve = (cls._merge_strengths(raw_strengths + cls._praise_from_verdicts(journeys)
                                              + cls._praise_as_strengths(vision_praise))
                        + cls._preserved_from_verdicts(journeys)
                        # D9: elements_to_preserve grounded in a *met* expectation --
                        # a control that did exactly what a visitor expected, first
                        # try -- not generic praise. A review that only lists faults
                        # is half a review.
                        + cls._preserved_from_met_expectations(journeys))
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
            if has_missed_findings:
                # Said explicitly, in both directions: before CAP-0 the scan had no
                # memory between HTTP calls, so it re-fixated the same few elements
                # on every step and "on screen and never looked at" partly measured
                # that amnesia rather than the page's prominence
                # (docs/next-cycle-worksheet.md). This run's scan carries a per-run
                # memory (alreadySeen), so this class means what it says here; a
                # report from before this change should be read with that caveat.
                limitations.append(
                    "This run's scan remembers what each persona already looked at earlier in "
                    "the same run, so findings below titled \"On screen and never looked at\" "
                    "reflect the page's prominence rather than the scan re-fixating the same "
                    "few elements on every step. Reports produced before this change did not "
                    "have that memory and should be read with that caveat."
                )
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
        if worker_configured and not findings:
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
        findings = cls._merge_similar_findings([finding for finding in findings if finding not in run_diagnostics])
        # Added after the split, not before: an instrument failure is a diagnostic by
        # construction and must never be merged into, or dropped by, the usability
        # findings it is reported alongside.
        run_diagnostics = (_instrument_diagnostics(journeys)
                           + _coverage_diagnostics(journeys) + run_diagnostics)
        findings, unverified = cls._drop_unverifiable_quotes(findings, cls._visible_text_corpus(journeys))
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
        thoughts_by_persona = {persona.get("id"): cls._persona_thoughts(journey)
                               for journey, persona in zip(journeys, personas) if persona.get("id")}
        # RPT-2/B3: one persona's expectations across the whole run, summarised
        # into a stated model of what they thought the product was.
        mental_models_by_persona = {persona.get("id"): cls._persona_mental_model(journey)
                                    for journey, persona in zip(journeys, personas) if persona.get("id")}
        persona_names = {persona.get("id"): (persona.get("persona") or {}).get("name") or persona.get("name") or persona.get("id")
                         for persona in personas}
        cls._attach_persona_evidence(findings, thoughts_by_persona, persona_names)
        # E7: continue the vision findings' own evidence-marker numbering rather
        # than restarting at 1, so no two region crops in one report share a digit.
        # Read off `findings` itself, not `vision_findings` -- the latter is only
        # ever assigned when a worker is configured, and this call runs either way.
        next_evidence_number = 1 + max((item.get("evidenceNumber") or 0 for item in findings), default=0)
        cls._attach_verdict_screenshots(findings, journeys, redact_selectors=redact_selectors,
                                         start_evidence_number=next_evidence_number)
        # BE-3: every Python-side model call this report itself makes while
        # building the redesign panels, for _model_usage_summary below.
        redesign_usage: list[dict[str, Any]] = []
        cls._attach_redesigns(findings, url, redesign,
                               usage_sink=redesign_usage)
        # F8: after screenshots are attached (their filenames are the step index
        # this reads), so findings accumulate into the story of the run instead
        # of a severity-shuffled grab-bag. Severity still governs impact_analysis's
        # own "what to fix first" ordering below, untouched by this.
        findings = cls._order_by_step(findings)
        # RPT-3: every finding is a falsifiable prediction -- stated per finding
        # so closing the loop needs no human judgement call about what "fixed"
        # would look like, only a re-run to check it against the fixed page.
        for finding in findings:
            retest = cls._retest_prediction(finding, persona_names, tasks)
            if retest:
                finding["retest"] = retest
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
        # A9: model calls at temperature > 0 are not reproducible byte-for-byte --
        # only a persona's disposition (its compiled behavior/ability profile) is,
        # not its exact wording on a re-run. Stated once, when there was live model
        # traffic to say it about.
        model_usage = cls._model_usage_summary(journeys, redesign_usage)
        if model_usage:
            limitations.append(
                "This run's model calls used temperature > 0 (personaActor.js's acting/reflection calls, "
                "0.7); re-running the same profile against the same page will not reproduce this run's "
                "persona quotes word for word. What is reproducible is the persona's disposition -- the "
                "compiled behavior and ability profile a re-run is given -- not its exact phrasing. See "
                "model_usage for what this run actually cost, by role, and which providers served it."
            )
        return {"schema_version": "1.1", "mode": "user_journey", "url": url,
                "executive_summary": cls._executive_summary(url, tasks, personas,
                                                             findings, preserve, journeys),
                "synthetic_users": personas, "persona_artifacts": persona_artifacts,
                "journey_outcome": {"status": journey_status, "tasks": tasks, "runs": journeys},
                # Which providers actually served this report. A run served by the
                # fallback is a run whose reproducibility claim is different, and a
                # reader cannot weigh that unless it is stated. Host and model only.
                "served_by": cls._served_by(journeys),
                # BE-3: what this run actually cost -- tokens and wall time, by
                # role -- and A9's model/provider naming, both from the same record.
                "model_usage": model_usage,
                "critical_pain_points": findings,
                "run_diagnostics": run_diagnostics,
                "flow_groups": cls._flow_groups(findings, tasks),
                "elements_to_preserve": preserve,
                "impact_analysis": cls._impact_analysis(findings, personas),
                # A2: task success, actions taken, expectations met vs missed --
                # the hit rate a report that only shows misses would otherwise hide.
                "scorecard": cls._run_scorecard(journeys, personas, persona_names),
                "persona_narration": [{"personaId": persona_id, "personaName": persona_names.get(persona_id, persona_id),
                                       "thoughts": thoughts,
                                       # B3: "" when there were too few expectations to support a
                                       # stated pattern -- an absent model is honest, a guessed one is not.
                                       "mentalModel": mental_models_by_persona.get(persona_id, "")}
                                      for persona_id, thoughts in thoughts_by_persona.items()],
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
            key = ReportAssembler._flow_label(finding)
            group = groups.setdefault(key, {"flow": key, "category": finding.get("category"), "findings": []})
            group["findings"].append(finding.get("title"))
        ordered = sorted(groups.values(), key=lambda item: -len(item["findings"]))
        for index, group in enumerate(ordered, start=1):
            group["section"] = f"02.{index}"
            group["findingCount"] = len(group["findings"])
        return ordered

    # F8: the leading zero-padded number in a capture's own filename is a real,
    # verifiable step index -- both this codebase's own captures
    # (personaDirector.js's keepSeenImage/keepRefusedCapture, "003-as-they-saw-
    # it.jpg") and journeytest-core's own action captures ("001-click-e21-
    # after.png") use it, so reading it back is not a guess at an external
    # format, only at one this codebase already relies on elsewhere
    # (_elements_for_screenshot pairs screenshots to snapshots by the same stem).
    _LEADING_STEP = re.compile(r"^(\d+)")

    @classmethod
    def _finding_step_index(cls, finding: dict[str, Any]) -> int | None:
        for key in ("evidenceScreenshot", "screenshotRef"):
            ref = finding.get(key)
            if ref:
                match = cls._LEADING_STEP.match(Path(ref).stem)
                if match:
                    return int(match.group(1))
        return None

    @classmethod
    def _retest_prediction(cls, finding: dict[str, Any], persona_names: dict[str, str],
                           tasks: list[str]) -> str:
        """RPT-3: every finding here is a falsifiable prediction -- fix this, and
        an identifiable persona's expectation should hold on the next run. No
        human review closes that loop; a stated, checkable prediction is the
        thing to be known for, per finding, not asserted once for the report as
        a whole.

        Returns "" when no persona can be attributed to the finding (the
        placeholder "No pain points detected"/"Journey ended early" entries, and
        anything a source built with no personaId) -- there is nobody to re-run
        it against, so nothing here would be falsifiable.

        Deliberately does not attempt the "re-run it against the fixed page"
        half of this section on its own: that is a live browser run against a
        target this codebase cannot reach from a report-generation call, and
        doing so would need its own job type and a real target to verify
        against, not something this method can respond for.
        """
        persona_ids = finding.get("affectedPersonaIds") or (
            [finding["personaId"]] if finding.get("personaId") else [])
        names = [persona_names.get(pid, pid) for pid in persona_ids if pid]
        if not names:
            return ""
        who = names[0] if len(names) == 1 else f"each of the {plural(len(names), 'affected persona')}"
        task = tasks[0] if len(tasks) == 1 else ("one of the configured tasks" if tasks else "the same task")
        title = str(finding.get("title") or "this issue").strip()
        return (f"Falsifiable: on a re-run against the fixed page, {who} attempting "
                f"“{task}” should no longer produce “{title}”. If it "
                f"does, the fix did not hold.")

    @classmethod
    def _order_by_step(cls, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """So findings accumulate into a story -- the order a reader would have
        hit them in, walking the run themselves -- rather than a grab-bag severity
        cannot arrange into one. Severity is not involved here at all; it governs
        only `_impact_analysis`'s "what to fix first" ordering, a separate list.

        A finding with no derivable step (most verdict-level findings: a blocker
        or a failed criterion is a claim about the whole run, not one screenshot)
        sinks to the end, in whatever order it already had -- `sorted` is stable,
        so ties never reshuffle findings that came from the same source.
        """
        with_index = [(cls._finding_step_index(finding), finding) for finding in findings]
        return [finding for _, finding in sorted(with_index, key=lambda pair: (pair[0] is None, pair[0] or 0))]

    @staticmethod
    def _served_by(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The distinct providers that answered across a cohort, in run order.

        `servedBy` is set by the worker and carries an endpoint and a model but
        never a key (services/journey-worker/node/src/journeytest.js). Runs that
        never reached a model contribute nothing rather than a blank row.

        RUN-0: moved here from `apps/api/executor.py` (unchanged apart from
        the move) -- it was a third back-reference from `assemble_report`
        into the run half that BE-2's own docstring did not name, found
        while making `ReportAssembler.assemble_report()` callable standalone
        for RUN-3's offline replay. It belongs here on its own terms too: it
        reads only `journeys` and summarises a report field, the same shape
        as `_model_usage_summary` beside it, not a run-half concern like
        `_vision_timeout`/`_worker_error` (still genuinely back-references,
        since they read environment and format a live HTTP error).
        """
        seen, served = set(), []
        for journey in journeys:
            entry = journey.get("servedBy") or {}
            key = (entry.get("endpoint"), entry.get("model"))
            if not entry.get("endpoint") or key in seen:
                continue
            seen.add(key)
            served.append({"endpoint": entry["endpoint"], "model": entry.get("model"),
                           "movedFromPrimary": bool(entry.get("movedFromPrimary"))})
        return served

    @staticmethod
    def _model_usage_summary(journeys: list[dict[str, Any]], extra_usage: list[dict[str, Any]] | None = None
                             ) -> dict[str, Any] | None:
        """BE-3: what this run actually cost, broken down by role, and which
        providers served it. Two funnels feed this -- every Node-side model
        call the run made (`journey["modelUsage"]`, from personaActor.js's
        `completion()`) and every Python-side call this report itself made
        while building the redesign panels (`extra_usage`, from
        DirectLLMSemanticEngine._complete()) -- because there are exactly two
        places a model call can originate from. Returns None when neither
        funnel recorded anything, rather than a report claiming a cost of
        zero for calls it simply never measured.
        """
        calls = list(extra_usage or [])
        for journey in journeys:
            calls.extend(journey.get("modelUsage") or [])
        if not calls:
            return None
        by_role: dict[str, dict[str, Any]] = {}
        providers: set[tuple[str, str]] = set()
        total_wall_ms = 0
        total_prompt_tokens = 0
        total_completion_tokens = 0
        any_tokens = False
        for call in calls:
            role = str(call.get("role") or "unspecified")
            bucket = by_role.setdefault(role, {"calls": 0, "wallMs": 0, "promptTokens": 0, "completionTokens": 0})
            bucket["calls"] += 1
            wall_ms = call.get("wallMs") or 0
            bucket["wallMs"] += wall_ms
            total_wall_ms += wall_ms
            prompt_tokens, completion_tokens = call.get("promptTokens"), call.get("completionTokens")
            if isinstance(prompt_tokens, (int, float)) or isinstance(completion_tokens, (int, float)):
                any_tokens = True
                bucket["promptTokens"] += prompt_tokens or 0
                bucket["completionTokens"] += completion_tokens or 0
                total_prompt_tokens += prompt_tokens or 0
                total_completion_tokens += completion_tokens or 0
            if call.get("endpoint") and call.get("model"):
                providers.add((str(call["endpoint"]), str(call["model"])))
        return {
            "totalCalls": len(calls),
            "totalWallMs": total_wall_ms,
            # None rather than 0 when nothing in this run's chain ever returned a
            # usage object -- a real zero and "never measured" are different claims.
            "totalPromptTokens": total_prompt_tokens if any_tokens else None,
            "totalCompletionTokens": total_completion_tokens if any_tokens else None,
            "byRole": by_role,
            "providers": [{"endpoint": endpoint, "model": model} for endpoint, model in sorted(providers)],
        }

    @staticmethod
    def _run_scorecard(journeys: list[dict[str, Any]], personas: list[dict[str, Any]],
                       persona_names: dict[str, str]) -> dict[str, Any]:
        """RPT-4/A2: task success, actions taken, where each run stopped, and
        expectations met vs missed -- per persona and rolled up. A report that
        only shows misses hides its own hit rate; this states it, from the same
        `matched` field the broken-promise findings already draw the misses from,
        so the two can never disagree about what a "miss" is."""
        rows = []
        total_met, total_missed = 0, 0
        for journey, persona in zip(journeys, personas):
            persona_id = persona.get("id")
            verdict = journey.get("verdict") or {}
            timeline = journey.get("timeline") or []
            actions = sum(1 for event in timeline if event.get("type") == "persona.expectation")
            met = sum(1 for event in timeline if event.get("type") == "persona.reflection"
                     and str((event.get("data") or {}).get("matched") or "").lower() == "yes")
            missed = sum(1 for event in timeline if event.get("type") == "persona.reflection"
                        and str((event.get("data") or {}).get("matched") or "").lower() == "no")
            total_met += met
            total_missed += missed
            rows.append({
                "personaId": persona_id, "personaName": persona_names.get(persona_id, persona_id),
                "runId": journey.get("runId"),
                "taskSuccess": verdict.get("status") == "passed",
                "verdictStatus": verdict.get("status") or "unknown",
                "actionsTaken": actions, "expectationsMet": met, "expectationsMissed": missed,
                # The run's own account of why it ended, whatever that was --
                # not re-derived, so this can never disagree with the verdict.
                "stoppedBecause": verdict.get("summary") or "",
            })
        total_expectations = total_met + total_missed
        return {
            "runs": rows,
            "tasksSucceeded": sum(1 for row in rows if row["taskSuccess"]),
            "tasksAttempted": len(rows),
            "expectationsMet": total_met, "expectationsMissed": total_missed,
            # None rather than a fabricated 0/0 -> 0% when no expectation was ever
            # recorded at all (an empty timeline, or a director that records none).
            "expectationsMetRate": round(total_met / total_expectations, 2) if total_expectations else None,
        }

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
                and str(finding.get("severity")) not in ReportAssembler._NOT_A_PROBLEM]
        noted = [finding for finding in findings
                 if str(finding.get("severity")) in ReportAssembler._NOT_A_PROBLEM]
        blocking = [finding for finding in real
                    if str(finding.get("severity")) in {"critical", "high"}]

        # F1: lead with the judgement, not the method. A reader who stops after
        # one sentence should still know what works, where the product loses
        # people, and the one thing to change -- the counts and the "N synthetic
        # users attempted M tasks" scaffolding that used to open this are true of
        # almost any report and tell a reader nothing they can act on; they now
        # sit underneath the judgement instead of in front of it.
        judgement = []
        worst = (blocking or real)
        if worst:
            flow = ReportAssembler._flow_label(worst[0])
            judgement.append(f"The one thing to change: {worst[0].get('title')}"
                             + (f", where it loses people at {flow}." if flow else "."))
        if preserve:
            judgement.append(f"What works: {preserve[0].get('title')}.")
        if not judgement:
            judgement.append("No usability issues were identified against the configured tasks.")

        parts = list(judgement)
        parts.append(f"{plural(len(personas), 'synthetic user')} attempted {plural(len(tasks), 'task')} "
                     f"against {url or 'the target site'}.")
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
                f"{len(cut_short)} of those runs stopped early and did not finish the tasks"
                + (f" -- one got {plural(steps, 'action')} in" if len(cut_short) == 1 and steps else "")
                + ", so what follows is what was seen before that, not a full review.")
        parts.append(f"{plural(len(real), 'usability issue')} {verb(len(real), 'was', 'were')} identified"
                     + (f", {len(blocking)} of them high-severity or blocking." if blocking else "."))

        unreadable = [f for f in real if f.get("source") == "perception.notPerceived"]
        missed = [f for f in real if f.get("source") == "perception.missed"]
        if unreadable:
            parts.append(f"{plural(len(unreadable), 'element')} {verb(len(unreadable), 'is', 'are')} present in the page but not legible "
                         "once these users' eyesight is applied to what was actually drawn.")
        if missed:
            parts.append(f"{plural(len(missed), 'thing')} a visitor came for {verb(len(missed), 'was', 'were')} readable and on screen, "
                         "and were never looked at -- a prominence problem rather than a wording one.")
        if noted:
            # Said, and deliberately not counted: the page is compliant in these
            # places and one unusual profile had trouble, which is worth knowing
            # and is not a defect.
            parts.append(f"{plural(len(noted), 'further observation')} {verb(len(noted), 'applies', 'apply')} to one unusual profile each "
                         "rather than to the site.")
        if preserve:
            parts.append(f"{plural(len(preserve), 'design decision')} {verb(len(preserve), 'is', 'are')} working and should be preserved.")
        return " ".join(parts)

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
        return acuity <= ReportAssembler._RARE_ACUITY or contrast <= ReportAssembler._RARE_CONTRAST

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
    # A finding claiming the capture ran out before the content did.
    _CLAIMS_CUT_OFF = re.compile(
        r"\bcut off\b|\bcut-off\b|\bcropped\b|\btruncated\b|\bclipped\b"
        r"|\bpartially (?:visible|shown|hidden)\b|\bruns? off the (?:screen|page|edge)\b", re.I)
    # A finding claiming the type is below what a person can read.
    _CLAIMS_TINY_TEXT = re.compile(
        r"\btext is too small\b|\btoo small to read\b|\btiny (?:text|type|font)\b"
        r"|\bfont size is too small\b|\billeg(?:ible|ibly) small\b|\bsmall(?:er)? than "
        r"(?:\d+px|readable)\b", re.I)
    # A finding claiming stretches of the page hold nothing.
    _CLAIMS_EMPTY_SECTIONS = re.compile(
        r"\bempty (?:section|sections|space|area|areas|region|regions|band|bands)\b"
        r"|\bblank (?:section|sections|space|area|areas|region|regions)\b"
        r"|\bmassive (?:empty|blank|white)\b|\blarge (?:empty|blank) (?:vertical )?(?:space|areas?)\b",
        re.I)
    # Below this, type genuinely is small enough that a reader can complain about
    # it. Not a judgement about any particular pair of eyes -- the perception
    # service makes those, per persona -- but the floor under which the claim is
    # at least about something real.
    _SMALL_TYPE_PX = 12.0

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

        Five of its claims are checkable against what the run itself recorded, and
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
                        f"{plural(len(captures), 'capture')} of this run, so nothing on the page was "
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
        # Nothing is cut off if nothing ran past the edge of the capture. The
        # perception service measures exactly this, per element, on every capture:
        # a box that leaves the frame is clipped, and it says how many did.
        if cls._CLAIMS_CUT_OFF.search(text):
            measured = cls._captures_measured(journeys)
            if measured and all(int(item.get("clipped") or 0) == 0 for item in measured):
                return ("the run measured every element as falling inside the capture on all "
                        f"{plural(len(measured), 'capture')} of this run, so nothing on the page "
                        "was cut off")
        # Type is not too small to read if the smallest type measured is not
        # small. The walk reads the computed font size off every element it
        # reports, so this is the page's own number, not an impression of one.
        if cls._CLAIMS_TINY_TEXT.search(text):
            sizes = [float(item.get("smallestFontPx") or 0) for item in cls._captures_measured(journeys)]
            sizes = [size for size in sizes if size]
            if sizes and min(sizes) >= cls._SMALL_TYPE_PX:
                return ("the smallest type the run measured anywhere on this page is "
                        f"{min(sizes):.0f}px, which is not too small to read")
        # No stretch of the page is empty if nearly all of it resolved. A region
        # the tree says holds something and the capture draws nothing into is
        # counted on every capture, as a share of what was measured.
        if cls._CLAIMS_EMPTY_SECTIONS.search(text):
            shares = [float(item.get("blankShare") or 0.0) for item in cls._captures_measured(journeys)]
            if shares and max(shares) <= 0.02:
                return ("every region the run measured had something drawn in it, on all "
                        f"{plural(len(shares), 'capture')} of this run, so no part of the page "
                        "was blank")
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

    @staticmethod
    def _captures_measured(journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Every capture measurement this run recorded, as the service reported it.

        One reader for three checks, because they are three questions about the
        same thing: what the perception service measured on the pictures this run
        actually took. A capture that carries no measurement is left out rather
        than counted as a clean one -- a check that cannot run must not pass.
        """
        return [capture for journey in journeys
                for event in journey.get("timeline") or []
                if event.get("type") == "persona.perception"
                for capture in [(event.get("data") or {}).get("capture") or {}]
                if capture.get("measured")]

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
                f"synthesized from {plural(finding.get('observations', 1), 'observation')} across "
                f"{plural(finding.get('affectedPersonas', 1), 'person', 'people')}; estimated impact: "
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
            measured_name = ""
            measured_box: dict[str, Any] | None = None
            could_see = ""
            unmet: dict[str, Any] | None = None
            previous = 0.0
            for event in journey.get("timeline") or []:
                kind, data = event.get("type"), event.get("data") or {}
                if kind == "persona.expectation":
                    pending, expectation = data.get("action") or {}, str(data.get("expectation") or "")
                    measured_name = str(data.get("targetName") or "").strip()
                    measured_box = data.get("targetBox") or None
                    # What this person could see when they formed the expectation,
                    # in their own words. The slide's fourth panel used to quote the
                    # gap, which the summary two panels earlier already quotes --
                    # three headings, one sentence.
                    could_see = str(data.get("visible") or "").strip()
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
                                 "name": measured_name, "box": measured_box,
                                 "couldSee": could_see,
                                 "observed": str(data.get("observed") or "").strip(),
                                 "gap": str(data.get("gap") or "").strip()}
                    pending = None
                elif kind == "persona.affect":
                    # The affect event that follows a reflection is what that
                    # reflection cost. Read here rather than assumed, because a
                    # miss a persona shrugs off and a miss that ends the journey
                    # are not the same finding.
                    frustration = float((data.get("state") or {}).get("frustration") or 0.0)
                    if unmet is not None:
                        label = cls._promise_label(unmet["expectation"], unmet["action"],
                                                   unmet.get("name"))
                        group = groups.setdefault(label, {
                            "label": label, "hits": 0, "cost": 0.0, "personas": [], "names": [],
                            "runs": [], "gaps": [], "expectations": [], "actions": [],
                            "boxes": [], "sightings": [], "roles": [], "feelings": []})
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
                        if unmet.get("box"):
                            group["boxes"].append(unmet["box"])
                        if unmet.get("couldSee"):
                            group["sightings"].append({"quote": unmet["couldSee"], "personaId": persona_id,
                                                       "personaName": persona_name})
                        # F5: what this cost them, in their own words -- not the
                        # factual gap, which is already quoted verbatim in the
                        # summary above. A quote is only worth printing a second
                        # time if it says something the summary did not.
                        feeling = str(data.get("feeling") or "").strip()
                        if feeling:
                            group["feelings"].append({"quote": feeling, "personaId": persona_id,
                                                      "personaName": persona_name})
                        role = str((unmet.get("action") or {}).get("type") or "").upper()
                        if role:
                            group["roles"].append(role)
                        group["actions"].append(unmet["action"])
                        unmet = None
                    previous = frustration
        merged = cls._merge_promise_labels(groups)
        return [cls._broken_promise_finding(group) for group in
                sorted(merged, key=lambda item: -item["cost"])]

    @classmethod
    def _preserved_from_met_expectations(cls, journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """RPT-4/D9: the positive to `_pain_points_from_expectations`' misses --
        a control that did exactly what a visitor expected, first try, grounded
        in a *met* expectation rather than in generic praise. Same rule the
        misses use for what counts as a promise (a control, not a scroll or a
        read), the same grouping key (`_promise_label`, so a control preserved
        here and broken elsewhere in another run can never silently be two
        different entries), and the same `matched` field the scorecard counts
        its hit rate from.
        """
        preserved: dict[str, dict[str, Any]] = {}
        for journey in journeys:
            persona_id = journey.get("profileId") or journey.get("testerProfileId")
            pending: dict[str, Any] | None = None
            expectation, measured_name = "", ""
            for event in journey.get("timeline") or []:
                kind, data = event.get("type"), event.get("data") or {}
                if kind == "persona.expectation":
                    pending, expectation = data.get("action") or {}, str(data.get("expectation") or "")
                    measured_name = str(data.get("targetName") or "").strip()
                elif kind == "persona.reflection" and pending is not None:
                    if (str(data.get("matched") or "").lower() == "yes"
                            and str(pending.get("type") or "").upper() in cls._PROMISING_ACTIONS):
                        label = cls._promise_label(expectation, pending, measured_name)
                        entry = preserved.setdefault(label, {
                            "title": f"“{label}” does what it says", "elements": [],
                            "personaIds": [], "routes": [], "screenshotRefs": [], "source": "persona.expectation",
                            "hits": 0, "expectation": expectation.strip()})
                        entry["hits"] += 1
                        if persona_id and persona_id not in entry["personaIds"]:
                            entry["personaIds"].append(persona_id)
                    pending = None
        for entry in preserved.values():
            entry["observedByPersonas"] = len(entry["personaIds"])
            entry["description"] = (f"Before touching it, a visitor expected: "
                                    f"“{entry.pop('expectation') or entry['title']}”. It delivered, "
                                    f"first try, {plural(entry.pop('hits'), 'time')}.")
        return list(preserved.values())

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
            for field in ("gaps", "expectations", "actions", "boxes", "sightings", "roles", "feelings"):
                host[field].extend(group.get(field) or [])
            for persona, name in zip(group["personas"], group["names"]):
                if persona not in host["personas"]:
                    host["personas"].append(persona)
                    host["names"].append(name)
            for run in group["runs"]:
                if run not in host["runs"]:
                    host["runs"].append(run)
        return kept

    @staticmethod
    def _promise_label(expectation: str, action: dict[str, Any], measured: str = "") -> str:
        """What the persona thought it was interacting with, named the way it named
        it.

        A ref groups nothing and means nothing: the same control is e6 in one run
        and e17 in another, and no reader knows what either is. Worse, a ref that
        leaks through splits one control into two findings -- a live replay
        produced both "Annual - save 17%" (high) and "e17" (low) for the same
        toggle, because one run happened to quote the label and the other wrote
        "the Annual button" without quotes.

        So: what the element walk read off the control first -- it is the one name
        here that was measured rather than parsed out of a sentence, and it is the
        same string on every run, which is what makes it group. Then the quoted
        label, then the phrase the sentence names as the thing being clicked, and
        the ref only when nothing else said anything useful at all.

        Reading it out of prose is what put "Promised more than it did: e6" in a
        report headline: the persona wrote "The Pricing page will load and display
        the company's pricing details", which names no control, so every pattern
        here missed and the ref fell through. The walk knew it was the Pricing
        link the whole time.
        """
        if (measured or "").strip():
            return measured.strip()
        quoted = _QUOTED_LABEL.search(expectation or "")
        if quoted:
            return quoted.group(1).strip()
        named = _NAMED_CONTROL.search(expectation or "")
        if named:
            return named.group(1).strip()
        target = str((action or {}).get("target") or (action or {}).get("content") or "").strip()
        return target or str((action or {}).get("type") or "the page").lower()

    _plural = staticmethod(plural)

    @staticmethod
    def _patience_in_words(cost: float) -> str:
        """The measured cost, with the scale it is measured on said out loud.

        "0.22 of this visitor's patience on a 0-1 scale" is a real number in a unit
        nobody knows, which reads as less credible than a vague sentence. The
        number stays -- it is measured -- but it arrives with something to hold it
        against.
        """
        share = max(0.0, min(1.0, float(cost)))
        if share >= 0.66:
            felt = "most of the way from calm to walking away"
        elif share >= 0.33:
            felt = "about a third of the way from calm to walking away"
        elif share >= 0.12:
            felt = "roughly a fifth of the way from calm to walking away"
        else:
            felt = "a small but measurable dent in their patience"
        return f"{share:.2f} on a 0-1 patience scale -- {felt}"

    # What the person expected the control to do, by the verb they used for it.
    _EXPECTED_TO_REVEAL = re.compile(
        r"\b(show|display|reveal|see|list|tell|confirm|explain|give me|find out)\w*\b", re.I)
    _EXPECTED_TO_MOVE = re.compile(
        r"\b(open|navigate|go to|take me|bring me|load|lead)\w*\b", re.I)
    # What the page did, by the way the run described it afterwards.
    _DID_NOTHING = re.compile(
        r"\b(did not|didn'?t|nothing|no change|unchanged|remain\w*|still (?:present|there|shown))\b", re.I)

    @classmethod
    def _expectation_shape(cls, group: dict[str, Any]) -> tuple[str, str, bool]:
        """`(label, wanted, silent)` for one broken-promise group, or `("", "", False)`
        when there is not enough to classify.

        Shared between the root cause and the committed recommendation (RPT-1/RPT-2),
        so the two are never reasoning from two different readings of the same
        encounter: `wanted` is what the visitor's own verb predicted of the control,
        `silent` is whether the run recorded the page doing nothing visible about it.
        """
        label = str(group.get("label") or "").strip()
        expectation = " ".join(group.get("expectations") or [])
        gap = " ".join(item.get("quote", "") for item in (group.get("gaps") or []))
        if not label or not expectation:
            return "", "", False

        # Whichever verb governs the sentence, which is the one that comes first:
        # "open a page showing the plan" is a request to be taken somewhere, and
        # matching on "showing" because the reveal pattern was tested first read it
        # as the opposite.
        reveal, move = cls._EXPECTED_TO_REVEAL.search(expectation), cls._EXPECTED_TO_MOVE.search(expectation)
        if reveal and move:
            wanted = "be told something" if reveal.start() < move.start() else "be taken somewhere"
        elif reveal:
            wanted = "be told something"
        elif move:
            wanted = "be taken somewhere"
        else:
            wanted = "get a response"
        silent = bool(cls._DID_NOTHING.search(gap))
        return label, wanted, silent

    @classmethod
    def _why_they_expected_that(cls, group: dict[str, Any]) -> str:
        """A root cause: the property of the control that produced the expectation.

        The slide headed "Root cause analysis" fell back to `observation`, which is
        the gap sentence -- already printed under "Observed user issue" and again
        under "In the user's words". Three headings, one sentence, and the panel
        meant to carry the thinking carried none.

        So this names a mechanism instead, and it is built from what the run
        measured rather than asked of a model: the control's own label, the kind of
        behaviour the visitor's own verbs predicted of it, and the kind of
        behaviour the run recorded. Requoting either sentence would only move the
        duplication somewhere else, so neither is repeated here.
        """
        label, wanted, silent = cls._expectation_shape(group)
        if not label:
            return ""
        got = "nothing they could see" if silent else "something else"
        # The lesson depends on both halves. Saying "the click only moves the
        # visitor instead" about a control that did nothing at all describes a
        # different page than the one that was tested.
        moral = {
            ("be told something", True): ("A control named for what you will get owes you that, or a "
                                          "visible reason you are not getting it. Silence reads as a "
                                          "control that is broken rather than one that declined."),
            ("be told something", False): ("A control labelled with what you will get is read as the "
                                           "thing that gives it. When the click delivers something "
                                           "else, the label is the defect -- not the copy around it."),
            ("be taken somewhere", True): ("A control that reads as a door has to lead somewhere. "
                                           "Changing nothing visible leaves the visitor unsure their "
                                           "click even registered."),
            ("be taken somewhere", False): ("A control that reads as a door is expected to lead "
                                            "somewhere it has named. Arriving anywhere else costs the "
                                            "visitor their place as well as their time."),
            ("get a response", True): ("A control that invites a click owes the visitor a visible "
                                       "response to it, even when the answer is no."),
            ("get a response", False): ("A control that invites a click owes the visitor a response "
                                        "they can connect to the click they made."),
        }[(wanted, silent)]

        hits = int(group.get("hits") or 1)
        again = (f" They came back to it {hits} times, which is what people do when they are sure "
                 f"they used the right control and assume they mis-clicked." if hits > 1 else "")
        # RPT-2/B2: name the convention the expectation rests on -- the
        # benchmark's best sentences are all this shape ("as this is the case on
        # other free apps"). Explicitly marked as an inference about a general
        # web convention, never as something this run measured: nothing here
        # observed another site, so it must not read as though it did.
        convention = {
            "be told something": "a control labelled with what it reveals is read as the thing that "
                                 "reveals it, on most sites a visitor has already used",
            "be taken somewhere": "a control that reads as a link or a button naming a destination is "
                                  "expected to lead there, the way it does on most sites",
            "get a response": "a clickable control is expected to visibly acknowledge the click, on "
                              "most sites a visitor has already used",
        }[wanted]
        return (f"The wording is what set the expectation. Reading \u201c{label}\u201d, this visitor "
                f"expected to {wanted}, and got {got}. {moral}{again} This rests on a general web "
                f"convention, not something this run measured: {convention}.")

    # One concrete verb per shape of promise, keyed on (wanted, silent). Committed
    # to, never offered as a choice -- "either make X do Y or stop it reading that
    # way" restates the problem and hands the thinking back to the reader, which is
    # what RPT-1 exists to stop.
    _COMMIT_VERB = {
        ("be told something", True): "show what it promises",
        ("be told something", False): "name what it actually shows, not what a reader assumes it shows",
        ("be taken somewhere", True): "navigate to where it reads as leading",
        ("be taken somewhere", False): "name where it actually leads, not where it reads as leading",
        ("get a response", True): "give a visible response when it is clicked",
        ("get a response", False): "name the response it actually gives",
    }

    @classmethod
    def _committed_recommendation(cls, group: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
        """One concrete change, committed to, with the rejected half moved to
        `alternatives` where a reader who disagrees with the call can still find it.

        RPT-1: `"Either make {label} do what it reads as doing, or stop it reading
        that way"` is a principle, not a recommendation -- it restates the problem
        as a choice and hands the thinking back to the reader. The benchmark this
        was measured against commits: "put the Danish database at the top of the
        menu", "add a counter". So this commits too, on one rule decided by what the
        run actually recorded happening:

        Nothing visible happened (`silent`): the label already describes the
        intended behaviour, so the cheaper and more likely fix is to build that
        behaviour -- this is the worksheet's own example, a "Start 3-day free
        trial" button that does nothing at all. Something happened, just not what
        the label said: the behaviour already exists and evidently works, so the
        label -- not the behaviour -- is what is wrong.

        Grounded entirely in this group's own `label`, which is a real string from
        the page under test, never a template that would read the same on another
        one -- the acceptance test this exists to pass.
        """
        label, wanted, silent = cls._expectation_shape(group)
        if not label:
            return "", []
        verb = cls._COMMIT_VERB[(wanted, silent)]
        if silent:
            commit = (f"Make \u201c{label}\u201d {verb}. Right now the click produces nothing a "
                      f"visitor can see, and the label is the thing telling them it should.")
            rejected = (f"Reword \u201c{label}\u201d so a visitor no longer expects to {wanted} -- "
                        f"right now nothing does. Kept as the fallback, not the recommendation: it "
                        f"treats the symptom rather than the control, and a visitor who reads the "
                        f"new wording correctly still gets nothing for the click.")
        else:
            commit = (f"Relabel \u201c{label}\u201d to {verb}.")
            rejected = (f"Change what \u201c{label}\u201d does so it matches its current label. Kept "
                        f"as the fallback: the existing behaviour may be the one worth keeping, and "
                        f"relabelling is the cheaper of the two changes to be wrong about.")
        return commit, [{"proposedChange": rejected,
                         "rationale": "The half of the either/or not committed to above."}]

    @staticmethod
    def _traits_behind(group: dict[str, Any]) -> list[str]:
        """Which dispositions this finding actually lands on.

        `susceptibleTraits` has been in the schema and shipped `None` on every
        persona-derived finding, so a run with three deliberately different
        visitors reported its findings as though they had happened to a generic
        one. Derived from the shape of the encounter, never asserted: a control
        retried is a patience problem, a control that cost a lot of patience in one
        touch is an irritability problem.
        """
        traits = []
        if int(group.get("hits") or 0) > 1:
            traits.append("low patience")
        if float(group.get("cost") or 0.0) >= 0.3:
            traits.append("high irritability")
        if len(group.get("personas") or []) > 1:
            traits.append("shared across dispositions")
        return traits

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
        again = (f" {len(personas)} different visitors expected the same thing of it."
                 if len(personas) > 1 else
                 f" They tried it {hits} times." if hits > 1 else "")
        recommendation, alternatives = cls._committed_recommendation(group)
        return {
            "severity": severity, "category": "expectation",
            "title": f"Promised more than it did: {label}",
            # Both quotes carry the persona's own full stop; adding another reads
            # as a typo.
            "summary": (f"Before touching it they said what they expected: "
                        f"\"{expected.rstrip(' .')}.\" What arrived was not that -- "
                        f"\"{happened.rstrip(' .')}.\"{again} It cost {cls._patience_in_words(cost)}, "
                        f"measured across the run rather than assumed."),
            "recommendation": recommendation,
            # The rejected half of the commit above, not a synthesised echo of
            # `recommendation` -- RPT-1: _finding_slide only fakes an alternative
            # from the recommendation when this field is empty, and it never is now.
            "alternatives": alternatives,
            "evidence": (f"{cls._plural(hits, 'unmet expectation')} across "
                         f"{cls._plural(len(group['runs']) or 1, 'run')} and "
                         f"{cls._plural(len(personas) or 1, 'person', 'people')}, "
                         f"costing {cls._patience_in_words(cost)}"),
            "evidenceScreenshot": None, "evidenceIsAsTheySawIt": False,
            "elementName": label,
            # Where the control sat, so the evidence can be cropped to it. Without
            # this the best-evidenced finding in the report illustrated itself with
            # a whole-page screenshot captioned "page context".
            "elementBox": (group.get("boxes") or [None])[0],
            "observation": happened,
            "rootCause": cls._why_they_expected_that(group),
            # RPT-2/F5: what this cost them, in their own words, is what makes a
            # second quote worth printing at all -- the factual gap is already
            # quoted verbatim in the summary above it, so requoting it here read
            # as the same observation in fancy dress. What they could see before
            # acting is the next-best first-person quote when there is no affect
            # line to draw on; the factual gap is the last resort, not the first.
            "personaEvidence": (group.get("feelings") or group.get("sightings") or group["gaps"])[:2],
            "susceptibleTraits": cls._traits_behind(group),
            "claimedImpact": {"frustration": round(cost, 2), "personas": len(personas) or 1,
                              "attempts": hits},
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
                             f"holds text, on {plural(group['steps'], 'step')}"),
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
                         f"seen on {plural(group['steps'], 'step')} by {plural(len(personas) or 1, 'person', 'people')}"),
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
                         f"{plural(group['steps'], 'step')} and {plural(len(personas) or 1, 'person', 'people')}"),
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
                        if (stopped_them := ReportAssembler._what_stopped_them(journey)) else
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

    # CAP-4: fields a redacted element's outbound copy must never carry a real
    # value in, matching the worker's own SENSITIVE_FIELDS in safety.js.
    _SENSITIVE_ELEMENT_FIELDS = ("name", "text", "value", "inputValue")

    @staticmethod
    def _boxes_to_redact(elements: list[dict[str, Any]], redact_selectors: list[str]) -> list[dict[str, Any]]:
        """Boxes of elements this run was told to always treat as sensitive (an
        account menu, an invoice row) -- the Python side of the same
        per-credential selector list the worker's markSelectorsSensitive reads
        off the DOM walk. No box, or no selector match: nothing to blank."""
        if not redact_selectors:
            return []
        wanted = set(redact_selectors)
        return [element["box"] for element in elements
                if isinstance(element, dict) and element.get("selector") in wanted and element.get("box")]

    @classmethod
    def _redact_element_fields(cls, elements: list[dict[str, Any]], redact_selectors: list[str]
                               ) -> list[dict[str, Any]]:
        """Blank the accessible name/text/value of a redact-listed element before
        it is included in an outbound vision-critique request -- the Python-side
        equivalent of the worker's markSelectorsSensitive + redactSensitive pair,
        applied to journeytest-core's own DOM snapshots rather than the walk."""
        if not redact_selectors:
            return elements
        wanted = set(redact_selectors)
        return [{**element, **{field: "[REDACTED]" for field in cls._SENSITIVE_ELEMENT_FIELDS if field in element}}
                if isinstance(element, dict) and element.get("selector") in wanted else element
                for element in elements]

    @staticmethod
    def _redact_boxes_in_image(image_bytes: bytes, boxes: list[dict[str, Any]]) -> bytes:
        """Blank the pixels of every sensitive box before this image becomes part
        of a report artifact or leaves this process in a vision-critique request
        -- redaction at the point of capture, not the point of render. Raises on
        a bad box or an unreadable image rather than returning the bytes
        unredacted: a caller with boxes to redact and a failure here must drop
        the screenshot, not ship it unblanked."""
        if not boxes:
            return image_bytes
        from PIL import Image, ImageDraw
        with Image.open(BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
            draw = ImageDraw.Draw(image)
            for box in boxes:
                x, y, width, height = float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
                draw.rectangle([x, y, x + width, y + height], fill=(0, 0, 0))
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()

    @classmethod
    def _attach_verdict_screenshots(cls, findings: list[dict[str, Any]], journeys: list[dict[str, Any]],
                                    redact_selectors: list[str] | None = None, start_evidence_number: int = 1
                                    ) -> None:
        """Show the page a stage-1 finding is about.

        Only the vision-synthesis findings carried an image before, so every slide
        built from JourneyTest's own verdict (blockers, uxFindings, failed pass
        criteria) rendered with an empty "Current design" panel. The verdict already
        cites the screenshot it drew each finding from -- use it. Where it cites
        none, fall back to the run's own framing shots: the state the run ended in
        for a blocker or a failed criterion, the state it started in for an
        observation about the page.

        `start_evidence_number` continues E7's per-finding marker numbering after
        whatever `_synthesize_pain_points` already assigned, so a report with both
        finding sources never draws two region crops with the same digit.
        """
        redact_selectors = redact_selectors or []
        evidence_number = start_evidence_number
        screenshots_by_run = {journey.get("runId"): (journey.get("artifacts") or {}).get("screenshots") or []
                              for journey in journeys}
        snapshots_by_run = {journey.get("runId"): (journey.get("artifacts") or {}).get("snapshots") or []
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
            if redact_selectors:
                elements = cls._elements_for_screenshot(path, snapshots_by_run.get(finding.get("runId")) or [])
                boxes = cls._boxes_to_redact(elements, redact_selectors)
                if boxes:
                    try:
                        image_bytes = cls._redact_boxes_in_image(image_bytes, boxes)
                    except (OSError, ValueError, KeyError, TypeError):
                        continue
            # Crop to the element when the finding knows where it is. A finding
            # about one unreadable caption, illustrated with the whole page, makes
            # the reader hunt for what it is talking about -- and on a capture
            # degraded to that persona's eyesight, hunting is exactly what they
            # cannot do.
            box = finding.get("elementBox")
            crop = cls._crop_element_data_uri(image_bytes, box, number=evidence_number) if box else None
            is_region = bool(crop)
            if not crop:
                crop = cls._screenshot_data_uri(image_bytes)
            if crop:
                finding["screenshotCrop"] = crop
                finding["screenshotIsRegion"] = is_region
                finding["screenshotRef"] = path
                if is_region:
                    finding["evidenceNumber"] = evidence_number
                    evidence_number += 1

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

    # D7: roles read as the same rough kind of control for proximity-grouping
    # purposes. Anything not in one of these buckets is left out of the check
    # entirely -- a role this doesn't recognise is a role it has no business
    # guessing the behaviour kind of.
    _CONTROL_ACTION_KIND = {
        "link": "navigates", "button": "acts", "submit": "acts", "checkbox": "toggles",
        "radio": "toggles", "switch": "toggles", "tab": "switches view", "menuitem": "opens menu",
    }
    # Elements whose boxes are within this many pixels of each other (expanded)
    # read as one visual group to a visitor scanning the page -- roughly a
    # comfortable touch-target gap, not a rigorous perceptual measurement.
    _GROUPING_MARGIN_PX = 16

    @staticmethod
    def _boxes_are_adjacent(a: dict[str, Any], b: dict[str, Any], margin: float) -> bool:
        try:
            ax0, ay0 = float(a["x"]), float(a["y"])
            ax1, ay1 = ax0 + float(a["width"]), ay0 + float(a["height"])
            bx0, by0 = float(b["x"]), float(b["y"])
            bx1, by1 = bx0 + float(b["width"]), by0 + float(b["height"])
        except (KeyError, TypeError, ValueError):
            return False
        return not (bx0 > ax1 + margin or bx1 < ax0 - margin or by0 > ay1 + margin or by1 < ay0 - margin)

    @classmethod
    def _cluster_by_proximity(cls, elements: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Elements a visitor would read as one visual group, by boxes touching
        or nearly touching -- proximity implying similar function is a
        relationship *between* elements, not a property of one, which is why no
        per-element check finds it. Simple flood-fill over pairwise adjacency;
        this does not need to be a real layout engine, only consistent."""
        remaining = list(elements)
        clusters: list[list[dict[str, Any]]] = []
        while remaining:
            cluster = [remaining.pop(0)]
            grew = True
            while grew:
                grew = False
                for candidate in list(remaining):
                    if any(cls._boxes_are_adjacent(member.get("box") or {}, candidate.get("box") or {},
                                                    cls._GROUPING_MARGIN_PX) for member in cluster):
                        cluster.append(candidate)
                        remaining.remove(candidate)
                        grew = True
            clusters.append(cluster)
        return clusters

    @classmethod
    def _grouped_controls_with_differing_actions(cls, journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """D7: controls close enough to read as one group, whose kinds of action
        actually differ -- a navigation link next to what looks like its sibling
        but is really a destructive submit button, say. The geometry and the
        roles are both already captured; this is the relationship between
        elements no per-element check can find."""
        findings: list[dict[str, Any]] = []
        seen: set[tuple] = set()
        for journey in journeys:
            snapshot_paths = [path for path in (journey.get("artifacts") or {}).get("snapshots") or []
                              if Path(path).suffix == ".json"]
            for snapshot_path in snapshot_paths:
                elements = [element for element in cls._read_snapshot_elements(snapshot_path)
                           if element.get("box") and str(element.get("role") or "").lower() in cls._CONTROL_ACTION_KIND]
                for cluster in cls._cluster_by_proximity(elements):
                    kinds = {str(element.get("role") or "").lower() for element in cluster}
                    if len(cluster) < 2 or len(kinds) < 2:
                        continue
                    key = tuple(sorted(str(element.get("selector") or "") for element in cluster))
                    if key in seen:
                        continue
                    seen.add(key)
                    names = [str(element.get("name") or element.get("text") or element.get("selector") or "").strip()
                            for element in cluster]
                    kind_list = ", ".join(f'"{name}" {cls._CONTROL_ACTION_KIND[str(element.get("role") or "").lower()]}'
                                          for name, element in zip(names, cluster))
                    box = min((element.get("box") for element in cluster),
                             key=lambda b: (b or {}).get("y", 0))
                    findings.append({
                        "severity": "medium", "category": "consistency",
                        "title": f"Grouped controls that do different kinds of things: {', '.join(names[:3])}",
                        "summary": (f"{plural(len(cluster), 'control')} sit close enough together to read as "
                                    f"one group, and do different kinds of things: {kind_list}. Proximity "
                                    "implies shared function; a visitor treating them as equivalent options "
                                    "gets a different outcome depending on which one they pick."),
                        "recommendation": ("Separate them visually if they are meant to be read as different "
                                           "kinds of control, or make their behaviour consistent if they are "
                                           "meant to be read as the same kind."),
                        "evidence": f"boxes within {cls._GROUPING_MARGIN_PX}px of each other, roles: "
                                   + ", ".join(sorted(kinds)),
                        "elementBox": box, "elementName": names[0] if names else "",
                        "source": "layout.grouped", "runId": journey.get("runId"),
                        "personaId": journey.get("profileId") or journey.get("testerProfileId"),
                    })
        return findings

    # D4: WCAG 2.5.8 (Target Size, Minimum) -- 24x24 CSS px, the AA minimum for
    # a pointer target. Built from box geometry alone, which is the one part of
    # the DOM snapshot already verified reliable elsewhere in this codebase
    # (_boxes_are_adjacent, _crop_element_data_uri). Deliberately the only piece
    # of the "deterministic sweep" this attempts: heading order needs a tag or
    # heading-level field, alt text needs an `alt` attribute, and a form-label
    # check needs a label association -- none of which this codebase has ever
    # seen on an element from journeytest-core's own snapshot (checked against
    # every fixture and every live payload shape referenced anywhere in this
    # tree, the same check RPT-5/C4 ran before declining to guess at a palette
    # field). Guessing field names that may not exist would either silently
    # find nothing (indistinguishable from "the page is fine") or crash on a
    # real payload -- both worse than not attempting the other four checks.
    _MIN_TARGET_PX = 24

    @classmethod
    def _small_touch_targets(cls, journeys: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """D4 (partial: target size only): an interactive control below the WCAG
        AA minimum is hard to hit accurately for any visitor, not only one whose
        motor profile happened to miss it -- a fact about the control, reported
        the same way the contrast check reports a fact about a colour."""
        findings: list[dict[str, Any]] = []
        seen: set[str] = set()
        for journey in journeys:
            for snapshot_path in [path for path in (journey.get("artifacts") or {}).get("snapshots") or []
                                  if Path(path).suffix == ".json"]:
                for element in cls._read_snapshot_elements(snapshot_path):
                    role = str(element.get("role") or "").lower()
                    if role not in cls._CONTROL_ACTION_KIND:
                        continue
                    box = element.get("box") or {}
                    width, height = box.get("width"), box.get("height")
                    if not (isinstance(width, (int, float)) and isinstance(height, (int, float))):
                        continue
                    if width >= cls._MIN_TARGET_PX and height >= cls._MIN_TARGET_PX:
                        continue
                    selector = str(element.get("selector") or "")
                    if not selector or selector in seen:
                        continue
                    seen.add(selector)
                    name = str(element.get("name") or element.get("text") or selector).strip()
                    findings.append({
                        "severity": "medium", "category": "accessibility",
                        "title": f'Target below the WCAG minimum: "{name}"',
                        "summary": (f'"{name}" measures {int(width)}x{int(height)}px. The WCAG 2.2 AA minimum '
                                    f"for a pointer target is {cls._MIN_TARGET_PX}x{cls._MIN_TARGET_PX}px -- "
                                    "below it, an accurate tap or click gets measurably harder for any "
                                    "visitor, not only one with reduced motor precision."),
                        "recommendation": (f"Increase the clickable area to at least "
                                           f"{cls._MIN_TARGET_PX}x{cls._MIN_TARGET_PX}px, either by enlarging "
                                           "the control or by padding its hit area without changing how it "
                                           "looks."),
                        "evidence": f"measured {int(width)}x{int(height)}px against a {cls._MIN_TARGET_PX}"
                                   f"x{cls._MIN_TARGET_PX}px minimum",
                        "elementBox": box, "elementName": name,
                        "source": "layout.targetSize", "runId": journey.get("runId"),
                        "personaId": journey.get("profileId") or journey.get("testerProfileId"),
                    })
        return findings

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

    # RPT-5/E7: the colour a marker is drawn in. Distinct from the deck's own
    # palette (`_presentation`'s `#38bdf8` accent) on purpose -- this has to read
    # against an arbitrary, unknown page background, not the deck's own.
    _EVIDENCE_MARKER_COLOR = (255, 59, 48)

    @classmethod
    def _draw_evidence_marker(cls, image: Any, box: dict[str, Any], offset: tuple[int, int], number: int) -> None:
        """Outline the exact element a finding is about and number it, in place.

        E7 (audit, absent, high): "bare screenshots make a reader hunt for the
        thing being discussed." The coordinates are already held on every
        finding (`elementBox`) -- this is the first thing that draws them."""
        from PIL import ImageDraw, ImageFont
        left, top = offset
        x0, y0 = box["x"] - left, box["y"] - top
        x1, y1 = x0 + box["width"], y0 + box["height"]
        draw = ImageDraw.Draw(image)
        draw.rectangle([x0, y0, x1, y1], outline=cls._EVIDENCE_MARKER_COLOR, width=3)
        label = str(number)
        radius = 11
        # Anchored on the box's own top-left corner, not the crop's -- the crop
        # is padded around the element, and a badge in the crop's corner would
        # point at empty margin rather than the control itself.
        cx, cy = max(radius, x0), max(radius, y0)
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=cls._EVIDENCE_MARKER_COLOR)
        try:
            font = ImageFont.load_default()
        except OSError:
            font = None
        text_box = draw.textbbox((0, 0), label, font=font)
        tw, th = text_box[2] - text_box[0], text_box[3] - text_box[1]
        draw.text((cx - tw / 2 - text_box[0], cy - th / 2 - text_box[1]), label, fill=(255, 255, 255), font=font)

    @classmethod
    def _crop_element_data_uri(cls, image_bytes: bytes, box: dict[str, Any] | None,
                               max_edge: int = 1200, number: int | None = None) -> str | None:
        """Crop the specific region a vision finding refers to out of the full
        screenshot, so the UI can show exactly what the finding is about instead
        of just a wall of text. Returns None (caller shows no image) rather than
        raising -- a missing crop is a lesser failure than losing the finding.

        `number`, when given, is drawn as a marker on the element's own box
        (E7) -- the same number the deck prints beside this finding's title, so
        a reader can match text to picture without reading the caption.
        """
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
                cropped = image.crop((left, top, right, bottom)).convert("RGB")
                if number is not None:
                    cls._draw_evidence_marker(cropped, {"x": x, "y": y, "width": width, "height": height},
                                              (left, top), number)
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

    @staticmethod
    def _screenshot_elapsed_ms(journey: dict[str, Any]) -> dict[str, float]:
        """When each of this run's screenshots was actually taken, from the run's
        own `browser.screenshot` timeline events -- the same `elapsedMs` clock
        every other event on the timeline is stamped with, so a screenshot and a
        persona.expectation/reflection/affect triple can be placed on one axis
        and compared."""
        out: dict[str, float] = {}
        for event in journey.get("timeline") or []:
            if event.get("type") != "browser.screenshot":
                continue
            path = (event.get("data") or {}).get("path")
            elapsed = event.get("elapsedMs")
            if path and isinstance(elapsed, (int, float)):
                out[path] = float(elapsed)
        return out

    @staticmethod
    def _persona_moments(journey: dict[str, Any]) -> list[dict[str, Any]]:
        """What this persona expected, found, and felt, as a timeline of moments
        -- one per expectation this run committed to, however far it got before
        the run ended (a moment with no reflection/affect yet is still kept,
        anchored at the expectation's own elapsedMs).

        This is the same expectation -> reflection -> affect state walk
        `_pain_points_from_expectations` uses to build broken-promise findings,
        reused here for a different purpose: not to decide whether a promise was
        kept, but to say what this persona was experiencing at a given moment on
        the run's own clock, so a vision critique of one screenshot can be told
        what the person looking at that exact screen was thinking."""
        profile = journey.get("simulationProfile") or {}
        persona_id = journey.get("profileId") or journey.get("testerProfileId")
        persona_name = ((profile.get("persona") or {}).get("name")
                        or profile.get("name") or persona_id or "Synthetic user")
        moments: list[dict[str, Any]] = []
        pending: dict[str, Any] | None = None
        for event in journey.get("timeline") or []:
            kind, data = event.get("type"), event.get("data") or {}
            elapsed = event.get("elapsedMs")
            if kind == "persona.expectation":
                pending = {"elapsedMs": elapsed, "expectation": str(data.get("expectation") or "").strip(),
                          "matched": "", "gap": "", "feeling": "",
                          "personaId": persona_id, "personaName": persona_name}
                moments.append(pending)
            elif kind == "persona.reflection" and pending is not None:
                pending["matched"] = str(data.get("matched") or "").strip()
                pending["gap"] = str(data.get("gap") or "").strip()
            elif kind == "persona.affect" and pending is not None:
                pending["feeling"] = str(data.get("feeling") or "").strip()
                pending = None
        return moments

    @staticmethod
    def _nearest_moment(moments: list[dict[str, Any]], elapsed_ms: float | None) -> dict[str, Any] | None:
        if elapsed_ms is None or not moments:
            return None
        return min(moments, key=lambda moment: abs((moment.get("elapsedMs") or 0) - elapsed_ms))

    @staticmethod
    def _persona_context_text(moment: dict[str, Any] | None) -> str:
        """One short, first-person account of a moment, for the vision prompt.

        Prefers what actually happened over the bare expectation -- a reflection
        or a feeling is the moment resolved, which is more useful context than a
        prediction that may not even be about this screenshot yet."""
        if not moment or not moment.get("expectation"):
            return ""
        parts = [f'they expected: "{moment["expectation"]}"']
        if moment.get("matched") == "no" and moment.get("gap"):
            parts.append(f'what arrived instead: "{moment["gap"]}"')
        elif moment.get("matched") == "yes":
            parts.append("it matched what they expected")
        if moment.get("feeling"):
            parts.append(f'how it left them: "{moment["feeling"]}"')
        return "; ".join(parts)

    @staticmethod
    def _dedupe_quotes(quotes) -> list[dict[str, str]]:
        """The same {quote, personaId, personaName} dict, once, in first-seen
        order -- several screenshots from the same run can resolve to the same
        nearest moment and would otherwise repeat its quote once per screenshot."""
        seen: set[str] = set()
        kept: list[dict[str, str]] = []
        for quote in quotes:
            text = quote.get("quote")
            if not text or text in seen:
                continue
            seen.add(text)
            kept.append(quote)
        return kept

    @staticmethod
    def _persona_evidence_from_moment(moment: dict[str, Any] | None) -> list[dict[str, str]]:
        """The one quote worth attaching to a vision finding as personaEvidence,
        in the same {quote, personaId, personaName} shape every other source
        here uses. F5: prefer how it felt over what they could see or expected --
        the feeling is what the summary text does not already say."""
        if not moment:
            return []
        quote = moment.get("feeling") or moment.get("gap") or moment.get("expectation")
        if not quote:
            return []
        return [{"quote": quote, "personaId": moment.get("personaId"), "personaName": moment.get("personaName")}]

    @classmethod
    def _collect_vision_pain_points(cls, journeys: list[dict[str, Any]], tasks: list[str],
                                     personas: list[dict[str, Any]], url: str | None,
                                     vision: list[tuple[str, str, str]] | None = None,
                                     send_options: bool = False,
                                     redact_selectors: list[str] | None = None
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
        their own.

        CAP-4: `redact_selectors`, when given, blanks the pixel boxes and the
        name/text/value fields of any matching element before either the
        outbound vision-critique request or `screenshot_bytes` (which
        `_synthesize_pain_points` later crops from) ever sees them -- the one
        request body in this run that actually leaves the deployment.
        """
        # Handed no vision provider this caller may use, the critique is not
        # attempted at all. The alternative -- calling and letting the worker fall
        # back to its own environment -- would spend the deployment's credentials
        # on a run that was told it may not. Best-effort already, so an absent
        # critique is a gap the report names rather than a failure.
        if vision is not None and not vision:
            return [], {}, [], "no model provider is configured for vision critique", []
        redact_selectors = redact_selectors or []
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
                # What this persona expected/found/felt, placed on the run's own
                # elapsedMs clock, so each screenshot can be critiqued alongside
                # what the person looking at that exact screen was experiencing --
                # rather than the vision model judging every screenshot cold.
                screenshot_elapsed = cls._screenshot_elapsed_ms(journey)
                moments = cls._persona_moments(journey)
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
                    elements = cls._elements_for_screenshot(screenshot_path, snapshots)
                    if redact_selectors:
                        boxes = cls._boxes_to_redact(elements, redact_selectors)
                        if boxes:
                            try:
                                image_bytes = cls._redact_boxes_in_image(image_bytes, boxes)
                            except (OSError, ValueError, KeyError, TypeError) as error:
                                last_error = f"a sensitive region could not be redacted, screenshot skipped: {error}"
                                continue
                        elements = cls._redact_element_fields(elements, redact_selectors)
                    # Population happens only after any redaction above, so every
                    # later reader of this dict -- the payload below and
                    # _synthesize_pain_points' own crop -- sees the same
                    # already-redacted bytes. Never redact twice, never miss one.
                    screenshot_bytes[screenshot_path] = image_bytes
                    image_b64, image_mime = cls._vision_image_payload(image_bytes)
                    moment = cls._nearest_moment(moments, screenshot_elapsed.get(screenshot_path))
                    persona_context = cls._persona_context_text(moment)
                    payload = json.dumps({
                        "imageBase64": image_b64, "imageMimeType": image_mime,
                        "elements": elements, "url": url, "task": task_summary, "personaSummary": persona_summary,
                        "runId": journey.get("runId"), "userId": persona.get("id"),
                        "stepId": f"vision-{step_index + 1}", "screenshotRef": screenshot_path,
                        **({"personaContext": persona_context} if persona_context else {}),
                        # Only when this workspace configured its own: the worker
                        # resolves from its environment otherwise, and it knows
                        # more about its own deployment than the general chain.
                        **({"options": {"baseUrl": vision[0][0], "apiKey": vision[0][1],
                                        "model": vision[0][2]}} if send_options and vision else {}),
                    }).encode()
                    call = request.Request(f"{worker_url.rstrip('/')}/v1/journey-evidence-analyses",
                        data=payload, headers={"content-type": "application/json"}, method="POST")
                    try:
                        with request.urlopen(call, timeout=cls._vision_timeout()) as response:
                            result = json.loads(response.read())
                    except (request.HTTPError, OSError, ValueError) as error:
                        last_error = cls._worker_error(error)
                        continue
                    # Attached here, not asked of the worker: the moment is
                    # resolved from this run's own timeline, which is Python's to
                    # read, and every pain point from this screenshot shares it.
                    evidence = cls._persona_evidence_from_moment(moment)
                    for point in result.get("painPoints", []):
                        if evidence and not point.get("personaEvidence"):
                            point["personaEvidence"] = evidence
                        pain_points.append(point)
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
            # BE-5: how many distinct runs actually saw this -- 1 of 1 and 2 of 2
            # are different claims, and this is the one place every finding
            # already passes through regardless of which run produced it, so it
            # is where a reproduction count can be computed for all of them at
            # once rather than duplicated per finding-source. Meaningful once a
            # cohort runs any persona more than once (repeat seeds); on a cohort
            # that does not, this is just 1 for everything, honestly.
            run_ids = {item.get("runId") for item in cluster if item.get("runId")}
            reproduced_in = len(run_ids) if run_ids else 1
            if len(cluster) == 1:
                merged.append({**cluster[0], "reproducedIn": reproduced_in})
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
            combined["reproducedIn"] = reproduced_in
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

    @classmethod
    def _persona_mental_model(cls, journey: dict[str, Any]) -> str:
        """RPT-2/B3: this persona's expectations across the whole run, summarised
        into one stated model of what they thought the product was, with where
        the page held or contradicted it -- not per-control (that is what the
        broken-promise findings are for), but the pattern across all of them.

        Built from every `persona.expectation` -> `persona.reflection` pair in
        the timeline, not only the unmet ones `_pain_points_from_expectations`
        groups into findings: a persona whose expectations mostly held is a real
        and different report from one whose expectations mostly did not, and
        that shape is invisible if only the misses are ever counted.
        """
        pending_expectation = ""
        classified: list[str] = []
        met, total = 0, 0
        for event in journey.get("timeline") or []:
            kind, data = event.get("type"), event.get("data") or {}
            if kind == "persona.expectation":
                pending_expectation = str(data.get("expectation") or "").strip()
            elif kind == "persona.reflection" and pending_expectation:
                reveal = cls._EXPECTED_TO_REVEAL.search(pending_expectation)
                move = cls._EXPECTED_TO_MOVE.search(pending_expectation)
                if reveal and move:
                    classified.append("be told something" if reveal.start() < move.start() else "be taken somewhere")
                elif reveal:
                    classified.append("be told something")
                elif move:
                    classified.append("be taken somewhere")
                else:
                    classified.append("get a response")
                total += 1
                if str(data.get("matched") or "").lower() == "yes":
                    met += 1
                pending_expectation = ""
        if total < 2:
            # One data point is not a pattern; stating a "model" from it would
            # overclaim what a single expectation can support.
            return ""
        dominant, dominant_count = Counter(classified).most_common(1)[0]
        share = dominant_count / total
        if share < 0.5:
            shape = "no single pattern -- their expectations of controls varied about as much as the controls did"
        else:
            shape = f"mostly expected controls to {dominant} ({dominant_count} of {total} expectations)"
        held = "held" if met == total else "never held" if met == 0 else f"held for {met} of {total}"
        return (f"Across the run, this persona {shape}. That model {held} against what the page actually "
                f"did.")

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
        # E7: a number drawn on the region crop, matched by the deck to the same
        # number beside this finding's title -- one counter across this whole
        # call, so two findings from the same run never draw the same digit.
        next_evidence_number = 1
        for root_cause in root_causes:
            member_points = [pain_point_by_id[pid] for pid in root_cause["painPointIds"] if pid in pain_point_by_id]
            if not member_points:
                continue
            representative = member_points[0]
            severity = max((point.get("severity", "medium") for point in member_points),
                           key=lambda value: cls._SEVERITY_RANK.get(value, 1))
            affected = len(root_cause["affectedUsers"])
            impact = root_cause["averageStateImpact"]
            crop, crop_is_region, evidence_number = None, False, None
            element = (representative.get("elements") or [{}])[0]
            screenshot = screenshot_bytes.get(representative.get("screenshotRef"))
            if element.get("box") and screenshot:
                evidence_number = next_evidence_number
                crop = cls._crop_element_data_uri(screenshot, element["box"], number=evidence_number)
                crop_is_region = crop is not None
                if crop_is_region:
                    next_evidence_number += 1
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
                                      f"({plural(len(root_cause['affectedIterations']), 'run')}).")
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
                # What the persona looking at this exact screen was experiencing --
                # not the vision model's own read of the page, but the run's own
                # first-hand account, matched to this screenshot by elapsedMs
                # (_persona_evidence_from_moment). Deduplicated across every member
                # pain point the way every other multi-persona finding here is.
                "personaEvidence": cls._dedupe_quotes(
                    quote for point in member_points for quote in (point.get("personaEvidence") or [])),
            }
            if crop:
                finding["screenshotCrop"] = crop
                finding["screenshotIsRegion"] = crop_is_region
                # Without this the crop could not be traced back to the capture it
                # was taken from (it was recorded only for stage-1 findings).
                finding["screenshotRef"] = representative.get("screenshotRef")
                if crop_is_region:
                    finding["evidenceNumber"] = evidence_number
            findings.append(finding)
        return findings

    @classmethod
    def _attach_redesigns(cls, findings: list[dict[str, Any]], url: str | None,
                          providers: list[tuple[str, str, str]] | None = None,
                          usage_sink: list[dict[str, Any]] | None = None) -> None:
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
            fragment = cls._generate_redesign_fragment(finding, url, providers, usage_sink=usage_sink)
            if fragment:
                finding["redesignHtml"] = fragment

    @staticmethod
    def _sample_palette(screenshot_path: str | None, box: dict[str, Any] | None) -> dict[str, str] | None:
        """The real colours this page actually uses, read from the pixels rather
        than assumed.

        C4 (audit, weak, high): the re-design panel is real, working HTML -- a
        genuine advantage over a static mockup -- and it renders a generic
        `#0066ff` button on white in system-ui, so it reads as a sketch rather
        than a proposal grounded in the page it is fixing. journeytest-core's
        DOM snapshot carries no colour, type-size or radius fields to lift this
        from (checked: not one fixture or live payload in this codebase's tests
        has ever carried them), so this reads it the one place it verifiably
        is -- the screenshot's own pixels -- rather than assuming a schema this
        codebase has not seen.
        """
        if not screenshot_path:
            return None
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            with Image.open(screenshot_path) as image:
                image = image.convert("RGB")
                element_region = image
                if box:
                    x, y, width, height = float(box["x"]), float(box["y"]), float(box["width"]), float(box["height"])
                    left, top = max(0, int(x)), max(0, int(y))
                    right, bottom = min(image.width, int(x + width)), min(image.height, int(y + height))
                    if right > left and bottom > top:
                        element_region = image.crop((left, top, right, bottom))
                # The corner farthest from the element's own box is the closest
                # thing to "the page background" this can read without a layout
                # model -- top-left would as often as not sample the element
                # itself, on a page where the finding is about something near
                # the top of the viewport.
                far_left = image.width // 2 <= (box.get("x", 0) if box else 0)
                far_top = image.height // 2 <= (box.get("y", 0) if box else 0)
                bx0 = 0 if far_left else max(0, image.width - 40)
                by0 = 0 if far_top else max(0, image.height - 40)
                background_region = image.crop((bx0, by0, min(bx0 + 40, image.width), min(by0 + 40, image.height)))

                def dominant_hex(region):
                    small = region.resize((1, 1), Image.LANCZOS)
                    r, g, b = small.getpixel((0, 0))
                    return f"#{r:02x}{g:02x}{b:02x}"

                return {"elementColor": dominant_hex(element_region), "pageBackground": dominant_hex(background_region)}
        except (OSError, ValueError, KeyError, TypeError):
            return None

    @classmethod
    def _generate_redesign_fragment(cls, finding: dict[str, Any], url: str | None,
                                    providers: list[tuple[str, str, str]] | None = None,
                                    usage_sink: list[dict[str, Any]] | None = None) -> str | None:
        """One finding -> a self-contained HTML fragment implementing its fix.

        Returns None when no model is configured or the call fails: an absent
        redesign is honest, a templated one that ignores the finding is not.
        """
        # Handed the chain rather than resolving one: the report half never opens
        # the settings store, so it stays a thing the control plane calls rather
        # than a second place that decides whose budget a run spends.
        if providers is not None and not providers:
            return None
        try:
            from services.persona_service.semantic import DirectLLMSemanticEngine
            engine = DirectLLMSemanticEngine(providers=providers)
        except (ImportError, ValueError):
            return None
        elements = "\n".join(
            f'- selector="{element.get("elementId") or element.get("elementSelector", "")}" '
            f'role={element.get("role", "")} box={json.dumps(element.get("box") or {})}'
            # Opportunistic: used when present on an element, never assumed. See
            # _sample_palette's docstring for why this cannot be relied on.
            + (f' fontPx={element["fontPx"]}' if element.get("fontPx") else "")
            + (f' color={element["color"]}' if element.get("color") else "")
            for element in (finding.get("elements") or [])[:8]) or "(no specific element; page-wide finding)"
        first_box = next((element.get("box") for element in (finding.get("elements") or []) if element.get("box")),
                         finding.get("elementBox"))
        palette = cls._sample_palette(finding.get("screenshotRef"), first_box)
        palette_line = (f"Measured palette from the real screenshot: this element's colour is "
                        f"{palette['elementColor']}, the page background is {palette['pageBackground']}. "
                        "Use these, not a generic default, unless the fix specifically requires a different "
                        "colour (e.g. a contrast fix)." if palette else "")
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
            *([palette_line] if palette_line else []),
            f"Changes to implement:\n{changes}",
            "Produce the corrected component implementing those changes.",
        ])
        try:
            content = engine.complete_text(system_prompt, user_prompt, role="report.redesign")
        except RuntimeError:
            return None
        finally:
            # BE-3: recorded whether or not the call above produced a usable
            # fragment -- the tokens were still spent on the attempt.
            if usage_sink is not None:
                usage_sink.extend(engine.usage_log)
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
            stripped = re.sub(r"\n?```\s*$", "", stripped).strip()
        # A fragment, not a document: reject a full page, and reject prose.
        if "<html" in stripped.lower() or "<" not in stripped:
            return None
        return stripped or None

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
            # E7: the same number drawn on the region crop, so a reader matches
            # text to picture without reading the caption end to end.
            marker = (f'<span style="display:inline-flex;align-items:center;justify-content:center;'
                     f'width:1.3em;height:1.3em;border-radius:50%;background:#ff3b30;color:#fff;'
                     f'font-size:.75em;margin-right:.4em">{item["evidenceNumber"]}</span>'
                     if item.get("evidenceNumber") else "")
            # The persona's own reasoning from the run that produced this finding --
            # what makes it demonstrated rather than asserted.
            quotes = "".join(
                f'<blockquote style="margin:.4rem 0;padding:.4rem .8rem;border-left:3px solid #38bdf8;opacity:.9">'
                f'{escape(str(evidence.get("quote", ""))[:400])}'
                f'<br><span style="opacity:.6;font-size:.8em">— {escape(str(evidence.get("personaName") or "Synthetic user"))}</span>'
                f'</blockquote>' for evidence in (item.get("personaEvidence") or [])[:2])
            # RPT-3: a falsifiable prediction, not just an assertion.
            retest = (f'<p style="opacity:.7;font-size:.85em"><strong>How you would know it worked:</strong> '
                     f'{escape(str(item["retest"]))}</p>' if item.get("retest") else "")
            return (f'<li>{marker}<strong>[{badge}] {escape(item["title"])}</strong> '
                    f'<span style="opacity:.6">({category})</span><br>'
                    f'{escape(item.get("summary") or item.get("evidence") or "")}{recommendation}{grounding}{retest}{quotes}{image}</li>')

        findings = "".join(render_finding(item) for item in report.get("critical_pain_points", [])) or "<li>No findings.</li>"
        preserve_items = "".join(
            f'<li><strong>{escape(str(item.get("title", "")))}</strong>'
            + (f' <span style="opacity:.6">(noted by {plural(item["observedByPersonas"], "person", "people")})</span>'
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
            + (f', {plural(entry["affectedPersonas"], "person", "people")}' if entry.get("affectedPersonas") else "") + ')</span></li>'
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
            f'{escape(plural(impact.get("personasTested", len(report.get("synthetic_users") or [])), "synthetic user"))}</p></section>')

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
        # F2: scope stated as intent, up front, including what this review did
        # not cover -- not left for a reader to infer from the absence of a
        # finding about some other page or flow.
        scope_note = (f'<p class="affected">Scope: only the tasks below, against {escape(url or "the target site")}. '
                      "Other pages, flows, and states of the product were not exercised and are not "
                      "represented in this review.</p>")
        # G4: the strongest sentence this report can write about itself, printed
        # verbatim rather than only rendered as "Observed"/"Inferred" prose --
        # it is the one line that says exactly how much to trust what follows.
        evidence_stamp = (f'<p class="affected" style="opacity:.7">'
                          f'evidence_language: {escape(report.get("evidence_language") or "unknown")}</p>')
        # BE-3: the economic case, on the one slide a reader would look for it --
        # never made before this existed anywhere in the artifact.
        usage = report.get("model_usage") or {}
        usage_note = ""
        if usage:
            token_bits = (f", {usage['totalPromptTokens'] + usage['totalCompletionTokens']} tokens"
                         if usage.get("totalPromptTokens") is not None else "")
            provider_bits = ", ".join(f"{p['model']} ({p['endpoint']})" for p in usage.get("providers") or [])
            usage_note = (f'<p class="affected" style="opacity:.7">'
                         f'{plural(usage["totalCalls"], "model call")}, '
                         f'{usage["totalWallMs"] / 1000:.1f}s wall time{token_bits}'
                         + (f" &mdash; served by {escape(provider_bits)}" if provider_bits else "") + '</p>')
        # A2: the hit rate, not only the misses -- a report that only shows
        # misses hides its own.
        scorecard = report.get("scorecard") or {}
        scorecard_note = ""
        if scorecard.get("tasksAttempted"):
            rate = scorecard.get("expectationsMetRate")
            rate_bits = f", {rate:.0%} of expectations held" if rate is not None else ""
            scorecard_note = (f'<p class="affected">{scorecard["tasksSucceeded"]} of '
                             f'{plural(scorecard["tasksAttempted"], "task")} completed{rate_bits}</p>')
        slides.append(
            f'<section class="slide"><h2>How this review was made</h2>'
            f'<p class="summary">{escape(method)}</p>'
            f'{scope_note}{evidence_stamp}{usage_note}{scorecard_note}'
            f'<h3>Tasks attempted</h3><ul>{task_items}</ul>'
            + (f'<p class="affected">{escape(plural(len(findings), "issue"))} found'
               + (f" &mdash; {escape(counts_line)}" if counts_line else "") + '</p>' if findings else "")
            # What the run could and could not see, on the slide where somebody
            # weighing an absent finding would look for it. The diagnostics were
            # reaching the JSON and a limitations line that says "see
            # run_diagnostics" -- which a reader of the deck cannot do.
            + cls._coverage_note(report)
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
                seen_line = (f'<p class="affected">Noted by {seen} of the {plural(seen, "person", "people")} tested</p>' if seen else "")
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
.sev-why{{font-size:.72rem;color:#5b6b7c;font-weight:400;letter-spacing:normal;text-transform:none}}
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
    def _coverage_note(report: dict[str, Any]) -> str:
        """One line on how much of the run the instruments actually saw.

        An absent finding and an unmeasured one look identical on a slide. A
        reader who knows the eyes resolved ten steps of twelve can weigh that
        silence; a reader who does not will read it as a clean bill of health.
        The diagnostics were reaching the JSON and a limitations line that reads
        "see run_diagnostics", which a reader of the deck cannot do.
        """
        coverage = [item for item in (report.get("run_diagnostics") or [])
                    if item.get("source") == "coverage"]
        if not coverage:
            return ""
        worst = max(coverage, key=lambda item: {"high": 2, "medium": 1}.get(item.get("severity"), 0))
        return (f'<p class="affected" style="opacity:.75">Coverage: '
                f'{escape(str(worst.get("evidence") or ""))}. An eyesight finding absent from those '
                f'steps is unknown rather than ruled out.</p>')

    @staticmethod
    def _severity_derivation(item: dict[str, Any]) -> str:
        """B7: a one-line account of *why* this severity, not just what it is,
        beside the chip -- built only from numbers this finding actually
        carries. A piece with nothing behind it is left out rather than
        guessed: not every finding source computes an affected count or a
        behavioural-impact delta (a verdict-level blocker is a claim about the
        whole run, not a per-persona measurement), so this degrades to
        whatever is real for that finding instead of inventing the rest.
        """
        bits = []
        affected = item.get("affectedPersonas")
        if affected:
            bits.append(plural(int(affected), "person"))
        impact = item.get("claimedImpact") or item.get("behavioralImpact") or {}
        frustration = impact.get("frustration") or impact.get("frustrationDelta")
        if isinstance(frustration, (int, float)) and frustration > 0:
            bits.append(f"raised frustration {frustration:.2f}")
        is_blocking = (item.get("category") == "blocker" or item.get("source") == "blockers"
                      or str(item.get("severity")) in ("critical", "high"))
        bits.append("blocking" if is_blocking else "not blocking")
        return ", ".join(bits)

    # RPT-2/E8: how much two panels' prose have to overlap before the second is
    # not new information -- "substantially repeats", not merely "mentions the
    # same words". Higher than _merge_similar_findings' 0.18 same-issue bar on
    # purpose: two findings about the same control are expected to share
    # vocabulary and still be different findings, but one slide's own root-cause
    # panel restating its own issue panel is the specific failure this guards.
    _PANEL_DUPLICATE_OVERLAP = 0.45

    @classmethod
    def _panel_duplicates(cls, candidate: str, other: str) -> bool:
        if not candidate or not other:
            return False
        if candidate.strip() == other.strip():
            return True
        return cls._jaccard(cls._text_tokens(candidate), cls._text_tokens(other)) >= cls._PANEL_DUPLICATE_OVERLAP

    @classmethod
    def _finding_slide(cls, item: dict[str, Any], index: int, issue_label: str) -> str:
        """One issue, in the three-part shape a usability report uses: what the user
        hit, why it happens, and what to change -- beside the evidence for it."""
        severity = str(item.get("severity") or "medium")
        flow = ReportAssembler._flow_label(item)
        issue_text = item.get("summary") or item.get("evidence") or ""
        # RPT-2: no fallback to `mechanism` or `observation`. Either the source
        # that produced this finding did the work of naming a root cause, or the
        # panel is left out -- a panel that cannot be filled honestly is not
        # filled with the symptom wearing a different heading. E8: also refused
        # when it substantially repeats the issue panel above it, not only when
        # the two are byte-identical -- a paraphrase of the symptom is the same
        # failure to say anything new, just harder to catch.
        root_cause = str(item.get("rootCause") or "")
        if root_cause and cls._panel_duplicates(root_cause, str(issue_text)):
            root_cause = ""
        alternatives = item.get("alternatives") or ([{"proposedChange": item["recommendation"]}]
                                                     if item.get("recommendation") else [])
        changes = "".join(f"<li>{escape(str(alt.get('proposedChange', '')))}</li>"
                          for alt in alternatives if alt.get("proposedChange"))
        affected = (f'<p class="affected">Reproduced by {item["affectedPersonas"]} of the visitors tested</p>'
                    if item.get("affectedPersonas") else "")
        references = (item.get("grounding") or {}).get("references") or []
        grounding = ('<p class="grounding"><strong>Grounded in:</strong> ' + "; ".join(
            f'{escape(str(ref.get("source", "")))} &mdash; {escape(str(ref.get("principle") or ref.get("title") or "")) }'
            for ref in references) + "</p>") if references else ""
        # RPT-3: how a reader would know this is fixed -- a falsifiable
        # prediction, not just an assertion, and checkable without a human
        # judgement call about what "fixed" would even mean here.
        retest = (f'<p class="grounding"><strong>How you would know it worked:</strong> '
                 f'{escape(str(item["retest"]))}</p>' if item.get("retest") else "")

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
            # C3: labelled as what it is -- working code, not a mockup -- with its
            # own source offered right below it so it can be read and lifted.
            panels.append('<figure class="shot"><figcaption>Re-design &mdash; working code, not a mockup</figcaption>'
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
        # B7: why this severity, not just what it is.
        derivation = ReportAssembler._severity_derivation(item)

        return (f'<section class="slide" data-severity="{escape(severity)}">'
                f'<span class="badge"><span class="sev sev-{escape(severity)}">{escape(severity.upper())}</span> '
                + (f'<span class="sev-why">&mdash; {escape(derivation)}</span> ' if derivation else "")
                + f'&middot; {escape(flow)}</span>'
                f'<h2>{escape(item.get("title", "Finding"))}</h2>{affected}'
                f'<div class="finding"><div class="cols">'
                f'<div class="col"><h3>{escape(issue_label)}</h3><p>{escape(str(issue_text))}</p></div>'
                + (f'<div class="col"><h3>Root cause analysis</h3><p>{escape(str(root_cause))}</p></div>'
                   if root_cause else "")
                + (f'<div class="col"><h3>Recommendations: design solutions</h3><ul>{changes}</ul></div>'
                   if changes else "")
                + quote_block
                + f'</div><div class="evidence">{shots}</div></div>{grounding}{retest}</section>')
