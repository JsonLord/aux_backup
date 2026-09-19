"""Whose model budget a run spends, and whether it can be spent by mistake.

BE-1. The store, the roles and the retry discipline already existed; what did not
was anything routing a run through them. Every test here proves a refusal rather
than a happy path -- the happy path passed before this change too, which is
exactly why it could not have caught the defect.
"""

import pytest

from apps.api.model_routing import built_in_allowed, providers_for, record_model_access
from apps.api.model_settings import KIND_REFERENCE, ROLE_GENERATION, ModelSettingsStore
from services.persona_service.semantic import DirectLLMSemanticEngine


@pytest.fixture
def store(tmp_path):
    return ModelSettingsStore(f"sqlite:///{tmp_path}/settings.db")


@pytest.fixture(autouse=True)
def a_deployment_with_its_own_credentials(monkeypatch):
    """The Space ships with provider credentials in its environment. That is the
    whole hazard: every run was spending them, whoever asked."""
    monkeypatch.setenv("SPACE_ID", "Leon4gr45/aux-synthetic-ux-demo")
    monkeypatch.delenv("SPACE_AUTHOR_NAME", raising=False)
    monkeypatch.delenv("AUX_DEFAULT_PROVIDER_OWNERS", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-the-deployments-own")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://built-in.example/v1")
    monkeypatch.delenv("BLABLADOR_BASE_URL", raising=False)
    monkeypatch.delenv("BLABLADOR_API_KEY", raising=False)


def _configure(store, monkeypatch, *, url="https://mine.example/v1", model="my-model"):
    monkeypatch.setenv("MY_KEY", "sk-mine")
    store.save(workspace_id="w1", owner_user_id="u1", label="Mine", role=ROLE_GENERATION,
               base_url=url, model=model, kind=KIND_REFERENCE, secret_ref="MY_KEY")


def test_a_workspaces_own_provider_is_tried_before_the_deployments(store, monkeypatch):
    _configure(store, monkeypatch)

    chain = providers_for("w1", ROLE_GENERATION, built_in_allowed=True, store=store)

    assert chain[0] == ("https://mine.example/v1", "sk-mine", "my-model")
    assert ("https://built-in.example/v1", "sk-the-deployments-own", "auto") in chain


def test_a_caller_who_may_not_spend_the_built_ins_is_not_handed_them(store, monkeypatch):
    """The rail. Appending the deployment's providers to everybody's chain would
    make the admission gate decorative: refused at the door, served at the back."""
    _configure(store, monkeypatch)

    chain = providers_for("w1", ROLE_GENERATION, built_in_allowed=False, store=store)

    assert chain == [("https://mine.example/v1", "sk-mine", "my-model")]
    assert not any("built-in.example" in url for url, _, _ in chain)
    assert not any(key == "sk-the-deployments-own" for _, key, _ in chain)


def test_no_provider_and_no_permission_fails_rather_than_borrowing_one(store):
    """A stranger with nothing configured must not quietly run on the Space's key."""
    chain = providers_for("w1", ROLE_GENERATION, built_in_allowed=False, store=store)
    assert chain == []

    with pytest.raises(ValueError) as refused:
        DirectLLMSemanticEngine(providers=chain)
    assert "OPENAI_API_KEY" in str(refused.value) or "provider" in str(refused.value)


def test_an_engine_given_a_chain_is_held_to_it(store, monkeypatch):
    """Given providers, the engine runs on those and on nothing else -- otherwise
    a refused caller reaches the built-ins through the fallback instead."""
    _configure(store, monkeypatch)
    chain = providers_for("w1", ROLE_GENERATION, built_in_allowed=False, store=store)

    engine = DirectLLMSemanticEngine(providers=chain)

    assert [entry["base_url"] for entry in engine._chain()] == ["https://mine.example/v1"]


def test_a_configured_workspace_runs_with_no_key_in_the_environment(store, monkeypatch):
    """The point of the feature: bring your own provider and the deployment's
    absence stops mattering."""
    _configure(store, monkeypatch)
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("OPENAI_BASE_URL")

    engine = DirectLLMSemanticEngine(
        providers=providers_for("w1", ROLE_GENERATION, built_in_allowed=True, store=store))

    assert engine.base_url == "https://mine.example/v1"
    assert engine.model == "my-model"
    assert engine.api_key == "sk-mine"


def test_an_engine_given_nothing_behaves_exactly_as_before(monkeypatch):
    """Every caller not yet threaded must be unaffected."""
    engine = DirectLLMSemanticEngine()
    assert engine.base_url == "https://built-in.example/v1"
    assert engine.api_key == "sk-the-deployments-own"


