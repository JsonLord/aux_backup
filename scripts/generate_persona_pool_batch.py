#!/usr/bin/env python3
"""Generate a batch of diverse personas for the GitHub-backed persona pool.

Run by .github/workflows/persona-pool-generate.yml on a schedule
(docs/persona-pool-plan.md component B). Calls the same TinyTroupeGenerator/
PersonaCompiler pipeline the live Space uses -- directly in-process, not over
HTTP, since nobody is waiting on this -- against a rotating set of theme/
customer-profile archetypes, and writes the results into a local checkout of
the pool repo (JsonLord/PersonaPool) alongside a regenerated index.json.
Also prunes entries older than --retention-days, deleting their files.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.persona_service.generator import TinyTroupeGenerator  # noqa: E402

# Broad enough that a later ranged-match query has something plausible to
# find (persona-pool-plan.md section 3): each customer_profile leans the
# generated persona's text toward a different behavioral flavor (patience,
# digital confidence, verification tendency, ...) since TinyTroupeGenerator
# has no direct numeric trait-target input -- behavior is compiled from the
# generated persona's description, not set by hand.
ARCHETYPES = [
    {"theme": "E-commerce checkout flow",
     "customer_profile": "Impatient online shoppers with low digital confidence who compare prices carefully before buying"},
    {"theme": "SaaS product onboarding",
     "customer_profile": "Busy, tech-savvy professionals evaluating a new software tool with high digital confidence and low patience for friction"},
    {"theme": "Customer support and contact flows",
     "customer_profile": "Frustrated customers with a problem, moderate digital confidence, seeking help quickly"},
    {"theme": "Content discovery and search",
     "customer_profile": "Curious, exploratory users with typical vision and high patience, browsing without a specific goal"},
    {"theme": "Healthcare appointment scheduling",
     "customer_profile": "Older adults with reduced visual acuity and lower digital confidence booking a medical appointment"},
    {"theme": "Banking and financial account management",
     "customer_profile": "Risk-averse, detail-oriented users with high verification tendency managing their finances online"},
]

_STOPWORDS = {"the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "who", "you", "your", "is", "are"}


def _keywords(text: str | None) -> list[str]:
    words = re.findall(r"[a-z0-9']+", (text or "").lower())
    return sorted({word for word in words if len(word) > 2 and word not in _STOPWORDS})


def _theme_tags(archetype: dict, profile: dict) -> list[str]:
    inner = profile.get("persona", {})
    persona_data = inner.get("persona", {}) if isinstance(inner.get("persona"), dict) else {}
    occupation = persona_data.get("occupation", {})
    tags = set(_keywords(archetype["theme"]))
    if isinstance(occupation, dict):
        tags.update(_keywords(occupation.get("title")))
    return sorted(tags)[:12]


def _summary(archetype: dict, profile: dict) -> str:
    name = profile.get("name") or profile.get("persona", {}).get("name") or "Unknown"
    return f"{name} -- {archetype['theme']}"


def build_batch(generator: TinyTroupeGenerator, count_per_theme: int, seed_base: int) -> tuple[list[dict], dict[str, dict]]:
    """Generate personas across every archetype. Returns (index_entries, profiles_by_id).

    A failure generating one archetype's batch is logged and skipped rather
    than aborting the whole run -- partial diversity beats no run at all for
    a scheduled, unattended job.
    """
    entries: list[dict] = []
    files: dict[str, dict] = {}
    for index, archetype in enumerate(ARCHETYPES):
        seed = seed_base + index
        try:
            profiles = generator.generate(archetype["theme"], archetype["customer_profile"], count_per_theme,
                                          scenario=archetype["theme"], seed=seed, allow_offline_fallback=False)
        except Exception as error:
            print(f"WARN: generation failed for archetype '{archetype['theme']}': {error}", file=sys.stderr)
            continue
        for profile in profiles:
            files[profile["id"]] = profile
            entries.append({
                "id": profile["id"],
                "path": None,  # filled in by write_batch once the date directory is known
                "date": None,
                "name": profile.get("name") or profile.get("persona", {}).get("name") or "Unknown",
                "summary": _summary(archetype, profile),
                "themeTags": _theme_tags(archetype, profile),
                "behavior": profile["behavior"],
                "source": profile.get("source"),
            })
    return entries, files


def write_batch(repo_dir: Path, entries: list[dict], files: dict[str, dict], today_iso: str) -> None:
    personas_dir = repo_dir / "personas" / today_iso
    personas_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        profile = files[entry["id"]]
        filename = f"{entry['id']}.json"
        (personas_dir / filename).write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
        entry["path"] = f"personas/{today_iso}/{filename}"
        entry["date"] = today_iso


def prune_index(entries: list[dict], retention_days: int, today: date) -> tuple[list[dict], list[dict]]:
    """Split entries into (kept, pruned) by age. An entry with a missing/unparseable
    date is kept -- never silently delete something we can't confidently date."""
    cutoff = today - timedelta(days=retention_days)
    kept, pruned = [], []
    for entry in entries:
        try:
            entry_date = date.fromisoformat(entry["date"])
        except (KeyError, TypeError, ValueError):
            kept.append(entry)
            continue
        (kept if entry_date >= cutoff else pruned).append(entry)
    return kept, pruned


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", required=True, type=Path, help="Local checkout of the pool repo")
    parser.add_argument("--count-per-theme", type=int, default=2)
    parser.add_argument("--seed-base", type=int, default=None, help="Defaults to a value derived from today's date")
    parser.add_argument("--retention-days", type=int, default=90)
    args = parser.parse_args()

    today = date.today()
    today_iso = today.isoformat()
    seed_base = args.seed_base if args.seed_base is not None else int(today.strftime("%Y%m%d"))

    generator = TinyTroupeGenerator()
    new_entries, files = build_batch(generator, args.count_per_theme, seed_base)
    write_batch(args.repo_dir, new_entries, files, today_iso)

    index_path = args.repo_dir / "index.json"
    existing = json.loads(index_path.read_text()) if index_path.exists() else []
    existing_ids = {entry["id"] for entry in existing}
    merged = existing + [entry for entry in new_entries if entry["id"] not in existing_ids]

    kept, pruned = prune_index(merged, args.retention_days, today)
    for entry in pruned:
        (args.repo_dir / entry["path"]).unlink(missing_ok=True)

    index_path.write_text(json.dumps(kept, indent=2, sort_keys=True) + "\n")

    print(f"Generated {len(new_entries)} new persona(s) across {len(ARCHETYPES)} archetype(s).")
    print(f"Pruned {len(pruned)} entr{'y' if len(pruned) == 1 else 'ies'} older than {args.retention_days} days.")
    print(f"Pool now has {len(kept)} total persona(s).")


if __name__ == "__main__":
    main()
