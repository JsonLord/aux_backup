"""Workspace-scoped browser credentials for signed-in journey runs.

A run browses signed in when it is given a storage-state JSON (cookies and
localStorage), which journeytest-core forwards to agent-browser as `--state`.
That file is a bearer credential: anything holding it is logged in as the user
until the session expires. This module is the only place one is written down.

Three ways to supply one, in decreasing order of how much this service has to
guard:

  reference  Nothing secret is stored. The record holds the *name* of an
             environment variable -- a Hugging Face Space secret, say -- and the
             value is read at run time and never persisted. Prefer this.
  state      A storage-state JSON pasted in by hand, encrypted at rest.
  password   A username and password, encrypted at rest, for a login-capture
             flow to exchange for a state file. Stored only because some sites
             have no other way in.

Encryption fails closed. Without AUX_CREDENTIAL_KEY nothing secret is written at
all, rather than quietly landing in the database in plaintext -- a password store
that silently degrades is worse than one that refuses, because nobody finds out
until the database leaks.

Nothing here returns a stored secret to a caller. `list_credentials` returns
metadata only, and the secret leaves this module in exactly one direction: onto
disk as a state file for a run that is about to start.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

KIND_REFERENCE = "reference"
KIND_STATE = "state"
KIND_PASSWORD = "password"
KINDS = (KIND_REFERENCE, KIND_STATE, KIND_PASSWORD)

ENCRYPTION_KEY_ENV = "AUX_CREDENTIAL_KEY"


class CredentialError(RuntimeError):
    """A credential could not be stored or resolved. Never carries the secret."""


def generate_key() -> str:
    """A new key for AUX_CREDENTIAL_KEY. Set it as a Space secret, not in git."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


def _cipher():
    key = os.getenv(ENCRYPTION_KEY_ENV, "").strip()
    if not key:
        raise CredentialError(
            f"{ENCRYPTION_KEY_ENV} is not set, so credentials cannot be stored securely. "
            "Set it (see generate_key()) as a Space secret, or use a reference credential, "
            "which keeps the secret in the environment and stores only its name."
        )
    try:
        from cryptography.fernet import Fernet

        return Fernet(key.encode("ascii"))
    except Exception as error:  # noqa: BLE001 - the cause must not carry key material
        raise CredentialError(f"{ENCRYPTION_KEY_ENV} is not a valid key: {type(error).__name__}") from None


def encryption_available() -> bool:
    """Whether secrets can be stored right now -- for the UI to say so up front."""
    try:
        _cipher()
    except CredentialError:
        return False
    return True


