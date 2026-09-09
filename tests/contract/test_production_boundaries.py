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


def test_hf_personal_token_is_verified_for_personal_workspace_only(monkeypatch):
    class OAuthResponse:
        def raise_for_status(self):
            raise __import__("requests").HTTPError("not an OAuth token")

    class WhoamiResponse:
        def raise_for_status(self): pass
        def json(self):
            # whoami-v2's `id` is the same stable account identifier OAuth userinfo
            # returns as `sub`; `name` is the username.
            return {"type": "user", "id": "675f37b072d14a2cff8b7343", "name": "ada", "fullname": "Ada",
                    "orgs": [{"name": "untrusted-org"}]}

    responses = iter([OAuthResponse(), WhoamiResponse()])
    monkeypatch.setattr("apps.api.auth.requests.get", lambda *args, **kwargs: next(responses))
    provider = IdentityProvider(mode="hf_token")

    result = provider.resolve("Bearer hf-personal-token", "hf:user:675f37b072d14a2cff8b7343", "forged")

    assert result["owner_user_id"] == "675f37b072d14a2cff8b7343"
    assert result["workspaces"] == [
        {"id": "hf:user:675f37b072d14a2cff8b7343", "name": "Ada", "type": "personal", "role": "owner"}]


def test_a_personal_token_and_an_oauth_login_reach_the_same_workspace(monkeypatch):
    """The same person must land in one workspace whichever credential they present.

    OAuth userinfo returns the account's stable id as `sub`, but the personal-token
    fallback used to return the *username*, so a session created through the API
    with a token went to "hf:user:<username>" while the browser -- signed in with
    OAuth -- asked for "hf:user:<id>" and got
    `GET /v1/sessions/.../artifacts 404 Not Found` for every session it had.
    """
    class Response:
        def __init__(self, payload, fail=False):
            self.payload, self.fail = payload, fail
        def raise_for_status(self):
            if self.fail:
                raise __import__("requests").HTTPError("not an OAuth token")
        def json(self):
            return self.payload

    account_id, username = "675f37b072d14a2cff8b7343", "ada"

    oauth = iter([Response({"sub": account_id, "preferred_username": username, "orgs": []})])
    monkeypatch.setattr("apps.api.auth.requests.get", lambda *a, **k: next(oauth))
    via_oauth = IdentityProvider(mode="hf_token").resolve(
        "Bearer oauth-token", f"hf:user:{account_id}", "ignored")

    token = iter([Response(None, fail=True),
                  Response({"type": "user", "id": account_id, "name": username, "fullname": "Ada"})])
    monkeypatch.setattr("apps.api.auth.requests.get", lambda *a, **k: next(token))
    via_token = IdentityProvider(mode="hf_token").resolve(
        "Bearer hf-personal-token", f"hf:user:{account_id}", "ignored")

    assert via_oauth["workspace_id"] == via_token["workspace_id"] == f"hf:user:{account_id}"
    assert via_oauth["owner_user_id"] == via_token["owner_user_id"] == account_id


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
