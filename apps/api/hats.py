"""CAP-2: the hat registry -- what a hat adds, never what it takes away.

`browsingFaculty()` (services/journey-worker/node/src/faculty.js) does not change
and is not renamed: it is the floor every hat stands on, not one option among
several. A hat record here can only ever *add* to it -- there is no field in
which it could record a removal, the same way `facultyWith()` on the Node side
only ever appends tools and never builds a faculty from scratch. This module is
the persisted half of that: where a hat's `adds`/`roles`/`grants` live between
runs, so a run can be told "use hat X" without re-specifying what X means every
time.

Validating `adds` against what the worker's `FACULTY_REGISTRY` actually has
registered is not attempted here -- this is a different process in a different
language, and asking it live on every hat write would make this module a second
place a hat's real capabilities could drift from the worker's own list, which is
the exact failure CAP-2 exists to prevent structurally. A name this store has
never heard of is accepted; a run given it and no matching registration throws
at `facultyWith()` on the worker side instead, loudly, at the point that
actually matters.
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


class HatError(RuntimeError):
    """A hat record could not be stored or resolved."""


class HatRegistry:
    def __init__(self, database_url: str | None = None):
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/control-plane.db")
        if not url.startswith("sqlite:///"):
            raise ValueError("HatRegistry is the SQLite adapter")
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
                CREATE TABLE IF NOT EXISTS hats (
                  hat_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL DEFAULT 'local',
                  owner_user_id TEXT NOT NULL DEFAULT 'local',
                  label TEXT NOT NULL,
                  adds TEXT NOT NULL DEFAULT '[]',
                  roles TEXT NOT NULL DEFAULT '{}',
                  grants TEXT NOT NULL DEFAULT '{}',
                  profile_defaults TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS hats_workspace ON hats (workspace_id);
                """
            )

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _record(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "hat_id": row["hat_id"], "label": row["label"],
            # "adds": extra faculties only -- see the module docstring. Never a
            # "removes" or "replaces" key, because there is nothing here that
            # could express one.
            "adds": json.loads(row["adds"]),
            "roles": json.loads(row["roles"]),
            "grants": json.loads(row["grants"]),
            "profileDefaults": json.loads(row["profile_defaults"]),
            "createdAt": row["created_at"],
        }

    def put(self, *, workspace_id: str = "local", owner_user_id: str = "local", label: str,
            adds: list[str] | None = None, roles: dict[str, Any] | None = None,
            grants: dict[str, Any] | None = None, profile_defaults: dict[str, Any] | None = None
            ) -> dict[str, Any]:
        """Create a hat. `adds` is the whole point: a list of extra faculty names
        (resolved against the worker's own registry at run time, not here),
        appended to browsing rather than replacing any part of it."""
        if not str(label or "").strip():
            raise HatError("a hat needs a label so it can be chosen for a run")
        adds = list(adds or [])
        if not all(isinstance(name, str) and name.strip() for name in adds):
            raise HatError("adds must be a list of non-empty faculty names")
        hat_id = f"hat_{uuid4().hex}"
        with self.lock, self.connect() as db:
            db.execute(
                "INSERT INTO hats (hat_id,workspace_id,owner_user_id,label,adds,roles,grants,"
                "profile_defaults,created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (hat_id, workspace_id, owner_user_id, label.strip(), json.dumps(adds),
                 json.dumps(roles or {}), json.dumps(grants or {}), json.dumps(profile_defaults or {}),
                 self._now()))
            row = db.execute("SELECT * FROM hats WHERE hat_id=?", (hat_id,)).fetchone()
        return self._record(row)

    def get(self, hat_id: str, workspace_id: str = "local") -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM hats WHERE hat_id=? AND workspace_id=?",
                             (hat_id, workspace_id)).fetchone()
        return self._record(row) if row else None

    def list_hats(self, workspace_id: str = "local") -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM hats WHERE workspace_id=? ORDER BY created_at DESC",
                              (workspace_id,)).fetchall()
        return [self._record(row) for row in rows]

    def delete(self, hat_id: str, workspace_id: str = "local") -> bool:
        with self.lock, self.connect() as db:
            cursor = db.execute("DELETE FROM hats WHERE hat_id=? AND workspace_id=?",
                                (hat_id, workspace_id))
            return cursor.rowcount > 0
