from __future__ import annotations

import os
from typing import Any

from fastapi import Header, HTTPException


class IdentityProvider:
    """HF OIDC identity and workspace-membership verification boundary."""

    def __init__(self, mode: str | None = None, membership_store=None):
        self.mode = mode or os.getenv("AUTH_MODE", "local")
        self.issuer = os.getenv("HF_OIDC_ISSUER", "https://huggingface.co")
        self.audience = os.getenv("HF_OIDC_AUDIENCE")
        self.jwks_url = os.getenv("HF_OIDC_JWKS_URL")
        self.membership_store = membership_store

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

    def __call__(
        self,
        authorization: str | None = Header(None),
        workspace: str | None = Header(None, alias="X-Workspace-ID"),
        local_user: str = Header("local", alias="X-User-ID"),
    ) -> dict[str, str]:
        if self.mode == "local":
            return {"workspace_id": workspace or "local", "owner_user_id": local_user}
        if authorization and authorization.startswith("Service "):
            if not self.membership_store:
                raise HTTPException(503, "service credential store is unavailable")
            credential_id, separator, secret = authorization[8:].partition(".")
            if not separator or not self.membership_store.verify_service_credential(credential_id, secret, workspace):
                raise HTTPException(401, "invalid service credential")
            return {"workspace_id": workspace, "owner_user_id": f"service:{credential_id}"}
        claims = self._claims(authorization)
        subject = str(claims["sub"])
        organizations = claims.get("orgs", claims.get("organizations", []))
        memberships = {str(item.get("name", item.get("id"))) if isinstance(item, dict) else str(item) for item in organizations}
        requested = workspace or subject
        if requested != subject and requested not in memberships:
            raise HTTPException(403, "workspace membership not present in verified token")
        if self.membership_store:
            self.membership_store.upsert_workspace_membership(subject, subject, "owner")
            for item in organizations:
                name = str(item.get("name", item.get("id"))) if isinstance(item, dict) else str(item)
                role = str(item.get("role", "member")) if isinstance(item, dict) else "member"
                self.membership_store.upsert_workspace_membership(name, subject, role)
        return {"workspace_id": requested, "owner_user_id": subject}
