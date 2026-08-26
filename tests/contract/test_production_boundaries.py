import pytest
import asyncio
from fastapi import HTTPException

from apps.api.artifact_storage import R2ArtifactStorage
from apps.api.auth import IdentityProvider
from apps.api.tenant import current_workspace
from apps.api.queue import CeleryJobQueue


class Presigner:
    def __init__(self): self.calls = []
    def generate_presigned_url(self, operation, Params, ExpiresIn):
        self.calls.append((operation, Params))
        return f"https://r2.invalid/{Params['Key']}?expires={ExpiresIn}"
    def create_multipart_upload(self, **kwargs): return {"UploadId": "upload-1"}
    def complete_multipart_upload(self, **kwargs): self.completed = kwargs
    def head_object(self, **kwargs): return {"ContentLength": 27 * 1024**2}


def test_r2_presign_enforces_prefix_and_size_limits():
    storage = R2ArtifactStorage(Presigner(), "artifacts")
    upload = storage.presign_upload("workspace", "session", "artifact", 26 * 1024**2, "video/webm")
    assert upload.object_key == "workspace/session/artifact"
    with pytest.raises(ValueError, match="1 GB"):
        storage.presign_upload("w", "s", "a", 1024**3 + 1, "video/webm")


def test_verified_identity_rejects_non_member_workspace(monkeypatch):
    provider = IdentityProvider(mode="hf_oidc")
    monkeypatch.setattr(provider, "_claims", lambda token: {"sub": "user-1", "name": "User", "orgs": [{"sub": "org-1", "name": "Org A", "roleInOrg": "write"}]})
    result = provider.resolve("Bearer token", "hf:org:org-1", "ignored")
    assert result["workspace_id"] == "hf:org:org-1" and result["owner_user_id"] == "user-1" and result["role"] == "write"
    with pytest.raises(HTTPException) as error:
        provider.resolve("Bearer token", "hf:org:org-b", "ignored")
    assert error.value.status_code == 403


def test_hf_access_token_is_verified_by_userinfo(monkeypatch):
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"sub": "stable-user", "preferred_username": "ada", "name": "Ada", "orgs": [{"sub": "stable-org", "name": "Research", "roleInOrg": "admin"}]}
    monkeypatch.setattr("apps.api.auth.requests.get", lambda *args, **kwargs: Response())
    provider = IdentityProvider(mode="hf_token")
    result = provider.resolve("Bearer opaque-space-token", "hf:user:stable-user", "forged")
    assert result["user"]["username"] == "ada"
    assert [item["id"] for item in result["workspaces"]] == ["hf:user:stable-user", "hf:org:stable-org"]


def test_async_identity_sets_rls_context_for_request_task():
    async def resolve():
        provider = IdentityProvider(mode="local")
        result = await provider(None, "alpha", "user-a")
        return result, current_workspace()
    result, workspace = asyncio.run(resolve())
    assert result["workspace_id"] == workspace == "alpha"


def test_r2_multipart_lifecycle():
    client = Presigner()
    storage = R2ArtifactStorage(client, "artifacts")
    assert storage.create_multipart("w/s/a", "video/webm") == "upload-1"
    url = storage.presign_part("w/s/a", "upload-1", 2)
    assert "w/s/a" in url and client.calls[-1][0] == "upload_part"
    storage.complete_multipart("w/s/a", "upload-1", [{"ETag": "etag", "PartNumber": 2}])
    assert client.completed["MultipartUpload"]["Parts"][0]["ETag"] == "etag"


def test_service_credentials_do_not_trust_identity_headers():
    class Credentials:
        def verify_service_credential(self, credential_id, secret, workspace):
            return (credential_id, secret, workspace) == ("svc", "secret", "alpha")
    provider = IdentityProvider(mode="hf_oidc", membership_store=Credentials())
    assert provider.resolve("Service svc.secret", "alpha", "forged") == {"workspace_id": "alpha", "owner_user_id": "service:svc", "role": "service"}
    with pytest.raises(HTTPException): provider.resolve("Service svc.wrong", "alpha", "forged")


def test_celery_queue_dispatches_only_persisted_job_id():
    class Celery:
        def send_task(self, name, args, queue): self.sent = (name, args, queue)
    celery = Celery()
    CeleryJobQueue(celery).enqueue("job_123")
    assert celery.sent == ("aux.execute_job", ["job_123"], "jobs")
