#!/usr/bin/env python3
"""Offline replay (RUN-3, docs/parallel-development-spec.md).

Rebuilds a `ux.report` from a saved run directory -- `last_runs/`'s own
layout -- by calling `ReportAssembler.assemble_report()` directly on the raw
`journey_log__*.json` and `persona_profile__*.json` artifacts, with no live
Journey worker, no live Eyeson worker, and no model call of its own
(`vision=[]`, `redesign=[]`; see `assemble_report`'s own docstring for why
that is a true no-op, not merely an unconfigured one -- both
`_collect_vision_pain_points` and `_generate_redesign_fragment` return
immediately on an empty-but-not-None provider list).

`url`/`tasks`/`job_id` are not carried on `journey_log__*.json` itself (it is
literally `{"runs": journey_outcome.runs}`, per `executor.py`'s own output
assembly), so they are read from `logs/job_final.json`'s `metadata` --
`last_runs/AGENTS.md` step 4 already saves this file for every snapshot.

Screenshot and video paths inside a saved run point at the deployment's own
filesystem (e.g. `/home/user/artifacts/journeys/<run>/screenshots/...`),
which does not exist in this checkout. `last_runs/` keeps a handful of the
real files, renamed to `<kind>__<artifact_id>.<ext>` by `AGENTS.md`'s own
refresh steps. `build_screenshot_remap()` recovers the original path -> local
file mapping from `logs/job_final.json`'s `output_artifacts` (written in the
same creation order `_browser_outputs()` emits them: every screenshot in
`journey.artifacts.screenshots` order, then the video), and every recovered
mapping is cross-checked against the local file's own magic bytes before
being trusted -- a `.png`-named original must map to a real PNG, a
`.jpg`-named original to a real JPEG, or the mapping is dropped rather than
guessed. Every path in the loaded journey is then rewritten wherever it
appears in the JSON tree (`artifacts.screenshots`, `artifacts.video`,
`persona.perception`'s `seenImage`, verdict evidence, ...), not just in the
few fields this script happens to name.

What differs from the live report, and why -- see `diff_reports()`'s own
categories, and `docs/parallel-development-spec.md`'s RUN-3 row for the
concrete numbers on `last_runs/`:

1. No `source: eyeson-vision-synthesis` findings -- `vision=[]` means the
   critique was never attempted.
2. `elements_to_preserve` can come up short, or empty, on a run whose
   journey-only sources (`_praise_from_verdicts`, `_preserved_from_verdicts`,
   `_preserved_from_met_expectations`) have nothing to say -- confirmed on
   `last_runs/`: an inconclusive run with 0 expectations met produces `[]`
   from all three, so its one live preserve entry ("Clear primary call to
   action") came entirely from the vision worker's own declared
   `raw_strengths`, which `vision=[]` never fetches. This is a real gap in
   what replay can reproduce, not a bug in the remap: on a run with real
   met-expectation or praised-verdict data, replay's `preserve` list is not
   empty.
3. No `redesignHtml` on any finding -- `redesign=[]` means
   `_generate_redesign_fragment` never ran.
4. `screenshotCrop`/`screenshotRef` absent on any finding whose evidence
   screenshot could not be remapped to a locally-kept file (most runs keep
   only a handful of screenshots, not every one the run took) -- on
   `last_runs/` this does not happen: all 6 kept screenshots remap cleanly.
5. `model_usage` carries no `report.redesign` role (no Python-side model
   call happened) but is otherwise identical -- the Node-side usage log is
   baked into each journey's own `modelUsage` field, unaffected by replay.
6. `step` is `None` on every finding in a replayed report, even findings
   whose real step is known. `_finding_step_index()` reads the leading
   digits off the evidence screenshot's own filename (`"001-as-they-saw-
   it.jpg"` -> step 1) -- a real, load-bearing convention both this
   codebase's captures and journeytest-core's own action captures already
   use, not a guess. `build_screenshot_remap()` renames every kept file to
   `<kind>__<artifact_id>.<ext>` (`last_runs/AGENTS.md`'s own naming, for
   snapshot hygiene unrelated to this), which destroys that leading number.
   Confirmed by running `assemble_report()` on the *unmapped* journey
   directly (no local screenshot files, so no crop, but the correct `step`):
   `step` resolves correctly there. `videoTimestampMs` is unaffected, for a
   different reason than it might look: the remap rewrites a path's
   *string*, consistently, everywhere it appears (the timeline event that
   records it and the finding that later cites it both end up naming the
   same local file), so a lookup keyed on string equality still matches.
   `step` fails because it needs information *encoded inside* the filename
   (the leading digits) that the remap's renaming destroys outright, not
   because the two sides of a comparison disagree.

Usage:
    replay_report.py <run-dir> [--diff] [--out FILE]

`--diff` also loads the run's own `ux_report__*.json` and prints a summary
of what differs, in the categories above.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.cycle.measure import _find_one  # noqa: E402  (path insert above)
from services.report_service.assembler import ReportAssembler  # noqa: E402

_ARTIFACT_FILENAME = re.compile(r".+__(art_[0-9a-f]+)\.\w+$")


def load_persona_profiles(run_dir: Path) -> list[dict[str, Any]]:
    matches = sorted((run_dir / "artifacts").glob("persona_profile__*.json"))
    return [json.loads(path.read_text()) for path in matches]


def load_job_metadata(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "logs" / "job_final.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _local_artifacts_by_id(run_dir: Path, glob_pattern: str) -> dict[str, Path]:
    out = {}
    for path in (run_dir / "artifacts").glob(glob_pattern):
        match = _ARTIFACT_FILENAME.match(path.name)
        if match:
            out[match.group(1)] = path
    return out


def _magic_matches(path: Path, original_name: str) -> bool:
    """Does the local file's own byte signature agree with what the original
    filename's extension claims? An unresolvable check (an unreadable file,
    or an extension this function does not know, such as `.webm`) returns
    True and defers to the positional-order match alone, which is already
    verified by count before this is called."""
    ext = Path(original_name).suffix.lower()
    try:
        head = path.open("rb").read(12)
    except OSError:
        return False
    is_png = head.startswith(b"\x89PNG")
    is_jpeg = head[:2] == b"\xff\xd8"
    if ext == ".png":
        return is_png
    if ext in (".jpg", ".jpeg"):
        return is_jpeg
    return True


def build_screenshot_remap(run_dir: Path, journeys: list[dict[str, Any]]) -> dict[str, str]:
    """original absolute path -> local file path, for every screenshot and
    video this snapshot kept, recovered from `logs/job_final.json`'s
    `output_artifacts` order and cross-checked by magic bytes (see the
    module docstring). A run whose screenshot count does not match the
    number of screenshot-kind ids found in `output_artifacts` is left
    unmapped rather than guessed -- this only happens when `job_final.json`
    is missing or stale, and an unmapped path simply means
    `_attach_verdict_screenshots` skips that finding's crop, the same
    graceful path it already takes for a screenshot never kept at all."""
    job_meta = load_job_metadata(run_dir)
    output_order = job_meta.get("output_artifacts") or []
    screenshot_local = _local_artifacts_by_id(run_dir, "browser_screenshot__*")
    video_local = _local_artifacts_by_id(run_dir, "browser_video__*")

    remap: dict[str, str] = {}
    for run in journeys:
        artifacts = run.get("artifacts") or {}
        original_screens = artifacts.get("screenshots") or []
        original_video = artifacts.get("video")

        ordered_screenshot_ids = [aid for aid in output_order if aid in screenshot_local]
        if ordered_screenshot_ids and len(ordered_screenshot_ids) == len(original_screens):
            for artifact_id, original in zip(ordered_screenshot_ids, original_screens):
                local_path = screenshot_local[artifact_id]
                if _magic_matches(local_path, original):
                    remap[original] = str(local_path)

        ordered_video_ids = [aid for aid in output_order if aid in video_local]
        if original_video and len(ordered_video_ids) == 1:
            remap[original_video] = str(video_local[ordered_video_ids[0]])

    return remap


def _remap_paths(value: Any, remap: dict[str, str]) -> Any:
    if isinstance(value, str):
        return remap.get(value, value)
    if isinstance(value, list):
        return [_remap_paths(item, remap) for item in value]
    if isinstance(value, dict):
        return {key: _remap_paths(item, remap) for key, item in value.items()}
    return value


def replay(run_dir: Path) -> dict[str, Any]:
    """Rebuild a ux.report from `run_dir`, no live worker, no model call."""
    journey_log = json.loads(_find_one(run_dir, "journey_log__*.json").read_text())
    journeys = journey_log.get("runs") or []
    if not journeys:
        raise ValueError(f"{run_dir}: journey_log has no runs to replay")

    personas = load_persona_profiles(run_dir)
    if not personas:
        raise ValueError(f"{run_dir}: no persona_profile__*.json artifacts found")

    job_meta = load_job_metadata(run_dir)
    metadata = job_meta.get("metadata") or {}
    url = metadata.get("url")
    tasks = metadata.get("tasks") or []
    if not url or not tasks:
        raise ValueError(
            f"{run_dir}: logs/job_final.json has no metadata.url/metadata.tasks -- "
            "replay needs it (last_runs/AGENTS.md step 2 already saves this file)."
        )

    remap = build_screenshot_remap(run_dir, journeys)
    journeys = [_remap_paths(run, remap) for run in journeys]

    return ReportAssembler.assemble_report(
        url=url,
        tasks=tasks,
        personas=personas,
        persona_artifacts=metadata.get("persona_artifacts") or [],
        journeys=journeys,
        worker_configured=True,
        job_id=job_meta.get("job_id"),
        vision=[],
        redesign=[],
        send_vision_options=False,
        redact_selectors=[],
    )


# ---------------------------------------------------------------------------
# Diffing against the live report
# ---------------------------------------------------------------------------


def _finding_titles(report: dict[str, Any]) -> list[str]:
    return [f.get("title") or "" for f in (report.get("critical_pain_points") or [])]


def diff_reports(replayed: dict[str, Any], live: dict[str, Any]) -> dict[str, Any]:
    """A summary diff, grouped by the categories the module docstring names --
    not a full structural diff, which would mostly restate that two
    independently-built dicts differ in key order and float precision.

    This also surfaces a second, welcome kind of difference the module
    docstring's five categories do not name: `assemble_report` is live code,
    so replaying an old run through today's tree picks up every report-side
    fix made since that run shipped, not only what vision/redesign being
    absent costs. On `last_runs/`, FND-1 (report-service, not this script)
    means replay no longer produces the four false "Fails WCAG AA contrast"
    titles the live snapshot still carries, and produces one grouped, honest
    finding the live snapshot does not have. `findings_missing_from_replay`/
    `findings_only_in_replay` will show both kinds of difference at once;
    telling them apart means checking whether the titles involved changed
    for a documented reason (a git-log question) or because vision/redesign
    were never called (this script's own doing).
    """
    replayed_titles, live_titles = _finding_titles(replayed), _finding_titles(live)
    missing_from_replay = [t for t in live_titles if t not in replayed_titles]
    extra_in_replay = [t for t in replayed_titles if t not in live_titles]

    def _findings_by_title(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {f.get("title"): f for f in (report.get("critical_pain_points") or [])}

    replayed_by_title, live_by_title = _findings_by_title(replayed), _findings_by_title(live)
    matched = set(replayed_by_title) & set(live_by_title)
    missing_crop = sorted(
        title for title in matched
        if live_by_title[title].get("screenshotCrop") and not replayed_by_title[title].get("screenshotCrop")
    )
    missing_redesign = sorted(
        title for title in matched
        if live_by_title[title].get("redesignHtml") and not replayed_by_title[title].get("redesignHtml")
    )

    live_usage = (live.get("model_usage") or {}).get("byRole") or {}
    replayed_usage = (replayed.get("model_usage") or {}).get("byRole") or {}

    return {
        "findings_missing_from_replay": missing_from_replay,
        "findings_only_in_replay": extra_in_replay,
        "matched_findings_missing_screenshot_crop": missing_crop,
        "matched_findings_missing_redesign_html": missing_redesign,
        "preserve_count": [len(replayed.get("elements_to_preserve") or []),
                           len(live.get("elements_to_preserve") or [])],
        "model_usage_roles": {"replayed": sorted(replayed_usage), "live": sorted(live_usage)},
        "evidence_language": [replayed.get("evidence_language"), live.get("evidence_language")],
        "journey_status": [
            (replayed.get("journey_outcome") or {}).get("status"),
            (live.get("journey_outcome") or {}).get("status"),
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--diff", action="store_true", help="also diff against the run's own ux_report")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    started = time.monotonic()
    report = replay(args.run_dir)
    elapsed = time.monotonic() - started

    if args.out:
        args.out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    else:
        print(json.dumps(report, indent=2, default=str))

    print(f"replayed in {elapsed:.2f}s", file=sys.stderr)

    if args.diff:
        live = json.loads(_find_one(args.run_dir, "ux_report__*.json").read_text())
        print(json.dumps(diff_reports(report, live), indent=2), file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
