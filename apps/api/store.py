"""SQLite development system-of-record behind an intentionally small interface.

PostgreSQL is the production target. SQLite is explicitly permitted by the spec for
local development and makes the initial API persistent without pretending a queue or
database deployment already exists.
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
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
                  metadata TEXT NOT NULL, external_ref TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs (
                  job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, pipeline_run_id TEXT,
                  type TEXT NOT NULL, version TEXT NOT NULL, status TEXT NOT NULL,
                  depends_on TEXT NOT NULL, input_artifacts TEXT NOT NULL,
                  output_artifacts TEXT NOT NULL, created_at TEXT NOT NULL,
                  started_at TEXT, ended_at TEXT, attempt INTEGER NOT NULL, seed INTEGER,
                  metadata TEXT NOT NULL, error TEXT, idempotency_key TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS events (
                  job_id TEXT NOT NULL, sequence INTEGER NOT NULL, type TEXT NOT NULL,
                  timestamp TEXT NOT NULL, progress REAL, data TEXT NOT NULL,
                  PRIMARY KEY(job_id, sequence));
                CREATE TABLE IF NOT EXISTS artifacts (
                  artifact_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, kind TEXT NOT NULL,
                  content_type TEXT NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL,
                  metadata TEXT NOT NULL);
            """)

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
        return result

    def create_session(self, payload):
        record = {"session_id": f"ses_{uuid4().hex}", "created_at": self.now(), **payload}
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (record["session_id"], record["created_at"], json.dumps(record["metadata"]), json.dumps(record["external_ref"])))
        return record

    def get_session(self, session_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone())

    def create_job(self, payload):
        if payload.get("idempotency_key"):
            with self.connect() as db:
                found = db.execute("SELECT * FROM jobs WHERE idempotency_key=?", (payload["idempotency_key"],)).fetchone()
                if found:
                    return self.decode(found), False
        record = {"job_id": f"job_{uuid4().hex}", "status": "queued", "output_artifacts": [], "created_at": self.now(), "started_at": None, "ended_at": None, "attempt": 1, "error": None, **payload}
        with self.connect() as db:
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                record["job_id"], record["session_id"], record.get("pipeline_run_id"), record["type"], record["version"], record["status"],
                json.dumps(record["depends_on"]), json.dumps(record["input_artifacts"]), "[]", record["created_at"], None, None, 1,
                record.get("seed"), json.dumps(record["metadata"]), None, record.get("idempotency_key"),
            ))
        self.event(record["job_id"], "job.queued", 0, {})
        return record, True

    def get_job(self, job_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def list_jobs(self, session_id):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM jobs WHERE session_id=? ORDER BY created_at", (session_id,))]

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
        allowed = {"started_at", "ended_at", "error", "attempt"}
        values = {"status": status, **{k: v for k, v in fields.items() if k in allowed}}
        assignments, params = [], []
        for key, value in values.items():
            assignments.append(f"{key}=?")
            params.append(json.dumps(value) if key == "error" and value is not None else value)
        with self.connect() as db:
            db.execute(f"UPDATE jobs SET {','.join(assignments)} WHERE job_id=?", (*params, job_id))

    def create_artifact(self, payload):
        artifact_id = f"art_{uuid4().hex}"
        path = self.artifact_root / artifact_id
        content = payload.pop("content")
        if isinstance(content, (dict, list)):
            path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        else:
            path.write_text(str(content), encoding="utf-8")
        record = {"artifact_id": artifact_id, "path": str(path), "created_at": self.now(), **payload}
        with self.connect() as db:
            db.execute("INSERT INTO artifacts VALUES (?,?,?,?,?,?,?)", (artifact_id, record["session_id"], record["kind"], record["content_type"], str(path), record["created_at"], json.dumps(record["metadata"])))
        return record

    def get_artifact(self, artifact_id):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM artifacts WHERE artifact_id=?", (artifact_id,)).fetchone())

    def list_artifacts(self, session_id):
        with self.connect() as db:
            return [self.decode(row) for row in db.execute("SELECT * FROM artifacts WHERE session_id=? ORDER BY created_at", (session_id,))]
