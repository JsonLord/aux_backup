"""Hugging Face Space OAuth helpers for per-callback workspace identity."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RequestIdentity:
    authorization: str
    workspace_id: str
    user_id: str


def workspaces_from_profile(profile: dict[str, Any] | None) -> list[dict[str, str]]:
    if not profile or not profile.get("sub"):
        return []
    subject = str(profile["sub"])
    items = [{"id": f"hf:user:{subject}", "name": profile.get("name") or profile.get("preferred_username") or "Personal", "type": "personal", "role": "owner"}]
    for org in profile.get("orgs") or []:
        if not org.get("sub") or org.get("securityRestrictions"):
            continue
        items.append({"id": f"hf:org:{org['sub']}", "name": org.get("name") or org.get("preferred_username") or str(org["sub"]), "type": "organization", "role": org.get("roleInOrg") or "member"})
    return items


def request_identity(profile, token, workspace_id: str | None) -> RequestIdentity:
    if profile is None or token is None:
        raise PermissionError("Sign in with Hugging Face to continue")
    workspaces = workspaces_from_profile(dict(profile))
    allowed = {item["id"] for item in workspaces}
    selected = workspace_id or (workspaces[0]["id"] if workspaces else None)
    if selected not in allowed:
        raise PermissionError("Selected workspace is not present in the Hugging Face session")
    return RequestIdentity(f"Bearer {token.token}", selected, str(profile["sub"]))
