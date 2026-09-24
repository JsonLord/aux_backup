"""Compiling an actor that does not need correcting.

The gate corrects one action, the memory bank makes the correction stick across
steps, and this turns both into a better prompt offline. What has to be pinned is
the thing that would quietly invalidate all of it: the compiler grading against a
different judge than the run uses.
"""
import json
from pathlib import Path

import pytest

from scripts.actor_program import (
    LESSON_CEILING, SCORE_SCALE, adherence_metric, adherence_prompt, episodes_as_examples,
    parse_score,
)

dspy = pytest.importorskip("dspy")


def test_the_compiler_and_the_run_grade_against_one_brief():
    """Optimising a prompt against a judge the run does not use produces a number
    that means nothing, and nothing about either file would look wrong."""
    shared = adherence_prompt()
    worker = Path("services/journey-worker/node/src/adherence.js").read_text(encoding="utf-8")

    start = worker.index("const ADHERENCE_SYSTEM = `") + len("const ADHERENCE_SYSTEM = `")
    inline = worker[start:worker.index("`;", start)].strip()
    assert inline == shared, (
        "prompts/persona-adherence.txt and adherence.js have drifted; the run and the "
        "compiler would be scoring against different judges")


def test_a_judgement_cut_off_mid_sentence_still_scores():
    """The router spends completion budget on reasoning it never returns, so a
    two-field answer comes back truncated often enough to matter -- measured at
    29 completion tokens against a budget of 800."""
    cut = '{"score": 0, "flaw": "His impatience makes reading a whole philosophy sec'
    assert parse_score(cut)["score"] == 0.0
    assert parse_score(cut)["truncated"] is True
    assert parse_score('{"score": 11}')["score"] == 10.0, "out of range is clamped, not believed"
    assert parse_score("no json here") is None


def test_the_metric_hands_gepa_the_reason_not_only_the_number():
    """The whole reason for choosing GEPA: it reads the written feedback and
    rewrites an instruction with it. MIPROv2 would keep the 1 and drop the
    sentence, which is the more informative half."""
    metric = adherence_metric(
        lambda system, user: '{"score": 2, "flaw": "Low patience makes such rereading unlikely"}')
    result = metric(dspy.Example(persona="Friedrich, patience 0.20"),
                    dspy.Prediction(visible="copy", expectation="a price", action_type="READ",
                                    action_target="e1"))
    assert result.score == 0.2, "the judge answers out of ten and GEPA works in 0..1"
    assert "Low patience" in result.feedback


def test_an_action_that_fits_still_gets_feedback_worth_reading():
    metric = adherence_metric(lambda system, user: '{"score": 10, "flaw": ""}')
    result = metric(dspy.Example(persona="Friedrich"), dspy.Prediction(action_type="GIVE_UP"))
    assert result.score == 1.0
    assert result.feedback, "GEPA needs something said about a success too"


def test_a_judge_that_did_not_answer_is_not_a_failing_action():
    """Scoring it zero would teach the optimiser to avoid whatever it happened to
    be looking at when the endpoint hiccuped."""
    metric = adherence_metric(lambda system, user: "the endpoint fell over")
    result = metric(dspy.Example(persona="Friedrich"), dspy.Prediction(action_type="READ"))
    assert result.score == 0.5
    assert "did not answer" in result.feedback


def test_a_memory_bank_is_already_a_trainset():
    """Every judged action is recorded with what they saw, what they expected and
    how it scored. Nobody has to write a labelled example."""
    bank = {"episodes": [
        {"visible": "a page of vision statements", "expectation": "a price",
         "action": {"type": "READ", "target": "e1"}, "score": 3, "flaw": "too patient", "passed": False},
        {"visible": "still no numbers", "expectation": "there is no price here",
         "action": {"type": "GIVE_UP", "target": ""}, "score": 10, "flaw": "", "passed": True},
        # No observation recorded: not an example, because the input is missing.
        {"visible": "", "action": {"type": "SCROLL"}, "score": 5, "passed": False},
    ]}
    examples = episodes_as_examples(bank, {"name": "Friedrich Wolf"})
    assert len(examples) == 2
    assert examples[0].observation == "a page of vision statements"
    assert set(examples[0].inputs().keys()) == {"persona", "observation", "task"}
    assert json.loads(examples[0].persona)["name"] == "Friedrich Wolf"


def test_the_ceiling_matches_the_one_the_memory_bank_uses():
    """Both decide what counts as criticism worth learning from, and a run where
    the two disagree learns different things at runtime and at compile time."""
    worker = Path("services/journey-worker/node/src/memoryBank.js").read_text(encoding="utf-8")
    assert f"const LESSON_CEILING = {LESSON_CEILING};" in worker
    assert SCORE_SCALE == 10.0
