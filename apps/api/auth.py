from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Header, HTTPException
from starlette.concurrency import run_in_threadpool
import requests

from .tenant import set_workspace


class IdentityProvider:
    """HF OIDC identity and workspace-membership verification boundary."""

    def __init__(self, mode: str | None = None, membership_store=None):
        self.mode = mode or os.getenv("AUTH_MODE", "local")
        self.issuer = os.getenv("HF_OIDC_ISSUER", "https://huggingface.co")
        self.audience = os.getenv("HF_OIDC_AUDIENCE")
        self.jwks_url = os.getenv("HF_OIDC_JWKS_URL")
        self.userinfo_url = os.getenv("HF_OIDC_USERINFO_URL", "https://huggingface.co/oauth/userinfo")
        self.whoami_url = os.getenv("HF_TOKEN_USERINFO_URL", "https://huggingface.co/api/whoami-v2")
        self.membership_store = membership_store
        # Operator break-glass credential. When ``ADMIN_API_TOKEN`` is configured
        # (Hugging Face Space secret), a request presenting ``Authorization: Admin
        # <token>`` is authenticated as an administrator without Hugging Face OAuth.
        # This lets maintainers exercise the app and API before sign-in works.
        self.admin_token = os.getenv("ADMIN_API_TOKEN") or None
        self.admin_workspace = os.getenv("ADMIN_WORKSPACE_ID", "admin")

    def _is_admin_authorization(self, authorization: str | None) -> bool:
        if not self.admin_token or not authorization:
            return False
        scheme, _, token = authorization.partition(" ")
        if scheme != "Admin" or not token:
            return False
        return hmac.compare_digest(token, self.admin_token)

    def _admin_identity(self, workspace: str | None) -> dict[str, Any]:
        requested = workspace or self.admin_workspace
        user = {"id": "admin", "username": "admin", "name": "Administrator", "picture": None}
        workspaces = [{"id": requested, "name": "Administrator", "type": "admin", "role": "admin"}]
        return {"workspace_id": requested, "owner_user_id": "admin", "role": "admin",
                "user": user, "workspaces": workspaces}

    @staticmethod
    def personal_workspace(subject: str) -> str:
        return f"hf:user:{subject}"

    @staticmethod
    def organization_workspace(subject: str) -> str:
        return f"hf:org:{subject}"

    def _hf_userinfo(self, authorization: str | None) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Hugging Face user access token required")
        try:
            response = requests.get(self.userinfo_url, headers={"Authorization": authorization}, timeout=15)
            try:
                response.raise_for_status()
                result = response.json()
                if not result.get("sub"):
                    raise ValueError("userinfo response has no subject")
                return result
            except requests.RequestException:
                pass
            # HF personal access tokens are intentionally not OAuth tokens, but are
            # valid user credentials for versioned API clients. Restrict this
            # fallback to the verified personal workspace; organization membership
            # continues to require the richer OAuth claims above.
            fallback = requests.get(self.whoami_url, headers={"Authorization": authorization}, timeout=15)
            fallback.raise_for_status()
            account = fallback.json()
            if account.get("type") != "user" or not account.get("name"):
                raise ValueError("whoami response has no user identity")
            # The subject must be the account's stable id, which is exactly what the
            # OAuth userinfo path above returns as `sub` -- not the username. Using
            # the username put the same person in two different workspaces depending
            # on which credential they presented: a session created with a personal
            # access token landed in "hf:user:<username>" while the browser, signed
            # in through OAuth, asked for "hf:user:<id>" and got 404 for every one of
            # them.
            if not account.get("id"):
                raise ValueError("whoami response has no account id")
            return {"sub": str(account["id"]), "preferred_username": account["name"],
                    "name": account.get("fullname") or account["name"], "orgs": []}
        except (requests.RequestException, ValueError) as error:
            raise HTTPException(401, "invalid Hugging Face user access token") from error

    def _claims(self, authorization: str | None) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Bearer token required")
        if not self.audience:
            raise HTTPException(503, "HF_OIDC_AUDIENCE is not configured")
        if not self.jwks_url:
            raise HTTPException(503, "HF_OIDC_JWKS_URL is not configured")
        try:
            import jwt

            key = jwt.PyJWKClient(self.jwks_url).get_signing_key_from_jwt(authorization[7:])
            return jwt.decode(
                authorization[7:], key.key, algorithms=["RS256"], audience=self.audience,
                issuer=self.issuer, options={"require": ["exp", "iat", "sub"]},
            )
        except HTTPException:
            raise
        except Exception as error:
            raise HTTPException(401, "invalid HF OIDC token") from error

    async def __call__(
        self,
        authorization: str | None = Header(None),
        workspace: str | None = Header(None, alias="X-Workspace-ID"),
        local_user: str = Header("local", alias="X-User-ID"),
    ) -> dict[str, Any]:
        result = await run_in_threadpool(self.resolve, authorization, workspace, local_user)
        set_workspace(result["workspace_id"])
        return result

    def resolve(self, authorization: str | None, workspace: str | None, local_user: str) -> dict[str, Any]:
        # Administrator break-glass takes precedence in every mode so operators can
        # reach the app and API before Hugging Face sign-in is available.
        if self._is_admin_authorization(authorization):
            return self._admin_identity(workspace)
        if self.mode == "local":
            selected = workspace or "local"
            return {"workspace_id": selected, "owner_user_id": local_user}
        if authorization and authorization.startswith("Service "):
            if not self.membership_store:
                raise HTTPException(503, "service credential store is unavailable")
            credential_id, separator, secret = authorization[8:].partition(".")
            if not separator or not self.membership_store.verify_service_credential(credential_id, secret, workspace):
                raise HTTPException(401, "invalid service credential")
            return {"workspace_id": workspace, "owner_user_id": f"service:{credential_id}", "role": "service"}
        claims = self._hf_userinfo(authorization) if self.mode == "hf_token" else self._claims(authorization)
        subject = str(claims["sub"])
        organizations = claims.get("orgs", claims.get("organizations", []))
        personal_workspace = self.personal_workspace(subject)
        available = [{"id": personal_workspace, "name": claims.get("name") or claims.get("preferred_username") or "Personal", "type": "personal", "role": "owner"}]
        for item in organizations:
            if not isinstance(item, dict) or not item.get("sub") or item.get("securityRestrictions"):
                continue
            available.append({"id": self.organization_workspace(str(item["sub"])), "name": item.get("name") or item.get("preferred_username") or str(item["sub"]), "type": "organization", "role": item.get("roleInOrg", item.get("role", "member"))})
        memberships = {item["id"] for item in available}
        requested = workspace or personal_workspace
        if requested not in memberships:
            raise HTTPException(403, "workspace membership not present in verified token")
        user = {"id": subject, "username": claims.get("preferred_username"), "name": claims.get("name"), "picture": claims.get("picture")}
        if self.membership_store and hasattr(self.membership_store, "sync_hf_identity"):
            self.membership_store.sync_hf_identity(user, available)
        elif self.membership_store:
            for item in available:
                self.membership_store.upsert_workspace_membership(item["id"], subject, item["role"])
        selected = next(item for item in available if item["id"] == requested)
        return {"workspace_id": requested, "owner_user_id": subject, "role": selected["role"], "user": user, "workspaces": available}