def test_the_space_owner_is_recognised_by_username_not_by_subject_id():
    """Decision 2, and the regression it exists to prevent.

    In hf_token mode a job's owner_user_id is the Hugging Face `sub`, while the
    reserved-owner list holds usernames. Deciding this when the job runs, from
    what the job carries, would deny the Space's own owner the credentials
    reserved for them -- on every asynchronous run, with nothing in the failure
    that reads as being about identity.
    """
    auth = {"workspace_id": "w1", "owner_user_id": "6390b1a0f6c2e3d4",
            "user": {"id": "6390b1a0f6c2e3d4", "username": "Leon4gr45"}}

    assert record_model_access({}, auth)["modelAccess"]["builtInAllowed"] is True
    # What the job alone carries is not enough to reach that answer.
    assert record_model_access({}, {"owner_user_id": auth["owner_user_id"]}
                               )["modelAccess"]["builtInAllowed"] is False


def test_the_decision_is_fixed_at_creation_and_does_not_drift(monkeypatch):
    """Editing the owner list must not change what an already-created job may do."""
    monkeypatch.setenv("AUX_DEFAULT_PROVIDER_OWNERS", "someone-else")
    job = {"metadata": record_model_access({}, {"owner_user_id": "a-stranger"})}
    assert built_in_allowed(job) is False

    monkeypatch.setenv("AUX_DEFAULT_PROVIDER_OWNERS", "a-stranger")
    assert built_in_allowed(job) is False, "the recorded decision is what counts"


def test_a_job_created_before_this_existed_keeps_what_it_had():
    """Denying the built-ins retroactively would break every queued job on
    deploy, which is a worse failure than the one this guards against."""
    assert built_in_allowed({"metadata": {}}) is True
    assert built_in_allowed({}) is True


def test_a_job_resolves_its_own_chain_and_a_refused_job_gets_nothing(store, monkeypatch):
    """The wiring, not just the pieces: what a run is handed comes from the
    workspace on its job and the decision recorded on it."""
    from apps.api.executor import JobExecutor
    from apps.api.model_settings import ROLE_VISION

    monkeypatch.setenv("MY_KEY", "sk-mine")
    store.save(workspace_id="w1", owner_user_id="u1", label="Mine", role=ROLE_VISION,
               base_url="https://mine.example/v1", model="my-vision",
               kind=KIND_REFERENCE, secret_ref="MY_KEY")
    monkeypatch.setattr("apps.api.model_routing.settings_store", lambda: store)

    allowed = {"workspace_id": "w1",
               "metadata": record_model_access({}, {"user": {"username": "Leon4gr45"}})}
    refused = {"workspace_id": "w1",
               "metadata": record_model_access({}, {"owner_user_id": "a-stranger"})}

    assert JobExecutor._providers_for(allowed, ROLE_VISION)[0][0] == "https://mine.example/v1"
    assert any("built-in.example" in url
               for url, _, _ in JobExecutor._providers_for(allowed, ROLE_VISION))
    # The refused job reaches its own provider and never the deployment's.
    assert JobExecutor._providers_for(refused, ROLE_VISION) == [
        ("https://mine.example/v1", "sk-mine", "my-vision")]


def test_a_redesign_is_skipped_rather_than_made_on_credentials_the_caller_may_not_use(monkeypatch):
    """An empty chain means no model this caller may call -- so no re-design,
    which is honest, rather than one paid for by the deployment."""
    from apps.api.executor import JobExecutor

    def must_not_be_constructed(**kwargs):
        raise AssertionError("no engine may be built for a caller with no providers")

    import services.persona_service.semantic as semantic
    monkeypatch.setattr(semantic, "DirectLLMSemanticEngine", must_not_be_constructed)

    assert JobExecutor._generate_redesign_fragment({"title": "t"}, "https://example.com", []) is None
    assert JobExecutor._generate_ui_html("t", "r", None, None, []) is None


def test_somebody_trying_a_bundled_example_keeps_the_allowance_the_gate_gave_them():
    """app.py lets an example-persona run through on the Space's credentials. If
    the job did not carry that, the run would disagree with the gate and the demo
    path would quietly lose its re-designs."""
    stranger = {"owner_user_id": "a-visitor"}

    assert record_model_access({}, stranger)["modelAccess"]["builtInAllowed"] is False
    allowed = record_model_access({"examplePersona": "Friedrich_Wolf.agent.json"}, stranger,
                                  example_persona="Friedrich_Wolf.agent.json")
    assert allowed["modelAccess"]["builtInAllowed"] is True
