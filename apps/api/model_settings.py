"""Which model a workspace runs on, and who may use the built-in one.

This deployment ships with provider credentials in its environment -- a router
key and a Blablador key -- and every run has been spending them, whoever asked
for the run. That is fine for a demo persona and not fine for a stranger's
hundred-step journey against their own site.

So the built-in providers are reserved, and everyone else configures their own:

  1. **The example personas.** The bundled profiles exist to be tried, and a
     visitor who has to find an API key before seeing anything sees nothing.
  2. **The owner's own Hugging Face profile.** Whoever the Space belongs to,
     read from SPACE_ID rather than written down here, so a fork reserves its
     own owner's budget and not this one's.
  3. **The admin API token.** The break-glass path a script or CI job uses; it
     already authenticates as an administrator (apps/api/auth.py).

Anyone else brings a provider. The dialog takes one the same two ways the
browser-credential dialog takes a session: a Space secret name, which keeps the
value in the environment and stores only the name, or a pasted key, which is
encrypted at rest and refused outright when no encryption key is configured.

A model, an endpoint and a key are one setting, not three -- the failure that
cost five cycles was a fallback that carried the endpoint and not the model, so
a provider row here is all three or it is not a row.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from apps.api.credentials import CredentialError, _cipher, encryption_available

# How a provider's key is held: in the environment under a name we store, or
# encrypted in the database. Same two shapes, and same ordering of preference,
# as the browser-credential dialog.
KIND_REFERENCE = "reference"
KIND_SECRET = "secret"

# Which part of a run a provider serves. Separate because they have genuinely
# different needs: writing a person is a big infrequent job and wants a large
# model, while reflection happens on every step and wants a fast one.
ROLE_GENERATION = "generation"
ROLE_ACTING = "acting"
ROLE_REFLECTION = "reflection"
ROLE_VISION = "vision"
ROLES = (ROLE_GENERATION, ROLE_ACTING, ROLE_REFLECTION, ROLE_VISION)


class ModelSettingsError(RuntimeError):
    """Raised when a provider cannot be stored or a run may not use the defaults."""


def space_owner() -> str:
    """Whose Space this is, from the environment rather than written down here.

    A fork reserves its own owner's budget, not the budget of whoever happened to
    write this file.
    """
    space_id = os.getenv("SPACE_ID", "")
    return (os.getenv("SPACE_AUTHOR_NAME") or (space_id.split("/")[0] if "/" in space_id else "")).strip()


def default_provider_owners() -> set[str]:
    """Identities allowed to spend the built-in credentials.

    AUX_DEFAULT_PROVIDER_OWNERS overrides, as a comma-separated list of Hugging
    Face usernames or user ids, so a deployment can widen this to a team without
    editing code.
    """
    configured = os.getenv("AUX_DEFAULT_PROVIDER_OWNERS", "")
    owners = {item.strip() for item in configured.split(",") if item.strip()}
    owner = space_owner()
    if owner:
        owners.add(owner)
    return owners


def _identifiers(auth: dict[str, Any]) -> set[str]:
    """Every name this caller is known by, so an owner matches on either."""
    user = auth.get("user") or {}
    candidates = [auth.get("owner_user_id"), user.get("username"), user.get("id"), user.get("name")]
    return {str(item).strip() for item in candidates if item}


def may_use_built_in_providers(auth: dict[str, Any] | None, *, example_persona: str | None = None) -> bool:
    """Whether this caller may run on the credentials baked into the Space."""
    auth = auth or {}
    if auth.get("role") == "admin":
        return True
    if example_persona:
        return True
    return bool(_identifiers(auth) & default_provider_owners())


def why_not_built_in(auth: dict[str, Any] | None) -> str:
    """What to tell somebody who may not, in terms they can act on."""
    owner = space_owner() or "the Space owner"
    return (
        "This Space's own model credentials are reserved for its example personas, "
        f"for {owner}, and for the admin API token. Add a provider of your own in "
        "Settings -> Model providers -- a Hugging Face Space secret name is enough, "
        "and the value never leaves the environment."
    )


class ModelSettingsStore:
    """Per-workspace model providers. Same SQLite file as the credential store."""

    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/control-plane.db")
        if not url.startswith("sqlite:///"):
            raise ValueError("ModelSettingsStore is the SQLite adapter")
        self.path = Path(url.removeprefix("sqlite:///"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_providers (
                  provider_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'local',
                  owner_user_id TEXT NOT NULL DEFAULT 'local',
                  label TEXT NOT NULL,
                  role TEXT NOT NULL,
                  base_url TEXT NOT NULL,
                  model TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  secret TEXT,
                  secret_ref TEXT,
                  position INTEGER NOT NULL DEFAULT 0,
                  created_at TEXT NOT NULL,
                  last_used_at TEXT);
                CREATE INDEX IF NOT EXISTS model_providers_workspace
                  ON model_providers (workspace_id, role, position);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def save(self, *, workspace_id: str, owner_user_id: str, label: str, role: str,
             base_url: str, model: str, kind: str, secret: str = "", secret_ref: str = "",
             position: int = 0) -> dict[str, Any]:
        if role not in ROLES:
            raise ModelSettingsError(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
        base_url, model, label = base_url.strip().rstrip("/"), model.strip(), label.strip()
        # A model, an endpoint and a key are one setting. A row missing any of the
        # three is not a usable provider, and storing it would look like a
        # fallback while being a 401 or a 404 on every call.
        if not base_url or not model or not label:
            raise ModelSettingsError("a provider needs a name, an endpoint and a model")
        if kind == KIND_REFERENCE:
            if not secret_ref.strip():
                raise ModelSettingsError("name the Space secret that holds the key")
            stored_secret, stored_ref = None, secret_ref.strip()
        elif kind == KIND_SECRET:
            if not secret.strip():
                raise ModelSettingsError("paste the API key, or name a Space secret instead")
            if not encryption_available():
                raise CredentialError(
                    "AUX_CREDENTIAL_KEY is not set, so a pasted key cannot be stored securely. "
                    "Name a Space secret instead -- the value stays in the environment.")
            stored_secret, stored_ref = _cipher().encrypt(secret.strip().encode()).decode(), None
        else:
            raise ModelSettingsError(f"unknown provider kind {kind!r}")

        provider_id = f"llm_{uuid4().hex[:12]}"
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO model_providers (provider_id, workspace_id, owner_user_id, label, role,"
                " base_url, model, kind, secret, secret_ref, position, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (provider_id, workspace_id, owner_user_id, label, role, base_url, model, kind,
                 stored_secret, stored_ref, position, self._now()))
        return {"provider_id": provider_id, "label": label, "role": role,
                "base_url": base_url, "model": model, "kind": kind}

    def list(self, workspace_id: str, role: str | None = None) -> list[dict[str, Any]]:
        """Metadata only. A stored key is never returned by this method."""
        query = ("SELECT provider_id, label, role, base_url, model, kind, secret_ref, position,"
                 " created_at, last_used_at FROM model_providers WHERE workspace_id = ?")
        params: list[Any] = [workspace_id]
        if role:
            query, _ = query + " AND role = ?", params.append(role)
        with self.connect() as db:
            rows = db.execute(query + " ORDER BY role, position, created_at", params).fetchall()
        return [dict(row) for row in rows]

    def delete(self, provider_id: str, workspace_id: str) -> bool:
        with self.lock, self.connect() as db:
            changed = db.execute(
                "DELETE FROM model_providers WHERE provider_id = ? AND workspace_id = ?",
                (provider_id, workspace_id)).rowcount
        return bool(changed)

    def chain(self, workspace_id: str, role: str) -> list[tuple[str, str, str]]:
        """This workspace's providers for one role, as (base_url, api_key, model).

        The same shape services/persona_service/providers.py produces, so a
        configured workspace and a default one are walked by the same code and a
        fallback behaves identically either way.

        A row whose Space secret has since been removed from the environment is
        skipped rather than offered: an endpoint with no key looks like a fallback
        and is a 401 on every call.
        """
        with self.connect() as db:
            rows = db.execute(
                "SELECT base_url, model, kind, secret, secret_ref FROM model_providers"
                " WHERE workspace_id = ? AND role = ? ORDER BY position, created_at",
                (workspace_id, role)).fetchall()
        chain: list[tuple[str, str, str]] = []
        for row in rows:
            if row["kind"] == KIND_REFERENCE:
                key = os.getenv(row["secret_ref"] or "", "")
            else:
                try:
                    key = _cipher().decrypt((row["secret"] or "").encode()).decode()
                except (CredentialError, Exception):  # noqa: BLE001 - a bad row must not end a run
                    key = ""
            if key:
                chain.append((row["base_url"], key, row["model"]))
        return chain
