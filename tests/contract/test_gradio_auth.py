from types import SimpleNamespace

import pytest

from apps.gradio.auth import request_identity, workspaces_from_profile


PROFILE = {"sub": "user-1", "name": "Ada", "preferred_username": "ada", "orgs": [{"sub": "org-1", "name": "Research", "roleInOrg": "write"}, {"sub": "blocked", "name": "Blocked", "securityRestrictions": ["mfa"]}]}


def test_space_profile_builds_namespaced_authorized_workspaces():
    assert [item["id"] for item in workspaces_from_profile(PROFILE)] == ["hf:user:user-1", "hf:org:org-1"]
    identity = request_identity(PROFILE, SimpleNamespace(token="oauth-token"), "hf:org:org-1")
    assert identity.authorization == "Bearer oauth-token"
    assert identity.user_id == "user-1"


def test_space_profile_rejects_forged_workspace_selection():
    with pytest.raises(PermissionError):
        request_identity(PROFILE, SimpleNamespace(token="oauth-token"), "hf:org:other")


def test_expired_sign_in_reads_as_a_prompt_not_a_traceback():
    """A Hugging Face OAuth token expires while the tab stays open, so the saved-report
    tabs' list_sessions()/list_artifacts() calls start returning 401 long after sign-in
    appeared to succeed. In production that surfaced as a raw
    `requests.exceptions.HTTPError: 401 Client Error: Unauthorized for url:
    http://127.0.0.1:8000/v1/sessions/.../artifacts` traceback in the UI."""
    import requests

    import app as gradio_app

    def http_error(status):
        response = requests.Response()
        response.status_code = status
        return requests.exceptions.HTTPError(f"{status} Client Error", response=response)

    assert "sign in" in gradio_app.workspace_access_message(http_error(401)).lower()
    assert "sign in" in gradio_app.workspace_access_message(http_error(403)).lower()
    assert "500" in gradio_app.workspace_access_message(http_error(500))
    assert "unreachable" in gradio_app.workspace_access_message(
        requests.exceptions.ConnectionError("connection refused"))
    assert "Sign in with Hugging Face to continue" in gradio_app.workspace_access_message(
        PermissionError("Sign in with Hugging Face to continue"))


def test_github_connection_sits_in_the_header_beside_the_hugging_face_sign_in():
    """Connecting GitHub is the same act as signing in -- attaching an account to
    the workspace -- and the token must be re-entered after every page reload
    because it is never stored server-side. Buried in the GitHub Backup tab it was
    a control a returning user had to go looking for."""
    import gradio as gr

    import app as gradio_app

    def ancestry(component):
        names, node = [], component
        while getattr(node, "parent", None) is not None:
            node = node.parent
            names.append(type(node).__name__)
        return names

    components = list(gradio_app.demo.blocks.values())
    token = next(c for c in components
                 if isinstance(c, gr.Textbox) and (c.label or "").startswith("GitHub token"))
    repo = next(c for c in components
                if isinstance(c, gr.Dropdown) and c.label == "Backup repository")
    workspace = next(c for c in components
                     if isinstance(c, gr.Dropdown) and c.label == "Workspace")

    # In the header, not inside any tab -- the same place the Workspace selector is.
    for component in (token, repo):
        assert "Tab" not in ancestry(component), ancestry(component)
        assert ancestry(component)[-1] == ancestry(workspace)[-1] == "Blocks"
    # The token is a secret, not free text.
    assert token.type == "password"
    # Exactly one place to enter it; the backup tab no longer defines its own.
    assert sum(1 for c in components
               if isinstance(c, gr.Textbox) and "GitHub" in (c.label or "")) == 1


