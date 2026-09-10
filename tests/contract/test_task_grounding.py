"""Tasks have to be about the site that is actually there.

Given only a URL the model invents the site from the domain name and the
persona. Against a real target it produced "Navigate to the 'Productivity for
AEC' section" and "Explore the 'Solutions' menu" for a page whose navigation is
Home / How it works / Install / Research / Pricing -- well-written tasks for a
site that does not exist. Reading the page first helps; checking afterwards is
what makes it a rule rather than a request.
"""
from apps.gradio.page_summary import (
    outline_vocabulary, tasks_that_invent_the_site, unfounded_references,
)

TAOHQ = {
    "url": "https://taoshq.com/", "title": "Tao HQ",
    "navigation": [{"text": "Home"}, {"text": "How it works"}, {"text": "Install"},
                   {"text": "Research"}, {"text": "Pricing"}],
    "headings": ["Three steps. Then it just runs in the background.",
                 "Five modes, matched to you"],
    "buttons": ["Start the free assessment", "Connect to your AI"],
    "textSample": "An AI layer that makes you better at your work.",
}


def test_the_two_inventions_a_live_run_actually_produced_are_caught():
    assert unfounded_references(
        "Navigate to the 'Productivity for AEC' section to see if it fits your practice.",
        TAOHQ) == ["Productivity for AEC"]
    assert unfounded_references("Explore the 'Solutions' menu for enterprise options.",
                                TAOHQ) == ["Solutions"]


def test_a_task_about_something_the_page_really_has_is_left_alone():
    """Rejecting good tasks is the way this check makes the product worse."""
    for task in [
        "Open the Pricing page and find out what a single seat costs.",
        "Click 'Start the free assessment' and see what it asks for.",
        "Read 'Five modes, matched to you' and decide whether any of them is you.",
        "Follow How it works and see whether the three steps are clear.",
    ]:
        assert unfounded_references(task, TAOHQ) == [], task


def test_looking_for_something_that_is_not_there_is_a_task_not_an_invention():
    """The prompt asks for exactly this when the persona wants something the page
    does not offer, so flagging it would punish the behaviour we want."""
    assert unfounded_references(
        "Look for a way to contact a human, and note whether one exists.", TAOHQ) == []
    assert unfounded_references(
        "Try to find a phone number or a support address anywhere on the site.", TAOHQ) == []


def test_a_name_is_founded_by_most_of_its_words_not_all_of_them():
    """A task is written by a model in its own words. Demanding an exact match
    would reject "the Pricing plans page" for a page whose heading is Pricing."""
    assert unfounded_references("Open the Pricing plans page.", TAOHQ) == []
    assert unfounded_references("Open the Enterprise Procurement page.", TAOHQ) == \
        ["Enterprise Procurement"]


def test_nothing_is_flagged_when_the_page_could_not_be_read():
    """Tasks written blind are already marked as such; calling them inventions on
    top of that would be false."""
    assert unfounded_references("Explore the 'Solutions' menu.", {}) == []
    assert tasks_that_invent_the_site(["Explore the 'Solutions' menu."], {}) == {}


def test_the_vocabulary_includes_where_the_links_go_not_only_their_labels():
    """A nav item labelled "Docs" pointing at /developer-guide founds a task about
    the developer guide."""
    outline = {"navigation": [{"text": "Docs", "url": "https://x.test/developer-guide"}]}
    assert "developer-guide" in outline_vocabulary(outline)
    assert unfounded_references("Open the Developer Guide and look for an API key.",
                                outline) == []


def test_a_batch_reports_every_task_that_invents_and_what_it_invented():
    tasks = [
        "Navigate to the 'Productivity for AEC' section.",
        "Open the Pricing page and find out what a seat costs.",
        "Explore the 'Solutions' menu.",
    ]
    invented = tasks_that_invent_the_site(tasks, TAOHQ)
    assert len(invented) == 2
    assert set(name for names in invented.values() for name in names) == \
        {"Productivity for AEC", "Solutions"}


class _Reply:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def _client_returning(*batches):
    """An LLM that answers with each batch in turn."""
    import json as _json

    replies = [_Reply(_json.dumps({"tasks": batch})) for batch in batches]
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs["messages"][0]["content"])
            return replies[min(len(calls) - 1, len(replies) - 1)]

    class Client:
        chat = type("Chat", (), {"completions": Completions()})()

    return Client(), calls


def test_a_batch_that_invents_the_site_is_sent_back_with_the_names_quoted(monkeypatch):
    """A rule that is checked, not just requested -- the same shape as the
    persona adherence gate."""
    import app

    invented = ["Explore the 'Solutions' menu for enterprise options."] * 6
    grounded = ["Open the Pricing page and find out what a single seat costs."] * 6
    client, calls = _client_returning(invented, grounded)
    monkeypatch.setattr(app, "get_llm_client", lambda: client)
    monkeypatch.setattr(app, "TASK_RETRY_WAIT_SECONDS", 0)

    tasks = app.generate_tasks("theme", "profile", "https://taoshq.com/", outline=TAOHQ)

    assert tasks == grounded
    assert len(calls) == 2, "the first batch was rejected and another asked for"
    assert '"Solutions"' in calls[1], "and the invented name went back with the request"


def test_tasks_that_never_come_back_clean_still_beat_numbered_placeholders(monkeypatch):
    """Discarding ten real tasks because one named an invented section, and
    shipping "Task 1 for {theme} (Manual fallback)" instead, is much worse."""
    import app

    invented = (["Explore the 'Solutions' menu."]
                + ["Open the Pricing page and read what a seat costs."] * 5)
    client, calls = _client_returning(invented)
    monkeypatch.setattr(app, "get_llm_client", lambda: client)
    monkeypatch.setattr(app, "TASK_RETRY_WAIT_SECONDS", 0)

    tasks = app.generate_tasks("theme", "profile", "https://taoshq.com/", outline=TAOHQ)

    assert tasks == invented
    assert not any("Manual fallback" in task for task in tasks)


def test_a_clean_batch_is_returned_without_a_second_call(monkeypatch):
    """The check costs nothing when the model got it right, which is most of the time."""
    import app

    grounded = ["Open the Pricing page and find out what a single seat costs."] * 6
    client, calls = _client_returning(grounded)
    monkeypatch.setattr(app, "get_llm_client", lambda: client)

    assert app.generate_tasks("theme", "profile", "https://taoshq.com/", outline=TAOHQ) == grounded
    assert len(calls) == 1
