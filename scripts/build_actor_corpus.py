"""Turn finished runs into a trainset for compiling the actor.

Every judged action a persona has taken is already a labelled example and nobody
had to write it: the director records what they could see and what they expected
before acting (`persona.expectation`), and the adherence gate records how much it
sounded like them and why (`persona.adherence`). That pair is exactly the shape
`scripts/actor_program.episodes_as_examples` consumes.

The runs are the corpus. Reading them from journey logs rather than from a live
memory bank matters for two reasons: a bank holds one persona's history and only
from the moment persistence was configured, while the logs go back over every run
ever kept -- and a bank on an ephemeral Space disappears with the container.

Usage:
    python scripts/build_actor_corpus.py <journey-log-or-dir>... -o corpus.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# The director records adherence for a step and then the expectation for the same
# step (services/journey-worker/node/src/personaDirector.js), so an adherence
# event is answered by the next expectation event. Pairing the other way round
# labels every action with the previous step's score.
ADHERENCE = "persona.adherence"
EXPECTATION = "persona.expectation"


def runs_in(path: Path):
    """Every run in a journey log, or in every journey log under a directory."""
    files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    for file in files:
        try:
            document = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        runs = document.get("runs") if isinstance(document, dict) else None
        for run in runs or []:
            if run.get("timeline"):
                yield file, run


def episodes_of(run: dict) -> list[dict]:
    """The judged actions in one run, as memory-bank episodes.

    An action with nothing recorded about what the person could see is dropped:
    it cannot teach anything about deciding from a page, and
    `episodes_as_examples` skips it anyway.
    """
    episodes: list[dict] = []
    pending: dict | None = None
    for event in run.get("timeline") or []:
        kind, data = event.get("type"), event.get("data") or {}
        if kind == ADHERENCE:
            pending = data
        elif kind == EXPECTATION and pending is not None:
            visible = str(data.get("visible") or "").strip()
            settled = data.get("action") or {}
            if visible:
                # Every attempt at this step, not only the one that survived. A
                # rejected action carries the sentence saying why it did not sound
                # like this person, which is the most informative example the gate
                # produces -- and a corpus of actions that all passed teaches an
                # optimiser very little. The rejected ones are in `history`, each
                # with the action it judged.
                attempts = pending.get("history") or [pending]
                for index, attempt in enumerate(attempts):
                    action = attempt.get("action")
                    # The last judgement in a history is the settled one, so it is
                    # the action the step actually took. Any earlier entry without
                    # an action of its own comes from a log written before the gate
                    # kept them, and is dropped rather than guessed at: pairing a
                    # rejected attempt's criticism with the action that replaced it
                    # would label a good action with the reason a different one was
                    # thrown away, and teach the optimiser something false.
                    if not action and index == len(attempts) - 1:
                        action = settled
                    if not action or not action.get("type"):
                        continue
                    episodes.append({
                        "action": action,
                        "visible": visible,
                        "expectation": str(data.get("expectation") or "").strip(),
                        "score": attempt.get("score"),
                        "flaw": str(attempt.get("flaw") or "").strip(),
                        "passed": bool(attempt.get("score", 0) >= (pending.get("threshold") or 7)),
                        "runId": run.get("runId"),
                    })
            pending = None
    return episodes


def build(paths: list[Path]) -> dict:
    episodes: list[dict] = []
    persona: dict = {}
    runs = 0
    for _, run in (pair for path in paths for pair in runs_in(path)):
        found = episodes_of(run)
        if not found:
            continue
        runs += 1
        episodes.extend(found)
        # Any run's profile will do as the persona: the corpus is per-person, and
        # a corpus spanning two people would compile instructions for neither.
        persona = persona or (run.get("simulationProfile") or {})
    return {"personaId": persona.get("id") or "corpus", "persona": persona,
            "runs": runs, "episodes": episodes}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    arguments = parser.parse_args()

    corpus = build(arguments.paths)
    arguments.out.write_text(json.dumps(corpus, indent=1), encoding="utf-8")
    scores = [item["score"] for item in corpus["episodes"] if isinstance(item.get("score"), (int, float))]
    below = [score for score in scores if score < 7]
    print(f"{len(corpus['episodes'])} judged actions from {corpus['runs']} run(s) -> {arguments.out}")
    if scores:
        print(f"mean adherence {sum(scores) / len(scores):.2f}/10; "
              f"{len(below)} of {len(scores)} scored below the gate's threshold of 7")


if __name__ == "__main__":
    main()