def test_the_thought_log_tab_opens_on_the_journey_log_not_a_persona_profile():
    """The tab is named for the thought log, but its dropdown selects its first
    entry and persona profiles are written at session creation, so they sorted
    ahead of the journey log and the tab opened on a persona profile."""
    import app as gradio_app

    ordered = ("journey.log", "persona.profile")
    artifacts = [
        {"kind": "persona.profile", "artifact_id": "art_p1", "metadata": {}},
        {"kind": "persona.profile", "artifact_id": "art_p2", "metadata": {}},
        {"kind": "journey.log", "artifact_id": "art_log",
         "metadata": {"download_name": "journey-log-job_x.json"}},
    ]
    artifacts.sort(key=lambda item: list(ordered).index(item["kind"]))

    assert artifacts[0]["kind"] == "journey.log"
    # The profiles are still reachable, just not what the tab opens on.
    assert [item["kind"] for item in artifacts[1:]] == ["persona.profile", "persona.profile"]
    assert gradio_app.log_choices_kinds == ordered


def test_the_thought_log_shows_the_models_real_reasoning_interleaved_with_actions():
    import json

    import app as gradio_app

    log = {"runs": [{
        "runId": "run_1", "simulationProfile": {"persona": {"name": "Friedrich Wolf"}},
        "verdict": {"status": "passed", "confidence": "high", "summary": "Completed the tasks."},
        "reasoning": [
            {"elapsedMs": 7400, "text": "That opened a tool panel, not a description.", "model": "auto"},
            {"elapsedMs": 900, "text": "No sentence says what the product does.", "model": "auto"},
        ],
        "timeline": [{"type": "browser.click", "summary": "Clicked 'Nova Act'", "elapsedMs": 5200},
                     {"type": "browser.screenshot", "summary": "Captured screenshot", "elapsedMs": 5300}],
    }]}

    rendered = gradio_app.format_persona_thought_log(json.dumps(log))

    assert "2 model thought(s)" in rendered
    # In the order the model produced them, and interleaved with what it did.
    assert (rendered.index("No sentence says what the product does.")
            < rendered.index("Clicked 'Nova Act'")
            < rendered.index("That opened a tool panel"))
    assert "— _model reasoning_ · +0.9s" in rendered
    # Nested italics rendered as "_model reasoning _(+0.9s)__" in the tab.
    assert "_model reasoning _(" not in rendered
    # Pure plumbing captures stay out of the narrative.
    assert "Captured screenshot" not in rendered


def test_the_thought_log_says_so_when_a_run_captured_no_reasoning():
    """A run whose provider returned no reasoning must say that, not quietly show
    only browser actions as though that were the persona's thinking."""
    import json

    import app as gradio_app

    log = {"runs": [{"runId": "run_1", "simulationProfile": {"persona": {"name": "Ada"}},
                     "verdict": {"status": "passed", "confidence": "high", "summary": "Done."},
                     "reasoning": [],
                     "timeline": [{"type": "browser.click", "summary": "Clicked 'Sign in'", "elapsedMs": 100}]}]}

    rendered = gradio_app.format_persona_thought_log(json.dumps(log))

    assert "No model reasoning was captured" in rendered
    assert "model thought(s)" not in rendered


def test_framing_a_document_does_not_truncate_it_at_its_own_entities():
    """The slide deck embeds each redesign as a nested iframe whose srcdoc is
    escaped, so the deck contains &quot; sequences of its own. The old framing
    escaped only `"`, leaving those intact -- the browser decoded the first one and
    closed the outer srcdoc attribute there, discarding the rest of the deck
    including the <script> that makes it click-through. A real deck lost 74% of
    itself this way."""
    from html import unescape
    import re

    import app as gradio_app

    deck = ('<!doctype html><html><body>'
            '<iframe srcdoc="&lt;p&gt;before &amp;quot;quoted&amp;quot; after&lt;/p&gt;"></iframe>'
            '<div data-x="literal &quot;quotes&quot; here">text &amp; more</div>'
            "<script>document.querySelector('.deck').addEventListener('click',()=>show(current+1));</script>"
            '</body></html>')

    framed = gradio_app.frame_document(deck, "Saved UX slide deck")

    srcdoc = re.search(r'srcdoc="([^"]*)"', framed).group(1)
    # The attribute value must decode back to exactly the document we passed in --
    # nothing lost, nothing decoded early.
    assert unescape(srcdoc) == deck
    assert "addEventListener('click'" in unescape(srcdoc), "the navigation script must survive framing"
    assert framed.count("<iframe") == 1, "the nested iframe must stay inside the attribute, not escape it"


