"""Pinned TinyTroupe acceptance; requires the package and configured model provider."""
import os

import pytest

from services.persona_service.generator import TinyTroupeGenerator


pytestmark = pytest.mark.skipif(os.getenv("RUN_TINY_TROUPE_ACCEPTANCE") != "1", reason="RUN_TINY_TROUPE_ACCEPTANCE is not enabled")


def test_pinned_tinytroupe_produces_distinct_serializable_profiles(monkeypatch):
    monkeypatch.setenv("PERSONA_GENERATOR", "tinytroupe")
    generator = TinyTroupeGenerator()
    assert generator.tinytroupe_available
    profiles = generator.generate("checkout", "busy customers", 2, "Buy an item", 42)
    assert profiles[0]["id"] != profiles[1]["id"]
    assert profiles[0]["persona"] != profiles[1]["persona"]
    assert all(profile["generation"]["model"].startswith("tinytroupe@a6244b") for profile in profiles)
