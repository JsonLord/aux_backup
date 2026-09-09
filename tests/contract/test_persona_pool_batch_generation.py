import importlib.util
import json
from datetime import date
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "generate_persona_pool_batch", Path(__file__).parents[2] / "scripts" / "generate_persona_pool_batch.py")
batch_script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch_script)


class FakeGenerator:
    def __init__(self, profiles_by_theme=None, fail_themes=None):
        self.profiles_by_theme = profiles_by_theme or {}
        self.fail_themes = fail_themes or set()
        self.calls = []

    def generate(self, theme, customer_profile, count, scenario, seed, allow_offline_fallback=False):
        self.calls.append((theme, count, seed))
        if theme in self.fail_themes:
            raise RuntimeError("router unavailable")
        return self.profiles_by_theme.get(theme, [
            {"id": f"persona_{theme[:4]}_{i}", "source": "tinytroupe",
             "name": f"Persona {i}", "persona": {"name": f"Persona {i}", "occupation": "Shopper"},
             "behavior": {"patience": 0.5}}
            for i in range(count)
        ])


def test_theme_tags_include_theme_and_occupation_keywords():
    archetype = {"theme": "E-commerce checkout flow"}
    profile = {"persona": {"persona": {"occupation": {"title": "Software Engineer"}}}}

    tags = batch_script._theme_tags(archetype, profile)

    assert "checkout" in tags
    assert "software" in tags or "engineer" in tags


def test_theme_tags_tolerates_flat_offline_fallback_shape():
    archetype = {"theme": "Content discovery"}
    profile = {"persona": {"occupation": "Researcher"}}  # offline-fallback shape: no nested persona.persona

    tags = batch_script._theme_tags(archetype, profile)

    assert "content" in tags


def test_summary_prefers_top_level_name():
    archetype = {"theme": "SaaS onboarding"}
    profile = {"name": "Ada Lovelace", "persona": {"name": "fallback"}}

    assert batch_script._summary(archetype, profile) == "Ada Lovelace -- SaaS onboarding"


def test_build_batch_covers_every_archetype_and_labels_each_entry():
    generator = FakeGenerator()

    entries, files = batch_script.build_batch(generator, count_per_theme=2, seed_base=1000)

    assert len(entries) == len(batch_script.ARCHETYPES) * 2
    assert len(generator.calls) == len(batch_script.ARCHETYPES)
    assert all(entry["id"] in files for entry in entries)
    assert all(entry["path"] is None and entry["date"] is None for entry in entries)  # filled in by write_batch


def test_build_batch_skips_failing_archetype_without_aborting():
    generator = FakeGenerator(fail_themes={batch_script.ARCHETYPES[0]["theme"]})

    entries, files = batch_script.build_batch(generator, count_per_theme=1, seed_base=1)

    assert len(entries) == len(batch_script.ARCHETYPES) - 1


def test_write_batch_creates_dated_files_and_fills_in_paths(tmp_path):
    generator = FakeGenerator()
    entries, files = batch_script.build_batch(generator, count_per_theme=1, seed_base=1)

    batch_script.write_batch(tmp_path, entries, files, "2026-08-29")

    for entry in entries:
        assert entry["path"] == f"personas/2026-08-29/{entry['id']}.json"
        assert entry["date"] == "2026-08-29"
        written = json.loads((tmp_path / entry["path"]).read_text())
        assert written["id"] == entry["id"]


def test_prune_index_keeps_recent_and_drops_old_entries():
    entries = [
        {"id": "recent", "date": "2026-08-01", "path": "personas/2026-08-01/recent.json"},
        {"id": "old", "date": "2026-01-01", "path": "personas/2026-01-01/old.json"},
    ]

    kept, pruned = batch_script.prune_index(entries, retention_days=90, today=date(2026, 8, 29))

    assert [entry["id"] for entry in kept] == ["recent"]
    assert [entry["id"] for entry in pruned] == ["old"]


def test_prune_index_keeps_entries_with_missing_or_bad_dates():
    entries = [{"id": "no-date", "path": "x.json"}, {"id": "bad-date", "date": "not-a-date", "path": "y.json"}]

    kept, pruned = batch_script.prune_index(entries, retention_days=90, today=date(2026, 8, 29))

    assert {entry["id"] for entry in kept} == {"no-date", "bad-date"}
    assert pruned == []


def test_main_end_to_end_writes_index_and_prunes_stale_entries(tmp_path, monkeypatch, capsys):
    repo_dir = tmp_path
    old_dir = repo_dir / "personas" / "2020-01-01"
    old_dir.mkdir(parents=True)
    (old_dir / "persona_stale.json").write_text("{}")
    (repo_dir / "index.json").write_text(json.dumps([
        {"id": "persona_stale", "date": "2020-01-01", "path": "personas/2020-01-01/persona_stale.json",
         "name": "Stale", "summary": "old", "themeTags": [], "behavior": {}, "source": "tinytroupe"},
    ]))

    monkeypatch.setattr(batch_script, "TinyTroupeGenerator", lambda: FakeGenerator())
    monkeypatch.setattr("sys.argv", ["generate_persona_pool_batch.py", "--repo-dir", str(repo_dir),
                                     "--count-per-theme", "1", "--seed-base", "1", "--retention-days", "90"])

    batch_script.main()

    index = json.loads((repo_dir / "index.json").read_text())
    assert not any(entry["id"] == "persona_stale" for entry in index)
    assert not (old_dir / "persona_stale.json").exists()
    assert len(index) == len(batch_script.ARCHETYPES)
    output = capsys.readouterr().out
    assert "Pruned 1 entry" in output
