"""Compile one persona's actor against a corpus of its own judged actions.

The third tier of steering (services/persona_service/actor_program.py): the gate
fixes an action and learns nothing, the memory bank learns within and across runs
by adding words to a prompt nobody designed, and this rewrites the instructions
themselves from the judgements both of those already produce.

Success is not a matter of taste. The gate counts how often it has to send an
action back; compiled instructions should make it count lower. Run the evaluation
before and after against the same trainset and the same judge, and compare.

Usage:
    python scripts/compile_actor.py corpus.json -o instructions.txt [--auto light]
    python scripts/compile_actor.py corpus.json --measure-only
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.persona_service.actor_program import (  # noqa: E402
    adherence_metric, adherence_prompt, build_signature, compile_actor,
    episodes_as_examples, instructions_of, parse_score,
)

BLABLADOR = "https://api.helmholtz-blablador.fz-juelich.de/v1"
# Both endpoints spend completion budget on reasoning they never return, so both
# budgets are set past what the visible answer needs rather than at it.
#
# The judge answers in two short fields: at 20 tokens it came back with
# content: null and finish_reason: length, and measured working at 400.
JUDGE_BUDGET = 600
# The actor answers in four, after reasoning at length about who the person is --
# one observed thinking block ran to 2,000 characters before the first field. At
# 600 it returned text: None with the whole budget spent on reasoning_content,
# which dspy reports as "The LM returned an empty or null response".
ACTOR_BUDGET = 6000


def blablador_judge(model: str, key: str):
    """The same small model the run uses, against the same brief."""
    def judge(system: str, user: str) -> str:
        body = json.dumps({"model": model, "max_tokens": JUDGE_BUDGET,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}]}).encode()
        request = urllib.request.Request(
            f"{BLABLADOR}/chat/completions", data=body,
            headers={"content-type": "application/json", "authorization": f"Bearer {key}"})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                answer = json.load(response)
            return answer["choices"][0]["message"].get("content") or ""
        except Exception:
            # A judge that did not answer is not a failing action; the metric
            # already scores that case as "this tells us nothing".
            return ""
    return judge


def score_of(program, examples, metric) -> tuple[float, int]:
    """Mean adherence over the trainset, and how many fall below the gate's bar."""
    total, below = 0.0, 0
    for example in examples:
        prediction = program(persona=example.persona, task=example.task,
                             observation=example.observation)
        result = metric(example, prediction)
        total += result.score
        below += int(result.score < 0.7)
    return (total / len(examples) if examples else 0.0), below


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("-o", "--out", type=Path)
    parser.add_argument("--auto", default="light", choices=["light", "medium", "heavy"])
    parser.add_argument("--actor-model", default="alias-large")
    parser.add_argument("--judge-model", default="alias-fast")
    parser.add_argument("--reflection-model", default="alias-large")
    parser.add_argument("--limit", type=int, default=0, help="use only the first N examples")
    parser.add_argument("--measure-only", action="store_true",
                        help="score the uncompiled actor and stop")
    arguments = parser.parse_args()

    key = os.getenv("BLABLADOR_API_KEY") or ""
    if not key:
        raise SystemExit("BLABLADOR_API_KEY is required: the judge and the actor both run on it.")

    import dspy

    bank = json.loads(arguments.corpus.read_text(encoding="utf-8"))
    persona = bank.get("persona") or {}
    examples = episodes_as_examples(bank, persona)
    if arguments.limit:
        examples = examples[: arguments.limit]
    if not examples:
        raise SystemExit("the corpus has no usable examples")
    print(f"{len(examples)} examples for {persona.get('id') or bank.get('personaId')}")

    def lm(model: str, budget: int = ACTOR_BUDGET) -> "dspy.LM":
        return dspy.LM(f"openai/{model}", api_base=BLABLADOR, api_key=key,
                       max_tokens=budget, temperature=1.0)

    dspy.configure(lm=lm(arguments.actor_model))
    metric = adherence_metric(blablador_judge(arguments.judge_model, key))
    program = dspy.Predict(build_signature())

    before, below_before = score_of(program, examples, metric)
    print(f"before: mean adherence {before * 10:.2f}/10; "
          f"{below_before} of {len(examples)} below the gate's threshold")
    if arguments.measure_only:
        return

    compiled = compile_actor(examples, blablador_judge(arguments.judge_model, key),
                             reflection_lm=lm(arguments.reflection_model), auto=arguments.auto)
    after, below_after = score_of(compiled, examples, metric)
    print(f"after:  mean adherence {after * 10:.2f}/10; "
          f"{below_after} of {len(examples)} below the gate's threshold")

    text = instructions_of(compiled)
    if arguments.out:
        arguments.out.write_text(text, encoding="utf-8")
        print(f"instructions -> {arguments.out} ({len(text)} chars)")
    else:
        print("\n--- compiled instructions ---\n" + text)


if __name__ == "__main__":
    main()
