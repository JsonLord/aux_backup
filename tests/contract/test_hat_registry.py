"""CAP-2: the hat registry -- what a hat adds, and only what it adds."""
import pytest

from apps.api.hats import HatError, HatRegistry


@pytest.fixture
def registry(tmp_path):
    return HatRegistry(f"sqlite:///{tmp_path / 'control.db'}")


def test_a_hat_needs_a_label(registry):
    with pytest.raises(HatError, match="label"):
        registry.put(label="")


def test_adds_must_be_a_list_of_names(registry):
    with pytest.raises(HatError, match="adds"):
        registry.put(label="Bad hat", adds=[123])


def test_a_hat_with_no_adds_is_the_plain_browsing_floor(registry):
    hat = registry.put(label="Plain browsing")

    assert hat["adds"] == []
    assert hat["roles"] == {} and hat["grants"] == {} and hat["profileDefaults"] == {}


def test_a_hat_records_what_it_adds_never_what_it_removes(registry):
    hat = registry.put(label="The integrator", adds=["developer"],
                       roles={"acting": "llm_abc", "reflection": "llm_def"},
                       grants={"developer": {"allowCommands": ["curl"], "hosts": ["example.com"]}},
                       profile_defaults={"patience": 0.6})

    assert hat["adds"] == ["developer"]
    assert hat["roles"] == {"acting": "llm_abc", "reflection": "llm_def"}
    assert hat["grants"]["developer"]["allowCommands"] == ["curl"]
    assert hat["profileDefaults"] == {"patience": 0.6}
    # No field anywhere in the record shape could express a removal -- see the
    # module docstring; this pins that there is no "removes"/"replaces" key.
    assert "removes" not in hat and "replaces" not in hat


def test_hats_are_scoped_to_a_workspace(registry):
    registry.put(workspace_id="alpha", label="Alpha's hat")
    registry.put(workspace_id="beta", label="Beta's hat")

    assert [h["label"] for h in registry.list_hats("alpha")] == ["Alpha's hat"]
    assert [h["label"] for h in registry.list_hats("beta")] == ["Beta's hat"]


def test_get_and_delete_are_scoped_to_a_workspace_too(registry):
    hat = registry.put(workspace_id="alpha", label="Alpha's hat")

    assert registry.get(hat["hat_id"], workspace_id="beta") is None
    assert registry.get(hat["hat_id"], workspace_id="alpha")["label"] == "Alpha's hat"
    assert registry.delete(hat["hat_id"], workspace_id="beta") is False
    assert registry.delete(hat["hat_id"], workspace_id="alpha") is True
    assert registry.get(hat["hat_id"], workspace_id="alpha") is None


def test_a_run_naming_a_hat_by_id_gets_its_adds_resolved(tmp_path, monkeypatch):
    """The Python side of CAP-2: a job names a hat, and the run's payload to
    the worker carries that hat's `adds` as hatExtras -- appended to browsing
    on the worker side (facultyWith), never a replacement for it."""
    import json as json_module

    from apps.api.executor import JobExecutor
    from apps.api.hats import HatRegistry
    from apps.api.store import Store

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'control.db'}")
    hat = HatRegistry(f"sqlite:///{tmp_path / 'control.db'}").put(
        workspace_id="local", label="The integrator", adds=["test-cap2-integration"])

    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}})

    captured = {}

    def dispatch(req, timeout):
        captured["payload"] = json_module.loads(req.data)

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        return Response(json_module.dumps({
            "runId": captured["payload"]["runId"], "runStatus": "completed",
            "profileId": "persona_ada", "simulationProfile": captured["payload"]["profile"],
            "verdict": {"status": "passed", "criteria": [], "blockers": [], "uxFindings": [],
                       "suggestedImprovements": []},
            "artifacts": {"screenshots": [], "snapshots": []}}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.delenv("EYESON_WORKER_URL", raising=False)
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": [persona["artifact_id"]], "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": [persona["artifact_id"]],
                    "tasks": ["Buy an item"], "hatId": hat["hat_id"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])

    assert store.get_job(job["job_id"])["status"] == "succeeded"
    assert captured["payload"]["hatExtras"] == ["test-cap2-integration"]


def test_a_run_naming_no_hat_sends_no_hatExtras_at_all(tmp_path, monkeypatch):
    """Absent, not an empty list -- a no-op on the worker side either way, but
    an absent field is what every other optional field here does."""
    import json as json_module

    from apps.api.executor import JobExecutor
    from apps.api.store import Store

    store = Store(f"sqlite:///{tmp_path / 'control.db'}", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'control.db'}")
    session = store.create_session({"metadata": {}, "external_ref": {}})
    persona = store.create_artifact({"session_id": session["session_id"], "kind": "persona.profile",
        "content_type": "application/json",
        "content": {"id": "persona_ada", "persona": {"name": "Ada"}, "abilities": {}, "behavior": {},
                    "generation": {"seed": 1}},
        "metadata": {}})

    captured = {}

    def dispatch(req, timeout):
        captured["payload"] = json_module.loads(req.data)

        class Response:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return self.body
        return Response(json_module.dumps({
            "runId": captured["payload"]["runId"], "runStatus": "completed",
            "profileId": "persona_ada", "simulationProfile": captured["payload"]["profile"],
            "verdict": {"status": "passed", "criteria": [], "blockers": [], "uxFindings": [],
                       "suggestedImprovements": []},
            "artifacts": {"screenshots": [], "snapshots": []}}).encode())

    monkeypatch.setenv("JOURNEY_WORKER_URL", "http://journey.invalid")
    monkeypatch.delenv("EYESON_WORKER_URL", raising=False)
    monkeypatch.setattr("apps.api.executor.request.urlopen", dispatch)
    job, _ = store.create_job({"session_id": session["session_id"], "type": "combined_test", "version": "1.0",
        "pipeline_run_id": None, "depends_on": [], "input_artifacts": [persona["artifact_id"]], "seed": 1,
        "metadata": {"url": "https://example.com", "persona_artifacts": [persona["artifact_id"]],
                    "tasks": ["Buy an item"]},
        "idempotency_key": None})
    JobExecutor(store).run(job["job_id"])

    assert store.get_job(job["job_id"])["status"] == "succeeded"
    assert "hatExtras" not in captured["payload"]
