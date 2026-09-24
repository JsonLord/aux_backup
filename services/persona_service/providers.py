"""Which model endpoints this deployment can use, resolved in one place.

The same resolution -- OPENAI_COMPATIBLE_ENDPOINT, then OPENAI_BASE_URL, then
BLABLADOR_BASE_URL, then a hard-coded router -- existed three times: in
generator.py for live generation, in dspy_program.py for compilation, and in
app.py for readiness. Adding a fallback to the first of those left the other two
reaching for an endpoint that was not there, and cycle 28 failed on exactly the
copy that had not been touched.

A model, an endpoint and a key are one setting, not three. Naming an alias
without its token is a 401 on every call, so each provider here carries all
three or is not offered at all.
"""

from __future__ import annotations

import os
import re

DEFAULT_ROUTER = "https://debian-devil.tail3f341b.ts.net/v1"

# A request that never reached a server: DNS, a dropped link, a provider
# restarting. Distinct from a provider that answered unhappily -- asking a
# different endpoint the same bad question only spends a second budget on the
# same failure.
_UNREACHABLE = re.compile(
    r"name resolution|nameresolution|failed to resolve|name or service not known"
    r"|network is unreachable|connection refused|connection reset|connection aborted"
    r"|max retries exceeded|temporary failure in name resolution|timed out|timeout"
    r"|econnrefused|econnreset|enotfound|eai_again|etimedout|ehostunreach|enetunreach"
    r"|apiconnectionerror|connection error"
    # A gateway that took the request and found nothing behind it to serve it.
    # 502, 503 and 504 are not the model answering unhappily -- no model saw the
    # question, so asking a different endpoint is not spending a second budget on
    # the same failure, it is the first budget finding somewhere to be spent.
    # Cycle 48 never started: four attempts, four 503s from one provider, and a
    # configured fallback that was never tried because a 503 read as an answer.
    r"|\b50[234] server error|service unavailable|bad gateway|gateway time-?out",
    re.I)


def model_providers() -> list[tuple[str, str, str]]:
    """Every (base_url, api_key, model) this deployment can call, in preference order.

    The second entry exists because the first keeps disappearing: the primary is
    reached over a Tailscale funnel, and when that link drops the name stops
    resolving from the Space entirely. Five cycles were lost to that while a
    second endpoint sat configured, reachable, and asked for nothing.
    """
    primary_key = os.getenv("OPENAI_API_KEY") or os.getenv("BLABLADOR_API_KEY")
    primary_url = (os.getenv("OPENAI_COMPATIBLE_ENDPOINT") or os.getenv("OPENAI_BASE_URL")
                   or os.getenv("BLABLADOR_BASE_URL") or DEFAULT_ROUTER)
    # A deployment with only Blablador configured resolves its "primary" to the
    # Blablador endpoint -- and must not then be handed the router's model id.
    # "auto" is the router's word; Blablador serves named models and answers 404
    # to it on every persona compile. The endpoint decides the model, not the
    # variable the endpoint happened to arrive in.
    on_the_spare = not (os.getenv("OPENAI_COMPATIBLE_ENDPOINT") or os.getenv("OPENAI_BASE_URL"))
    primary_model = os.getenv("OPENAI_MODEL") or (
        os.getenv("BLABLADOR_MODEL", "alias-large") if on_the_spare and os.getenv("BLABLADOR_BASE_URL")
        else "auto")
    # Blablador is credentialed for reflection already, so its key and endpoint
    # can be reached through either name.
    spare_url = os.getenv("BLABLADOR_BASE_URL") or os.getenv("JOURNEY_REFLECT_BASE_URL", "")
    spare_key = os.getenv("BLABLADOR_API_KEY") or os.getenv("JOURNEY_REFLECT_API_KEY", "")
    candidates = [
        (primary_url, primary_key, primary_model),
        # Generating and compiling a persona is a big, infrequent job, so the
        # spare runs a large model rather than the small one reflection uses --
        # alias-fast is chosen for reflection precisely because it is cheap and
        # frequent, and it is the wrong tool for writing a person.
        (spare_url, spare_key, os.getenv("BLABLADOR_MODEL", "alias-large")),
        (spare_url, spare_key, os.getenv("BLABLADOR_FALLBACK_MODEL", "alias-huge")),
    ]
    chosen: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for url, key, model in candidates:
        url = (url or "").rstrip("/")
        # Keyed on endpoint *and* model: two aliases on one host are two
        # providers, and deduplicating on the host alone would silently drop the
        # second of them.
        if not url or not key or not model or (url, model) in seen:
            continue
        seen.add((url, model))
        chosen.append((url, key, model))
    return chosen


def require_providers() -> list[tuple[str, str, str]]:
    providers = model_providers()
    if not providers:
        raise RuntimeError("OPENAI_API_KEY or BLABLADOR_API_KEY is required")
    return providers


def why(error: BaseException | None) -> str:
    """The real cause, when it is hiding one level down under __cause__."""
    parts: list[str] = []
    current, depth = error, 0
    while current is not None and depth < 4:
        text = str(current) or type(current).__name__
        if text and text not in parts:
            parts.append(text)
        current, depth = getattr(current, "__cause__", None), depth + 1
    return " <- ".join(parts)[:300]


def unreachable(error: BaseException | None) -> bool:
    """No model answered. Distinct from a model answering unhappily.

    The line is not whether bytes came back -- a 503 from a gateway is bytes --
    but whether anything got as far as reading the question. A 400 or a 401 is a
    verdict on what was asked and the next provider will reach the same one; a
    dropped connection or a gateway with nothing behind it is not a verdict at
    all.
    """
    return bool(error) and bool(_UNREACHABLE.search(why(error)))