class CredentialStore:
    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/control-plane.db")
        if not url.startswith("sqlite:///"):
            raise ValueError("CredentialStore is the SQLite adapter")
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
                CREATE TABLE IF NOT EXISTS browser_credentials (
                  credential_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'local',
                  owner_user_id TEXT NOT NULL DEFAULT 'local',
                  label TEXT NOT NULL,
                  origin TEXT NOT NULL DEFAULT '',
                  kind TEXT NOT NULL,
                  secret TEXT,
                  secret_ref TEXT,
                  username TEXT,
                  created_at TEXT NOT NULL,
                  last_used_at TEXT);
                CREATE INDEX IF NOT EXISTS browser_credentials_workspace
                  ON browser_credentials (workspace_id);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _metadata(row: sqlite3.Row) -> dict[str, Any]:
        """What a caller may see. Deliberately excludes `secret`."""
        return {
            "credential_id": row["credential_id"],
            "label": row["label"],
            "origin": row["origin"],
            "kind": row["kind"],
            "username": row["username"] or None,
            "secret_ref": row["secret_ref"] or None,
            "created_at": row["created_at"],
            "last_used_at": row["last_used_at"],
            # So a viewer can tell a reference whose variable has gone missing
            # from one that is ready, without reading the value.
            "resolvable": (
                bool(os.getenv(row["secret_ref"] or "", "").strip())
                if row["kind"] == KIND_REFERENCE else True
            ),
        }

    def put(self, *, workspace_id: str = "local", owner_user_id: str = "local",
            label: str, kind: str, origin: str = "", secret: str | None = None,
            secret_ref: str | None = None, username: str | None = None) -> dict[str, Any]:
        """Store a credential. Returns metadata only -- never the secret."""
        if kind not in KINDS:
            raise CredentialError(f"unknown credential kind '{kind}'; expected one of {', '.join(KINDS)}")
        if not str(label or "").strip():
            raise CredentialError("a credential needs a label so it can be chosen for a run")

        encrypted = None
        if kind == KIND_REFERENCE:
            if not str(secret_ref or "").strip():
                raise CredentialError("a reference credential needs the name of the environment variable holding it")
            secret_ref = secret_ref.strip()
        elif kind == KIND_STATE:
            if not str(secret or "").strip():
                raise CredentialError("a state credential needs the storage-state JSON")
            try:
                json.loads(secret)
            except (TypeError, ValueError):
                raise CredentialError("the storage state is not valid JSON") from None
            encrypted = _cipher().encrypt(secret.encode("utf-8")).decode("ascii")
        elif kind == KIND_PASSWORD:
            if not str(secret or "").strip():
                raise CredentialError("a password credential needs a password")
            encrypted = _cipher().encrypt(secret.encode("utf-8")).decode("ascii")

        credential_id = f"cred_{uuid4().hex}"
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO browser_credentials (credential_id,workspace_id,owner_user_id,label,"
                "origin,kind,secret,secret_ref,username,created_at,last_used_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                (credential_id, workspace_id, owner_user_id, label.strip(), (origin or "").strip(),
                 kind, encrypted, secret_ref, (username or "").strip() or None, self._now()),
            )
            row = db.execute("SELECT * FROM browser_credentials WHERE credential_id=?",
                             (credential_id,)).fetchone()
        return self._metadata(row)

    def list_credentials(self, workspace_id: str = "local") -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM browser_credentials WHERE workspace_id=? ORDER BY created_at DESC",
                (workspace_id,)).fetchall()
        return [self._metadata(row) for row in rows]

    def delete(self, credential_id: str, workspace_id: str = "local") -> bool:
        with self.lock, self.connect() as db:
            cursor = db.execute(
                "DELETE FROM browser_credentials WHERE credential_id=? AND workspace_id=?",
                (credential_id, workspace_id))
            return cursor.rowcount > 0

    def _row(self, credential_id: str, workspace_id: str) -> sqlite3.Row:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM browser_credentials WHERE credential_id=? AND workspace_id=?",
                (credential_id, workspace_id)).fetchone()
        if not row:
            raise CredentialError("credential not found in this workspace")
        return row

    def attach_state(self, credential_id: str, state: str, workspace_id: str = "local") -> dict[str, Any]:
        """Record a captured browser session against an existing credential.

        A password credential becomes usable at this point: from here on the run
        is handed the session, and the password is not needed again until it
        expires.
        """
        try:
            json.loads(state)
        except (TypeError, ValueError):
            raise CredentialError("the captured session is not valid JSON") from None
        row = self._row(credential_id, workspace_id)
        encrypted = _cipher().encrypt(state.encode("utf-8")).decode("ascii")
        with self.lock, self.connect() as db:
            db.execute("UPDATE browser_credentials SET secret=?, kind=? WHERE credential_id=?",
                       (encrypted, KIND_STATE, credential_id))
            updated = db.execute("SELECT * FROM browser_credentials WHERE credential_id=?",
                                 (credential_id,)).fetchone()
        # The username is kept: it says whose session this is, which matters when
        # a workspace holds several for the same site.
        _ = row
        return self._metadata(updated)

    def capture_session(self, credential_id: str, login_url: str, *, workspace_id: str = "local",
                        worker_url: str | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Sign in with a stored password and keep the resulting session.

        The password is decrypted here, sent once over loopback to the worker that
        owns the browser, and never returned to a caller -- so it stays inside
        this module and the service that has to type it.

        The call is held open for the whole sign-in, including any wait for a
        second factor, so the client timeout has to outlast the worker's own
        patience rather than cutting a half-finished login short.
        """
        from urllib import request as urlrequest

        row = self._row(credential_id, workspace_id)
        if row["kind"] != KIND_PASSWORD:
            raise CredentialError("only a password credential has anything to sign in with")
        if not str(login_url or "").strip():
            raise CredentialError("a capture needs the URL of the sign-in page")

        password = _cipher().decrypt(row["secret"].encode("ascii")).decode("utf-8")
        body = json.dumps({
            "url": login_url.strip(), "username": row["username"] or "", "password": password,
        }).encode("utf-8")
        base = (worker_url or os.getenv("JOURNEY_WORKER_URL", "http://127.0.0.1:8080")).rstrip("/")
        call = urlrequest.Request(f"{base}/v1/login-captures", data=body,
                                  headers={"content-type": "application/json"}, method="POST")
        # Default past the worker's own second-factor wait, with room to spare.
        wait = timeout if timeout is not None else float(os.getenv("AUX_LOGIN_CAPTURE_TIMEOUT", "300"))
        try:
            with urlrequest.urlopen(call, timeout=wait) as response:
                outcome = json.loads(response.read())
        except Exception as error:  # noqa: BLE001 - the cause must not carry the password
            raise CredentialError(f"the sign-in service could not be reached: {type(error).__name__}") from None
        finally:
            del password

        status = outcome.get("status")
        if status != "succeeded":
            # Surfaced verbatim: "answer the challenge" and "the password is
            # wrong" need different reactions from whoever is watching.
            raise CredentialError(outcome.get("detail") or f"sign-in did not complete ({status})")
        state = outcome.get("state")
        if not state:
            raise CredentialError("the sign-in reported success but returned no session")
        return self.attach_state(credential_id, state, workspace_id)

    def write_state_file(self, credential_id: str, directory: str | Path,
                         workspace_id: str = "local") -> str:
        """Materialise a run's storage state on disk and return its path.

        This is the one place a stored secret is decrypted, and it goes straight
        to a file the run is about to read. The file is created with owner-only
        permissions before anything is written to it, so it is never briefly
        world-readable.
        """
        row = self._row(credential_id, workspace_id)
        kind = row["kind"]
        if kind == KIND_PASSWORD:
            raise CredentialError(
                "a password credential has no browser session yet; capture one by signing in first")
        if kind == KIND_REFERENCE:
            state = os.getenv(row["secret_ref"] or "", "").strip()
            if not state:
                raise CredentialError(
                    f"environment variable '{row['secret_ref']}' is empty or unset in this deployment")
        else:
            state = _cipher().decrypt(row["secret"].encode("ascii")).decode("utf-8")

        try:
            json.loads(state)
        except (TypeError, ValueError):
            raise CredentialError("the resolved storage state is not valid JSON") from None

        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        path = target / f"{credential_id}.json"
        # Open with 0600 rather than writing and chmod-ing after: between those
        # two steps the session token would be readable by anyone on the box.
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(state)

        with self.lock, self.connect() as db:
            db.execute("UPDATE browser_credentials SET last_used_at=? WHERE credential_id=?",
                       (self._now(), credential_id))
        return str(path)
