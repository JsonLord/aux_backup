"""Compile one persona's actor against a corpus of its own judged actions.

The third tier of steering (scripts/actor_program.py): the gate
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
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from actor_program import (  # noqa: E402
    adherence_metric, adherence_prompt, build_signature, compile_actor,
    episodes_as_examples, instructions_of, parse_score,
)

# Two providers, and which one is used decides what the compile can afford.
#
# The router has a context window around a million tokens and returns clean
# content for a one-word answer at one completion token; Blablador's models spend
# their budget on reasoning they never return, so every call has to be sized for
# thinking nobody reads. The router is also what the journey worker's actor runs
# on in production, which makes compiling against it the honest measurement.
ROUTER = "https://debian-devil.tail3f341b.ts.net/v1"
BLABLADOR = "https://api.helmholtz-blablador.fz-juelich.de/v1"
PROVIDERS = {
    # (base url, env var holding the key)
    "router": (ROUTER, "freellmapi"),
    "blablador": (BLABLADOR, "BLABLADOR_API_KEY"),
}
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


def http_judge(base: str, model: str, key: str):
    """The same small model the run uses, against the same brief."""
    def judge(system: str, user: str) -> str:
        body = json.dumps({"model": model, "max_tokens": JUDGE_BUDGET,
                           "messages": [{"role": "system", "content": system},
                                        {"role": "user", "content": user}]}).encode()
        request = urllib.request.Request(
            f"{base}/chat/completions", data=body,
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


def score_of(program, examples, metric) -> tuple[float, int, int]:
    """Mean adherence over the trainset, how many fall below the gate's bar, and
    how many the endpoint never answered.

    One failed call costs one example. The first attempt at this let a single 502
    out of eighty-seven sequential requests end the whole compile before the
    baseline had finished measuring -- an hour of work thrown away by one bad
    gateway response, which is not a property of the actor being measured.
    """
    scored, total, below, lost = 0, 0.0, 0, 0
    started = time.monotonic()
    for index, example in enumerate(examples, start=1):
        try:
            prediction = program(persona=example.persona, task=example.task,
                                 observation=example.observation)
        except Exception:
            lost += 1
            continue
        result = metric(example, prediction)
        scored += 1
        total += result.score
        below += int(result.score < 0.7)
        # Said out loud, because a compile that prints nothing for an hour is
        # indistinguishable from one that has hung -- and two of them were killed
        # on a timeout before anyone could tell which.
        if index % 5 == 0 or index == len(examples):
            print(f"    {index}/{len(examples)} scored, mean {total / max(1, scored) * 10:.2f}/10, "
                  f"{lost} unanswered, {time.monotonic() - started:.0f}s elapsed", flush=True)
    return (total / scored if scored else 0.0), below, lost


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("-o", "--out", type=Path)
    parser.add_argument("--auto", default="light", choices=["light", "medium", "heavy"])
    parser.add_argument("--provider", default="router", choices=sorted(PROVIDERS))
    parser.add_argument("--actor-model", default="")
    parser.add_argument("--judge-model", default="")
    parser.add_argument("--reflection-model", default="")
    parser.add_argument("--limit", type=int, default=0, help="use only the first N examples")
    parser.add_argument("--measure-only", action="store_true",
                        help="score the uncompiled actor and stop")
    arguments = parser.parse_args()

    base, key_name = PROVIDERS[arguments.provider]
    key = os.getenv(key_name) or ""
    if not key:
        raise SystemExit(f"{key_name} is required: the judge and the actor both run on {base}.")
    # The router takes one model id and picks; Blablador is asked for a model by
    # name. Defaulted per provider rather than globally, so neither is ever sent
    # an id the other one's catalogue uses.
    default = "auto" if arguments.provider == "router" else "alias-fast"
    actor_model = arguments.actor_model or default
    judge_model = arguments.judge_model or default
    reflection_model = arguments.reflection_model or default

    import dspy

    bank = json.loads(arguments.corpus.read_text(encoding="utf-8"))
    persona = bank.get("persona") or {}
    examples = episodes_as_examples(bank, persona)
    if arguments.limit:
        examples = examples[: arguments.limit]
    if not examples:
        raise SystemExit("the corpus has no usable examples")
    print(f"{len(examples)} examples for {persona.get('id') or bank.get('personaId')} "
          f"on {arguments.provider} ({actor_model})")

    def lm(model: str, budget: int = ACTOR_BUDGET) -> "dspy.LM":
        # Retried inside the client: these endpoints return the occasional 502
        # from an upstream that took too long, and a compile measured over
        # eighty-seven sequential calls will meet one.
        return dspy.LM(f"openai/{model}", api_base=base, api_key=key,
                       max_tokens=budget, temperature=1.0, num_retries=3)

    dspy.configure(lm=lm(actor_model))
    metric = adherence_metric(http_judge(base, judge_model, key))
    program = dspy.Predict(build_signature())

    before, below_before, lost_before = score_of(program, examples, metric)
    print(f"before: mean adherence {before * 10:.2f}/10; "
          f"{below_before} below the gate's threshold; {lost_before} unanswered "
          f"of {len(examples)}")
    if arguments.measure_only:
        return

    print(f"compiling with GEPA (auto={arguments.auto}); this makes many more calls than the "
          f"baseline above, so expect it to take several times as long", flush=True)
    compiled = compile_actor(examples, http_judge(base, judge_model, key),
                             reflection_lm=lm(reflection_model), auto=arguments.auto)
    after, below_after, lost_after = score_of(compiled, examples, metric)
    print(f"after:  mean adherence {after * 10:.2f}/10; "
          f"{below_after} below the gate's threshold; {lost_after} unanswered "
          f"of {len(examples)}")

    text = instructions_of(compiled)
    if arguments.out:
        arguments.out.write_text(text, encoding="utf-8")
        print(f"instructions -> {arguments.out} ({len(text)} chars)")
    else:
        print("\n--- compiled instructions ---\n" + text)


if __name__ == "__main__":
    main()
