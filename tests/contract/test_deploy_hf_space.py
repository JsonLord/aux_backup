import pytest
from pathlib import Path

from scripts import deploy_hf_space


def test_resolve_token_prefers_hf_token(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_environment")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "hf_legacy")
    monkeypatch.setattr(deploy_hf_space, "get_token", lambda: "hf_cached")

    assert deploy_hf_space.resolve_token() == "hf_environment"


def test_resolve_token_accepts_cached_login(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.setattr(deploy_hf_space, "get_token", lambda: "hf_cached")

    assert deploy_hf_space.resolve_token() == "hf_cached"


def test_resolve_token_explains_that_username_is_not_authentication(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGING_FACE_HUB_TOKEN", raising=False)
    monkeypatch.setenv("HF_USERNAME", "registered-user")
    monkeypatch.setattr(deploy_hf_space, "get_token", lambda: None)

    with pytest.raises(SystemExit, match="HF_USERNAME alone"):
        deploy_hf_space.resolve_token()


def test_full_repo_deployment_context_applies_live_space_overlay():
    overlay = Path("spaces/aux-live").resolve()

    with deploy_hf_space.deployment_folder(overlay, full_repo=True) as staged:
        assert (staged / "apps/api/main.py").is_file()
        assert (staged / "services/persona_service/main.py").is_file()
        assert (staged / "services/journey-worker/node/src/index.js").is_file()
        assert (staged / "Dockerfile").read_text() == (overlay / "Dockerfile").read_text()
        assert (staged / "README.md").read_text() == (overlay / "README.md").read_text()
        assert not (staged / ".git").exists()
        assert not list(staged.rglob("node_modules"))
