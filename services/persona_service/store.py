from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import Any


class PersonaStore(MutableMapping[str, dict[str, Any]]):
    """Small durable repository for versioned synthetic-user profiles.

    The mapping interface preserves the service's existing adapter boundary while
    making generated and manually edited profiles survive process restarts.
    """

    def __init__(self, database_path: str):
        self.database_path = database_path
        self._lock = threading.RLock()
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS personas (
                persona_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                workspace_id TEXT NOT NULL DEFAULT 'local',
                owner_user_id TEXT NOT NULL DEFAULT 'local',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(personas)")}
        if "workspace_id" not in columns:
            self._connection.execute("ALTER TABLE personas ADD COLUMN workspace_id TEXT NOT NULL DEFAULT 'local'")
        if "owner_user_id" not in columns:
            self._connection.execute("ALTER TABLE personas ADD COLUMN owner_user_id TEXT NOT NULL DEFAULT 'local'")
        self._connection.commit()

    def save(self, profile, workspace_id="local", owner_user_id="local"):
        if profile.get("id") is None: raise ValueError("profile id is required")
        payload = json.dumps(profile, separators=(",", ":"), sort_keys=True)
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO personas (persona_id,profile_json,workspace_id,owner_user_id)
                VALUES (?,?,?,?) ON CONFLICT(persona_id) DO UPDATE SET
                profile_json=excluded.profile_json, workspace_id=excluded.workspace_id,
                owner_user_id=excluded.owner_user_id, updated_at=CURRENT_TIMESTAMP""",
                (profile["id"], payload, workspace_id, owner_user_id),
            )
        return profile

    def get_for_workspace(self, persona_id, workspace_id="local"):
        with self._lock:
            row = self._connection.execute(
                "SELECT profile_json FROM personas WHERE persona_id=? AND workspace_id=?",
                (persona_id, workspace_id),
            ).fetchone()
        if row is None: raise KeyError(persona_id)
        return json.loads(row["profile_json"])

    def list_for_workspace(self, workspace_id="local", limit=50):
        with self._lock:
            rows = self._connection.execute(
                "SELECT profile_json FROM personas WHERE workspace_id=? ORDER BY rowid LIMIT ?",
                (workspace_id, limit),
            ).fetchall()
        return [json.loads(row["profile_json"]) for row in rows]

    def __getitem__(self, persona_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._connection.execute(
                "SELECT profile_json FROM personas WHERE persona_id = ?", (persona_id,)
            ).fetchone()
        if row is None:
            raise KeyError(persona_id)
        return json.loads(row["profile_json"])

    def __setitem__(self, persona_id: str, profile: dict[str, Any]) -> None:
        if profile.get("id") != persona_id:
            raise ValueError("profile id must match its storage key")
        self.save(profile)

    def __delitem__(self, persona_id: str) -> None:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM personas WHERE persona_id = ?", (persona_id,)
            )
        if cursor.rowcount == 0:
            raise KeyError(persona_id)

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT persona_id FROM personas ORDER BY rowid"
            ).fetchall()
        return iter(row["persona_id"] for row in rows)

    def __len__(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) AS count FROM personas").fetchone()
        return int(row["count"])

    def clear(self) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM personas")

    def close(self) -> None:
        with self._lock:
            self._connection.close()


class PostgresPersonaStore(MutableMapping[str, dict[str, Any]]):
    """Production persona repository using the shared PostgreSQL system of record."""

    def __init__(self, database_url: str):
        import psycopg
        from psycopg.rows import dict_row
        self.database_url = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        self._psycopg, self._row_factory = psycopg, dict_row

    def connect(self):
        from apps.api.tenant import current_workspace
        connection = self._psycopg.connect(self.database_url, row_factory=self._row_factory)
        workspace = current_workspace()
        if workspace:
            connection.execute("SELECT set_config('app.workspace_id', %s, false)", (workspace,))
        return connection

    def save(self, profile, workspace_id="local", owner_user_id="local"):
        if profile.get("id") is None: raise ValueError("profile id is required")
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO personas (persona_id,profile,workspace_id,owner_user_id,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (persona_id) DO UPDATE SET profile=EXCLUDED.profile,workspace_id=EXCLUDED.workspace_id,owner_user_id=EXCLUDED.owner_user_id,updated_at=EXCLUDED.updated_at", (profile["id"], self._psycopg.types.json.Jsonb(profile), workspace_id, owner_user_id, self._now(), self._now()))
        return profile

    def get_for_workspace(self, persona_id, workspace_id="local"):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT profile FROM personas WHERE persona_id=%s AND workspace_id=%s", (persona_id, workspace_id))
            row = cursor.fetchone()
        if row is None: raise KeyError(persona_id)
        return row["profile"]

    def list_for_workspace(self, workspace_id="local", limit=50):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT profile FROM personas WHERE workspace_id=%s ORDER BY created_at,persona_id LIMIT %s", (workspace_id, limit))
            return [row["profile"] for row in cursor.fetchall()]

    def __getitem__(self, persona_id):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT profile FROM personas WHERE persona_id=%s", (persona_id,))
            row = cursor.fetchone()
        if row is None: raise KeyError(persona_id)
        return row["profile"]

    def __setitem__(self, persona_id, profile):
        if profile.get("id") != persona_id: raise ValueError("profile id must match its storage key")
        self.save(profile)

    def __delitem__(self, persona_id):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("DELETE FROM personas WHERE persona_id=%s", (persona_id,))
            if cursor.rowcount == 0: raise KeyError(persona_id)

    def __iter__(self):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT persona_id FROM personas ORDER BY created_at,persona_id")
            ids = [row["persona_id"] for row in cursor.fetchall()]
        return iter(ids)

    def __len__(self):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM personas")
            return cursor.fetchone()["count"]

    def clear(self):
        with self.connect() as db, db.cursor() as cursor: cursor.execute("DELETE FROM personas")

    def close(self): pass

    def upsert_workspace_membership(self, workspace_id, user_id, role="member"):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO workspace_memberships (workspace_id,user_id,role,verified_at) VALUES (%s,%s,%s,%s) ON CONFLICT (workspace_id,user_id) DO UPDATE SET role=EXCLUDED.role,verified_at=EXCLUDED.verified_at", (workspace_id, user_id, role, self._now()))

    def sync_hf_identity(self, user, workspaces):
        now = self._now()
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO users (user_id,username,display_name,picture,last_verified_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (user_id) DO UPDATE SET username=EXCLUDED.username,display_name=EXCLUDED.display_name,picture=EXCLUDED.picture,last_verified_at=EXCLUDED.last_verified_at", (user["id"], user.get("username"), user.get("name"), user.get("picture"), now))
            cursor.execute("UPDATE workspace_memberships SET active=false WHERE user_id=%s AND source='hf'", (user["id"],))
            for workspace in workspaces:
                provider_ref = workspace["id"].split(":", 2)[-1]
                cursor.execute("INSERT INTO workspaces (workspace_id,workspace_type,name,provider_ref,updated_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (workspace_id) DO UPDATE SET name=EXCLUDED.name,updated_at=EXCLUDED.updated_at", (workspace["id"], workspace["type"], workspace["name"], provider_ref, now))
                cursor.execute("INSERT INTO workspace_memberships (workspace_id,user_id,role,verified_at,source,active) VALUES (%s,%s,%s,%s,'hf',true) ON CONFLICT (workspace_id,user_id) DO UPDATE SET role=EXCLUDED.role,verified_at=EXCLUDED.verified_at,source='hf',active=true", (workspace["id"], user["id"], workspace["role"], now))

    def verify_service_credential(self, credential_id, secret, workspace_id):
        import hashlib, hmac
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT secret_hash,salt,workspace_ids FROM service_credentials WHERE credential_id=%s AND revoked_at IS NULL", (credential_id,))
            row = cursor.fetchone()
        if not row or not workspace_id or workspace_id not in row["workspace_ids"]: return False
        digest = hashlib.scrypt(secret.encode(), salt=bytes(row["salt"]), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest, bytes(row["secret_hash"]))

    @staticmethod
    def _now():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc)


def persona_store_from_environment():
    import os
    url = os.getenv("PERSONA_DATABASE_URL") or os.getenv("DATABASE_URL")
    if url and url.startswith(("postgresql://", "postgresql+psycopg://")):
        return PostgresPersonaStore(url)
    return PersonaStore(os.getenv("PERSONA_DATABASE_PATH", "/tmp/aux-personas.db"))