def test_a_framed_document_gets_its_own_viewport_instead_of_leaking_onto_the_page():
    """The presentation styles its sections min-height:90vh with content centred --
    a full-screen deck. gr.HTML injects with innerHTML, so leaked into the tab that
    made every section 90% of the browser viewport tall: the huge whitespace
    between the controls and the rendering."""
    import app as gradio_app

    framed = gradio_app.frame_document("<!doctype html><style>section{min-height:90vh}</style><section>x</section>",
                                       "Saved UX presentation")

    assert framed.startswith("<iframe")
    assert "height:78vh" in framed
    assert 'title="Saved UX presentation"' in framed
    # Sized by style, not a fixed pixel attribute, so it fits the window.
    assert "width=" not in framed and "height=" not in framed.replace("height:78vh", "")


def test_the_evidence_series_shows_one_frame_per_view_in_capture_order():
    """A run's screenshots are consecutive frames of one journey, not fifty
    unrelated files picked from a dropdown."""
    import app as gradio_app

    frames = [{"src": "data:image/jpeg;base64,AAA", "caption": "initial-view", "run": "run_1"},
              {"src": "data:image/jpeg;base64,BBB", "caption": "001-click-e21-after", "run": "run_1"},
              {"src": "data:image/jpeg;base64,CCC", "caption": "final-view", "run": "run_1"}]

    document = gradio_app.build_evidence_series(frames)

    assert document.count('class="frame') == 3
    # Exactly one starts active, and only the active one is displayed.
    assert document.count('class="frame active"') == 1
    assert ".frame{" in document.replace("\n", "") or "display:none" in document
    assert ".frame.active{display:flex}" in document
    # Click, buttons and arrow keys, the same interaction as the slide deck.
    assert "addEventListener('click'" in document
    assert "ArrowRight" in document and "ArrowLeft" in document
    assert 'id="next"' in document and 'id="prev"' in document
    # Captions carry the capture name, so a frame can be traced to its artifact.
    assert "001-click-e21-after" in document
    assert "1 / 3" in document and "3 / 3" in document
    assert gradio_app.build_evidence_series([]) == ""


def test_inlined_evidence_frames_are_bounded_in_size():
    """Unbounded, a real seven-frame run came to 2,146 KB of base64 in one page
    because two captures were full-page screenshots over 8,000px tall."""
    from io import BytesIO

    from PIL import Image

    import app as gradio_app

    tall = BytesIO()
    Image.new("RGB", (2400, 24000), color="white").save(tall, format="PNG")

    uri = gradio_app._thumbnail_data_uri(tall.getvalue())

    assert uri.startswith("data:image/jpeg;base64,")
    import base64 as b64
    with Image.open(BytesIO(b64.b64decode(uri.split(",", 1)[1]))) as scaled:
        assert scaled.width == 1100
        assert scaled.height == 2600, "a very tall page must be bounded, not shrunk to a strip"


def _recordings_session(artifacts):
    """A control-plane client stub exposing just what the Recordings tab uses."""
    class Client:
        def list_artifacts(self, session_id):
            return artifacts
        def download_artifact(self, artifact):
            return f"/tmp/{artifact['artifact_id']}.webm"
    return Client()


def _artifact(kind, artifact_id, run_id, stem=None):
    metadata = {"run_id": run_id}
    if stem:
        metadata["capture_stem"] = stem
    return {"kind": kind, "artifact_id": artifact_id, "metadata": metadata}


