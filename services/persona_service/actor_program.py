"""Compiling an actor that does not need correcting.

There are three tiers of steering here and they do different work.

Within a step, the adherence gate scores the proposed action and, when it scores
badly, hands the criticism back and asks for another. That fixes the action and
learns nothing.

Across steps, the memory bank consolidates criticism that keeps recurring into
standing lessons in the persona's own voice, so the same mistake stops being made
inside one run and across later ones. That learns, but only by adding words to a
prompt nobody designed.

This is the third tier. The judgements the gate already produces are training
signal, and GEPA is the optimiser that can use them as they are: its metric
returns a score *and* a written reason, which is exactly the shape the gate emits
(`{"score": 1, "flaw": "Low patience makes such lengthy rereading unlikely"}`).
GEPA reads the reason and reflectively rewrites the program's instructions;
MIPROv2 or BootstrapFewShot would keep the 1 and discard the sentence, which is
the more informative half.

What comes out is instruction text for one persona, which the journey worker adds
to its system prompt. Success is measurable and not a matter of taste: the
regeneration rate the gate already counts should fall, which makes each run both
cheaper and more in character.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

# The judge's brief lives in one file because the compiler and the runtime must
# grade against the same thing. Optimising a prompt against a judge the run does
# not use would produce a number that means nothing.
ADHERENCE_PROMPT = (Path(__file__).resolve().parents[2] / "prompts" / "persona-adherence.txt")

# GEPA's metric works in 0..1; the judge answers out of 10.
SCORE_SCALE = 10.0

# Below this a step is worth learning from. At or above it the judge found
# nothing to say, and its flaw text is pro forma -- the same ceiling the memory
# bank uses, for the same reason.
LESSON_CEILING = 9


def adherence_prompt() -> str:
    return ADHERENCE_PROMPT.read_text(encoding="utf-8").strip()


def parse_score(text: str) -> dict | None:
    """Read the judge's answer, including one that was cut off mid-sentence.

    The router spends completion budget on reasoning it never returns, so a
    two-field object comes back truncated often enough to matter: measured at
    twenty-nine completion tokens against a budget of eight hundred. The score is
    asked for first precisely so it survives, and discarding a whole judgement
    over a half-finished sentence is how a gate silently stops working.
    """
    body = str(text or "")
    try:
        found = re.search(r"\{[\s\S]*\}", body)
        if found:
            parsed = json.loads(found.group(0))
            return {"score": max(0.0, min(10.0, float(parsed["score"]))),
                    "flaw": str(parsed.get("flaw") or "")}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        pass
    score = re.search(r'"score"\s*:\s*(-?\d+(?:\.\d+)?)', body)
    if not score:
        return None
    flaw = re.search(r'"flaw"\s*:\s*"((?:[^"\\]|\\.)*)', body)
    return {"score": max(0.0, min(10.0, float(score.group(1)))),
            "flaw": (flaw.group(1) if flaw else ""), "truncated": True}


def episodes_as_examples(bank: dict, persona: dict) -> list:
    """One memory bank turned into a trainset.

    Every judged action a persona has taken is already recorded with what they
    could see, what they expected and how the judge scored it. That is a labelled
    example without anyone having to write one.
    """
    import dspy

    examples = []
    for episode in bank.get("episodes", []):
        if not episode.get("visible"):
            continue
        examples.append(dspy.Example(
            persona=json.dumps(persona, sort_keys=True),
            observation=episode["visible"],
            task=episode.get("expectation", ""),
            action_type=episode["action"]["type"],
            action_target=episode["action"].get("target", ""),
        ).with_inputs("persona", "observation", "task"))
    return examples


def build_signature():
    """The actor's contract, mirroring what the journey worker asks of it.

    Deliberately the same three things in the same order -- what is visible, what
    is expected, then one action -- because that ordering is what makes the step
    falsifiable: an expectation committed to before acting can turn out wrong,
    and a vague one cannot.
    """
    import dspy

    class DecideNextAction(dspy.Signature):
        """Decide what this specific person does next on a web page.

        Answer as them. Never mention tools, refs or automation; those are how an
        action reaches the page, not how a person thinks about it.
        """

        persona: str = dspy.InputField(desc="who this person is, and their behavioural traits")
        task: str = dspy.InputField(desc="what they came to do, in their own words")
        observation: str = dspy.InputField(desc="only what they have actually looked at on the page")

        visible: str = dspy.OutputField(desc="what they can see, plainly, in the first person")
        expectation: str = dspy.OutputField(
            desc="specifically what they think will happen if they do the thing they are about to do")
        action_type: str = dspy.OutputField(desc="one of READ, CLICK, SCROLL, TYPE, GO_BACK, GIVE_UP, DONE")
        action_target: str = dspy.OutputField(desc="the element reference it applies to, or empty")

    return DecideNextAction


def adherence_metric(judge):
    """A GEPA metric: how much this action sounds like this person, and why.

    `judge` is any callable taking (system, user) and returning the model's text
    -- in practice the same small model the run uses, against the same brief.

    Returned as dspy.Prediction(score=..., feedback=...), which GEPA reads as
    ScoreWithFeedback. The feedback is the point: it is what lets the optimiser
    rewrite an instruction rather than only rank a candidate.
    """
    import dspy

    brief = adherence_prompt()

    def metric(example, prediction, trace=None, pred_name=None, pred_trace=None):
        action = (f"They say they can see: {getattr(prediction, 'visible', '')}\n"
                  f"They expect: {getattr(prediction, 'expectation', '')}\n"
                  f"They will: {getattr(prediction, 'action_type', '')} "
                  f"{getattr(prediction, 'action_target', '')}").strip()
        answered = judge(brief, f"THE PERSON:\n{example.persona}\n\nTHE PROPOSED NEXT ACTION:\n{action}")
        judged = parse_score(answered)
        if judged is None:
            # A judge that did not answer is not a failing action. Scoring it
            # zero would teach the optimiser to avoid whatever it happened to be
            # looking at when the endpoint hiccuped.
            return dspy.Prediction(score=0.5, feedback="The judge did not answer; this tells us nothing.")
        return dspy.Prediction(score=judged["score"] / SCORE_SCALE,
                               feedback=judged["flaw"] or "This is exactly what this person would do.")

    return metric


def compile_actor(trainset, judge, *, reflection_lm, auto: str = "light"):
    """Optimise the actor's instructions for one persona.

    GEPA rather than MIPROv2 or BootstrapFewShot for one concrete reason: it is
    the optimiser that consumes the written reason alongside the number, and the
    reasons are what the adherence judge is best at producing.
    """
    import dspy

    program = dspy.Predict(build_signature())
    optimiser = dspy.GEPA(metric=adherence_metric(judge), auto=auto, reflection_lm=reflection_lm)
    return optimiser.compile(program, trainset=trainset, valset=trainset)


def instructions_of(program) -> str:
    """The compiled instruction text, for the worker to add to its system prompt."""
    predictor = getattr(program, "predictors", lambda: [])()
    for candidate in predictor:
        instructions = getattr(getattr(candidate, "signature", None), "instructions", "")
        if instructions:
            return str(instructions)
    return ""
