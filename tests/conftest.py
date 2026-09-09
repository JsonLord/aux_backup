import pytest


@pytest.fixture(autouse=True)
def no_live_redesign_calls(monkeypatch):
    """Keep the suite off the network.

    _attach_redesigns makes a real model call per finding when credentials are
    present, and this sandbox exports them -- which turned a 6-second suite into
    a 110-second one whose results depended on a live router. Redesign generation
    is therefore off by default in tests; the tests that cover it opt back in and
    stub the generator.
    """
    monkeypatch.setenv("EYESON_REDESIGN_LIMIT", "0")