def test_recordings_are_discovered_one_entry_per_persona_run(monkeypatch):
    import app as gradio_app

    artifacts = [
        _artifact("browser.video", "art_v1", "run_a"),
        _artifact("browser.screenshot", "art_s1", "run_a", "initial-view"),
        _artifact("browser.screenshot", "art_s2", "run_a", "001-click-e1-after"),
        # A run whose recording never made it: it must still be listed, and say so.
        _artifact("browser.screenshot", "art_s3", "run_b", "initial-view"),
        _artifact("ux.report", "art_r", None),
    ]
    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: (_recordings_session(artifacts), None))

    runs, slider, picker, gallery, status = gradio_app.discover_recordings("ses_1", "ws", object(), object())

    assert [run["runId"] for run in runs] == ["run_a", "run_b"]
    assert runs[0]["shots"] == 2 and runs[0]["video"] == "art_v1"
    assert runs[1]["video"] is None and "no recording" in runs[1]["label"]
    assert slider["maximum"] == 2 and slider["label"] == "Recording 1 / 2"
    assert picker["choices"] == [run["label"] for run in runs]
    assert "2 persona run(s); 1 with a recording." == status


def test_the_slider_steps_between_recordings_and_says_which_one(monkeypatch):
    import app as gradio_app

    artifacts = [_artifact("browser.video", "art_v1", "run_a"), _artifact("browser.video", "art_v2", "run_b")]
    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: (_recordings_session(artifacts), None))
    runs = gradio_app.discover_recordings("ses_1", "ws", object(), object())[0]

    video, status, slider = gradio_app.show_recording(2, runs, "ses_1", "ws", object(), object())

    assert video["value"] == "/tmp/art_v2.webm" and video["visible"] is True
    assert slider["label"] == "Recording 2 / 2"
    assert "run_b" in status


def test_a_run_without_a_recording_points_at_the_gallery_instead(monkeypatch):
    import app as gradio_app

    artifacts = [_artifact("browser.screenshot", "art_s1", "run_a", "initial-view")]
    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: (_recordings_session(artifacts), None))
    runs = gradio_app.discover_recordings("ses_1", "ws", object(), object())[0]

    video, status, _ = gradio_app.show_recording(1, runs, "ses_1", "ws", object(), object())

    assert video["visible"] is False
    assert "screenshot gallery" in status


def test_comparing_recordings_plays_up_to_four_and_holds_the_pick_there(monkeypatch):
    import app as gradio_app

    artifacts = [_artifact("browser.video", f"art_v{n}", f"run_{n}") for n in range(1, 7)]
    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: (_recordings_session(artifacts), None))
    runs = gradio_app.discover_recordings("ses_1", "ws", object(), object())[0]

    labels = [run["label"] for run in runs]
    *videos, status, picker = gradio_app.compare_recordings(labels[:2], runs, "ses_1", "ws", object(), object())
    assert [v["visible"] for v in videos] == [True, True, False, False]
    assert "Playing 2 recording(s)." in status

    *videos, status, picker = gradio_app.compare_recordings(labels[:6], runs, "ses_1", "ws", object(), object())
    assert [v["visible"] for v in videos] == [True, True, True, True]
    assert "Four is the maximum" in status
    # The picker is held at four, so it shows what is actually playing.
    assert picker["value"] == labels[:4]


def test_recordings_modes_are_exclusive_and_video_is_the_default():
    import app as gradio_app

    def modes(mode, layout="Single", following=True):
        single, compare, live, gallery, layout_vis, timer = gradio_app.switch_recordings_mode(
            mode, layout, following)
        return ((single["visible"], compare["visible"], live["visible"], gallery["visible"]),
                layout_vis["visible"], timer["active"])

    visible, layout_shown, ticking = modes("Video")
    assert visible == (True, False, False, False)
    assert layout_shown is True
    # Nothing is polled unless the live view is on screen.
    assert ticking is False

    visible, _, _ = modes("Video", "Compare up to 4")
    assert visible == (False, True, False, False)

    visible, layout_shown, ticking = modes("Live")
    assert visible == (False, False, True, False)
    assert layout_shown is False, "the layout choice only applies to video"
    assert ticking is True

    # Unchecking Follow stops the polling without leaving the view.
    assert modes("Live", following=False)[2] is False

    visible, layout_shown, ticking = modes("Screenshot gallery")
    assert visible == (False, False, False, True)
    assert (layout_shown, ticking) == (False, False)


