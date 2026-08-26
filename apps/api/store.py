"""SQLite development system-of-record behind an intentionally small interface.

PostgreSQL is the production target. SQLite is explicitly permitted by the spec for
local development and makes the initial API persistent without pretending a queue or
database deployment already exists.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class Store:
    def __init__(self, database_url: str | None = None, artifact_root: str | None = None):
        url = database_url or os.getenv("DATABASE_URL", "sqlite:///data/control-plane.db")
        if not url.startswith("sqlite:///"):
            raise ValueError("PLACEHOLDER: only sqlite DATABASE_URL is implemented; PostgreSQL is next")
        self.path = Path(url.removeprefix("sqlite:///"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_root = Path(artifact_root or os.getenv("ARTIFACT_ROOT", "data/artifacts"))
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(self.path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                  session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                  metadata TEXT NOT NULL, external_ref TEXT NOT NULL,
                  workspace_id TEXT NOT NULL DEFAULT 'local', owner_user_id TEXT NOT NULL DEFAULT 'local');
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, pipeline_run_id TEXT,
                  type TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL,
                  depends_on TEXT NOT NULL, input_artifacts TEXT NOT NULL,
                  output_artifacts TEXT NOT NULL, created_at TEXT NOT NULL,
                  started_at TEXT, ended_at TEXT, attempt INTEGER NOT NULL, seed INTEGER,
                  metadata TEXT NOT NULL, error TEXT, idempotency_key TEXT UNIQUE,
                  workspace_id TEXT NOT NULL DEFAULT 'local', owner_user_id TEXT NOT NULL DEFAULT 'local');
                CREATE TABLE IF NOT EXISTS events (
                  job_id TEXT NOT NULL, sequence INTEGER NOT NULL, type TEXT NOT NULL,
                  timestamp TEXT NOT NULL, progress REAL, data TEXT NOT NULL,
                  PRIMARY KEY(job_id, sequence));
                CREATE TABLE IF NOT EXISTS artifacts (
                  artifact_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL,
                  content_type TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL,
                  metadata TEXT NOT NULL,
                  workspace_id TEXT NOT NULL DEFAULT 'local', owner_user_id TEXT NOT NULL DEFAULT 'local',
                  retention_class TEXT NOT NULL DEFAULT 'structured', pinned INTEGER NOT NULL DEFAULT 0,
                  expires_at TEXT);
                CREATE TABLE IF NOT EXISTS attempts (
                  job_id TEXT NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL,
                  started_at TEXT NOT NULL, ended_at TEXT, error TEXT,
                  PRIMARY KEY(job_id, attempt));
            """)
            self._ensure_column(db, "sessions", "workspace_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(db, "sessions", "owner_user_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(db, "jobs", "workspace_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(db, "jobs", "owner_user_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(db, "artifacts", "workspace_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(db, "artifacts", "owner_user_id", "TEXT NOT NULL DEFAULT 'local'")
            self._ensure_column(db, "artifacts", "retention_class", "TEXT NOT NULL DEFAULT 'structured'")
            self._ensure_column(db, "artifacts", "pinned", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(db, "artifacts", "expires_at", "TEXT")

    @staticmethod
    def _ensure_column(db, table, column, declaration):
        columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("metadata", "external_ref", "depends_on", "input_artifacts", "output_artifacts", "error", "data"):
            if key in result and result[key] is not None:
                result[key] = json.loads(result[key])
        if result.get("idempotency_key") and result.get("workspace_id"):
            result["idempotency_key"] = result["idempotency_key"].removeprefix(f"{result['workspace_id']}:")
        return result

    def create_session(self, payload, workspace_id="local", owner_user_id="local"):
        record = {"session_id": f"ses_{uuid4().hex}", "created_at": self.now(), **payload}
        record.update(workspace_id=workspace_id, owner_user_id=owner_user_id)
        with self.connect() as db:
            db.execute("INSERT INTO sessions (session_id,created_at,metadata,external_ref,workspace_id,owner_user_id) VALUES (?,?,?,?,?,?)", (record["session_id"], record["created_at"], json.dumps(record["metadata"]), json.dumps(record["external_ref"]), workspace_id, owner_user_id))
        return record

    def get_session(self, session_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())

    def create_job(self, payload):
        with self.lock:
            session = self.get_session(payload["session_id"])
            client_idempotency_key = payload.get("idempotency_key")
            if payload.get("idempotency_key"):
                payload = {**payload, "idempotency_key": f"{session['workspace_id']}:{payload['idempotency_key']}"}
            if payload.get("idempotency_key"):
                with self.connect() as db:
                    found = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (payload["idempotency_key"],)).fetchone()
                    if found:
                        return self.decode(found), False
            record = {"job_id": f"job_{uuid4().hex}", "status": "queued", "output_artifacts": [], "created_at": self.now(), "started_at": None, "ended_at": None, "attempt": 1, "error": None, **payload}
            record.update(workspace_id=session["workspace_id"], owner_user_id=session["owner_user_id"])
            with self.connect() as db:
                db.execute("INSERT INTO jobs (job_id,session_id,pipeline_run_id,type,version,status,depends_on,input_artifacts,output_artifacts,created_at,started_at,ended_at,attempt,seed,metadata,error,idempotency_key,workspace_id,owner_user_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    record["job_id"], record["session_id"], record.get("pipeline_run_id"), record["type"], record["version"], record["status"],
                    json.dumps(record["depends_on"]), json.dumps(record["input_artifacts"]), "[]", record["created_at"], None, None, 1,
                    record.get("seed"), json.dumps(record["metadata"]), None, record.get("idempotency_key"), record["workspace_id"], record["owner_user_id"],
                ))
            self.event(record["job_id"], "job.queued", 0, {})
            record["idempotency_key"] = client_idempotency_key
        return record, True

    def get_job(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def list_jobs(self, session_id):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM jobs WHERE session_id=? ORDER BY created_at", (session_id,))]

    def waiting_jobs(self, dependency_id):
        with self.connect() as db:
            rows = [self.decode(row) for row in db.execute("SELECT * FROM jobs WHERE status='waiting_on_dependency'")]
        return [row for row in rows if dependency_id in row["depends_on"]]

    def event(self, job_id, event_type, progress, data):
        with self.lock, self.connect() as db:
            sequence = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE job_id=?", (job_id,)).fetchone()[0]
            record = {"sequence": sequence, "job_id": job_id, "type": event_type, "timestamp": self.now(), "progress": progress, "data": data}
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (job_id, sequence, event_type, record["timestamp"], progress, json.dumps(data)))
            return record

    def events(self, job_id, after=0):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM events WHERE job_id=? AND sequence>? ORDER BY sequence", (job_id, after))]

    def update_job(self, job_id, status, **fields):
        allowed = {"started_at", "ended_at", "error", "attempt", "output_artifacts"}
        values = {"status": status, **{k: v for k, v in fields.items() if k in allowed}}
        assignments, params = [], []
        for key, value in values.items():
            assignments.append(f"{key}=?")
            params.append(json.dumps(value) if key in {"error", "output_artifacts"} and value is not None else value)
        with self.connect() as db:
            db.execute(f"UPDATE jobs SET {','.join(assignments)} WHERE job_id=?", (*params, job_id))

    def start_attempt(self, job_id, attempt):
        now = self.now()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO attempts VALUES (?,?,?,?,?,?)", (job_id, attempt, "running", now, None, None))
        self.update_job(job_id, "running", started_at=now, ended_at=None, error=None)

    def finish_attempt(self, job_id, attempt, status, error=None):
        now = self.now()
        with self.connect() as db:
            db.execute("UPDATE attempts SET status=?,ended_at=?,error=? WHERE job_id=? AND attempt=?", (status, now, json.dumps(error) if error else None, job_id, attempt))
        self.update_job(job_id, status, ended_at=now, error=error)

    def attempts(self, job_id):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM attempts WHERE job_id=? ORDER BY attempt", (job_id,))]

    def delete_session(self, session_id):
        with self.lock, self.connect() as db:
            artifact_paths = [Path(row[0]) for row in db.execute("SELECT path FROM artifacts WHERE session_id=?", (session_id,))]
            job_ids = [row[0] for row in db.execute("SELECT job_id FROM jobs WHERE session_id=?", (session_id,))]
            for job_id in job_ids:
                db.execute("DELETE FROM events WHERE job_id=?", (job_id,))
                db.execute("DELETE FROM attempts WHERE job_id=?", (job_id,))
            db.execute("DELETE FROM jobs WHERE session_id=?", (session_id,))
            db.execute("DELETE FROM artifacts WHERE session_id=?", (session_id,))
            deleted = db.execute("DELETE FROM sessions WHERE session_id=?", (session_id,)).rowcount
        for path in artifact_paths:
            path.unlink(missing_ok=True)
        return bool(deleted)

    def create_artifact(self, payload):
        artifact_id = f"art_{uuid4().hex}"
        session = self.get_session(payload["session_id"])
        workspace_id, owner_user_id = session["workspace_id"], session["owner_user_id"]
        path = self.artifact_root / workspace_id / payload["session_id"] / artifact_id
        path.parent.mkdir(parents=True, exist_ok=True)
        content = payload.pop("content")
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
        retention_class = payload.pop("retention_class", "structured")
        expires_at = (datetime.now(timezone.utc) + timedelta(days=30 if retention_class == "raw" else 180)).isoformat()
        record = {"artifact_id": artifact_id, "path": str(path), "created_at": self.now(), "workspace_id": workspace_id, "owner_user_id": owner_user_id, "retention_class": retention_class, "pinned": False, "expires_at": expires_at, **payload}
        with self.connect() as db:
            db.execute("INSERT INTO artifacts (artifact_id,session_id,kind,content_type,path,created_at,metadata,workspace_id,owner_user_id,retention_class,pinned,expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (artifact_id, record["session_id"], record["kind"], record["content_type"], str(path), record["created_at"], json.dumps(record["metadata"]), workspace_id, owner_user_id, record["retention_class"], 0, expires_at))
        return record

    def pin_artifact(self, artifact_id, pinned):
        with self.connect() as db:
            db.execute("UPDATE artifacts SET pinned=? WHERE artifact_id=?", (int(pinned), artifact_id))
        return self.get_artifact(artifact_id)

    def delete_expired_artifacts(self, now=None):
        now = now or self.now()
        with self.lock, self.connect() as db:
            rows = list(db.execute("SELECT artifact_id,path FROM artifacts WHERE pinned=0 AND expires_at IS NOT NULL AND expires_at<=?", (now,)))
            for artifact_id, _ in rows:
                db.execute("DELETE FROM artifacts WHERE artifact_id=?", (artifact_id,))
        for _, path in rows:
            Path(path).unlink(missing_ok=True)
        return len(rows)

    def get_artifact(self, artifact_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone())

    def list_artifacts(self, session_id):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM artifacts WHERE session_id=? ORDER BY created_at", (session_id,))]