def _live_worker(routes):
    """A stand-in journey worker serving the live endpoints' real JSON shape."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = routes.get(self.path)
            self.send_response(200 if body is not None else 404)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body if body is not None else {"error": "not_found"}).encode())
        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_live_view_reads_frames_and_thoughts_from_the_worker(monkeypatch):
    """The recording is only finalized when a run ends, so a live view shows what
    does exist mid-flight: the newest frame on disk and the reasoning so far."""
    import app as gradio_app

    frame = "data:image/png;base64,iVBORw0KGgo="
    server = _live_worker({
        "/v1/runs/live": {"runs": [{"runId": "job_a_persona_1", "startedAt": 1, "thoughts": 2}]},
        "/v1/runs/job_a_persona_1/live": {
            "runId": "job_a_persona_1", "status": "live", "elapsedMs": 31200, "frames": 7,
            "frame": frame, "frameName": "001-click-e21-after.png",
            "reasoning": [{"elapsedMs": 900, "text": "The page has loaded."},
                          {"elapsedMs": 7400, "text": "That opened a tool panel, not a description."}]},
    })
    monkeypatch.setenv("JOURNEY_WORKER_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        assert [run["runId"] for run in gradio_app.fetch_live_runs()] == ["job_a_persona_1"]

        image, thoughts, note, timer, journey = gradio_app.poll_live_run("job_a_persona_1", True, "")

        assert image["visible"] is True and frame in image["value"]
        assert "001-click-e21-after.png" in image["value"]
        # Newest thought first: it is the one that explains what is on screen now.
        assert thoughts.index("That opened a tool panel") < thoughts.index("The page has loaded.")
        assert "7 frame(s)" in note and "2 thought(s)" in note and "31s" in note
        assert timer["active"] is True
    finally:
        server.shutdown()


def test_the_live_view_stops_polling_when_the_run_ends(monkeypatch):
    """A finished run's capture is cleared, so its absence is exactly the end of
    the run -- the view must stop polling rather than spin forever."""
    import app as gradio_app

    server = _live_worker({"/v1/runs/job_a_persona_1/live": {
        "runId": "job_a_persona_1", "status": "finished", "frames": 0, "frame": None, "reasoning": []}})
    monkeypatch.setenv("JOURNEY_WORKER_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        image, _, note, timer, journey = gradio_app.poll_live_run("job_a_persona_1", True, "")
        assert image["visible"] is False
        # The note is the signal the handoff keys on.
        assert "has finished" in note
        assert timer["active"] is False
    finally:
        server.shutdown()


def test_an_unreachable_worker_is_reported_and_does_not_spin(monkeypatch):
    import app as gradio_app

    # Nothing listening on this port.
    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://127.0.0.1:9")
    assert gradio_app.fetch_live_runs() == []

    image, _, note, timer, journey = gradio_app.poll_live_run("job_a_persona_1", True, "")
    assert image["visible"] is False
    assert "Could not reach the journey worker" in note
    assert timer["active"] is False


def test_a_live_run_that_has_not_written_a_frame_yet_still_follows(monkeypatch):
    import app as gradio_app

    server = _live_worker({"/v1/runs/r/live": {
        "runId": "r", "status": "live", "elapsedMs": 1200, "frames": 0, "frame": None,
        "reasoning": [{"elapsedMs": 500, "text": "Opening the base URL."}]}})
    monkeypatch.setenv("JOURNEY_WORKER_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        image, thoughts, note, timer, journey = gradio_app.poll_live_run("r", True, "")
        assert image["visible"] is False
        assert "has not written a frame yet" in note
        assert "Opening the base URL." in thoughts
        assert timer["active"] is True, "still live, so keep following"
    finally:
        server.shutdown()


def test_a_finished_stream_becomes_the_ordinary_recording_of_the_same_run(monkeypatch):
    """The live view is a stand-in for a recording that does not exist yet. When the
    run ends, the view should turn into that recording rather than leaving the
    reader on a dead frame."""
    import app as gradio_app

    artifacts = [
        _artifact("browser.video", "art_v1", "2026-08-30T14-58-52-774Z-job_abc"),
        _artifact("browser.screenshot", "art_s1", "2026-08-30T14-58-52-774Z-job_abc", "initial-view"),
        _artifact("browser.video", "art_v2", "2026-08-30T15-02-46-493Z-job_abc"),
    ]
    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: (_recordings_session(artifacts), None))

    mode, runs, slider, video, picker, status = gradio_app.hand_off_finished_run(
        "✔️ This run has finished — loading its recording…",
        "2026-08-30T15-02-46-493Z-job_abc", "ses_1", "ws", object(), object())

    assert mode["value"] == "Video", "the live view hands over to the normal recordings view"
    # The *second* run's recording, matched by journeytest-core's own run id.
    assert video["value"] == "/tmp/art_v2.webm" and video["visible"] is True
    assert slider["label"] == "Recording 2 / 2"
    assert "Stream finished" in status


def test_the_handoff_waits_when_the_recording_is_not_stored_yet(monkeypatch):
    """The executor writes artifacts when the whole job completes, so the first
    persona's recording is not on disk the moment its own stream ends. Switching to
    an empty Video view would be worse than saying so."""
    import app as gradio_app

    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: (_recordings_session([]), None))

    mode, runs, slider, video, picker, status = gradio_app.hand_off_finished_run(
        "✔️ This run has finished — loading its recording…",
        "2026-08-30T15-02-46-493Z-job_abc", "ses_1", "ws", object(), object())

    assert mode == gradio_app.gr.update(), "stays put rather than switching to nothing"
    assert "saved once the whole job completes" in status


def test_the_handoff_does_nothing_while_the_run_is_still_live(monkeypatch):
    import app as gradio_app

    calls = []
    monkeypatch.setattr(gradio_app, "authenticated_clients",
                        lambda *a, **k: calls.append(1) or (_recordings_session([]), None))

    result = gradio_app.hand_off_finished_run(
        "Live · 7 frame(s) captured · 2 thought(s) · running 31s",
        "run", "ses_1", "ws", object(), object())

    assert all(update == gradio_app.gr.update() for update in result)
    assert calls == [], "a live tick must not hit the control plane"


def test_the_diagnostics_panel_reports_a_failure_rather_than_becoming_one(monkeypatch):
    """Signed out, or with an expired token, this raised straight out of me() and
    put a traceback on screen -- from the panel whose whole job is to report
    system state."""
    import requests

    import app as gradio_app

    class Rejecting:
        def me(self):
            response = requests.Response()
            response.status_code = 401
            raise requests.exceptions.HTTPError("401 Client Error", response=response)

    monkeypatch.setattr(gradio_app, "authenticated_clients", lambda *a, **k: (Rejecting(), None))
    fn = next(dep.fn for dep in gradio_app.demo.fns.values()
              if getattr(dep.fn, "__name__", "") == "local_system_test")

    result = fn("ws", None, None)

    assert isinstance(result, dict)
    assert "sign in" in result["status"].lower()
    assert result["github_runtime_dependency"] is False


def test_saving_a_persona_reports_a_rejected_token_and_keeps_the_edit(monkeypatch):
    import requests

    import app as gradio_app

    def rejecting(*args, **kwargs):
        response = requests.Response()
        response.status_code = 401
        raise requests.exceptions.HTTPError("401 Client Error", response=response)

    monkeypatch.setattr(gradio_app, "authenticated_clients", rejecting)

    _, editor, personas, status = gradio_app.save_manual_persona(
        '{"id": "p1"}', [], 0, "ws", None, None)

    assert "sign in" in status.lower()
    # The edit the user typed must survive a failed save.
    assert editor == '{"id": "p1"}'

    _, editor, _, status = gradio_app.save_manual_persona("not json", [], 0, "ws", None, None)
    assert "not valid JSON" in status
    assert editor == "not json"
