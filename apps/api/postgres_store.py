"""Production PostgreSQL implementation of the control-plane Store contract."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
import hashlib
import hmac
import os


class PostgresStore:
    backend = "postgresql"

    def __init__(self, database_url: str, artifact_storage):
        import psycopg
        from psycopg.rows import dict_row
        self.database_url = database_url
        self.artifact_storage = artifact_storage
        self._psycopg = psycopg
        self._row_factory = dict_row

    def connect(self):
        return self._psycopg.connect(self.database_url, row_factory=self._row_factory)

    def ping(self):
        with self.connect() as db, db.cursor() as cursor: cursor.execute("SELECT 1")
        return True

    @staticmethod
    def now():
        return datetime.now(timezone.utc)

    @staticmethod
    def decode(row):
        if row is None:
            return None
        result = dict(row)
        for key, value in tuple(result.items()):
            if isinstance(value, datetime):
                result[key] = value.isoformat()
        return result

    def create_session(self, payload, workspace_id="local", owner_user_id="local"):
        record = {"session_id": f"ses_{uuid4().hex}", "created_at": self.now(), **payload,
                  "workspace_id": workspace_id, "owner_user_id": owner_user_id}
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO sessions (session_id,created_at,metadata,external_ref,workspace_id,owner_user_id) VALUES (%s,%s,%s::jsonb,%s::jsonb,%s,%s)",
                           (record["session_id"], record["created_at"], self._psycopg.types.json.Jsonb(record["metadata"]), self._psycopg.types.json.Jsonb(record["external_ref"]), workspace_id, owner_user_id))
        return self.decode(record)

    def get_session(self, session_id):
        return self._one("SELECT * FROM sessions WHERE session_id=%s", (session_id,))

    def list_sessions(self, workspace_id):
        return self._many("SELECT * FROM sessions WHERE workspace_id=%s ORDER BY created_at DESC", (workspace_id,))

    def create_job(self, payload):
        session = self.get_session(payload["session_id"])
        client_key = payload.get("idempotency_key")
        record = {"job_id": f"job_{uuid4().hex}", "status": "queued", "output_artifacts": [],
                  "created_at": self.now(), "started_at": None, "ended_at": None, "attempt": 1,
                  "error": None, **payload, "workspace_id": session["workspace_id"],
                  "owner_user_id": session["owner_user_id"]}
        columns = ("job_id,session_id,pipeline_run_id,type,version,status,depends_on,input_artifacts,"
                   "output_artifacts,created_at,started_at,ended_at,attempt,seed,metadata,error,"
                   "idempotency_key,workspace_id,owner_user_id")
        values = (record["job_id"], record["session_id"], record.get("pipeline_run_id"), record["type"],
                  record["version"], "queued", self._json(record["depends_on"]), self._json(record["input_artifacts"]),
                  self._json([]), record["created_at"], None, None, 1, record.get("seed"),
                  self._json(record["metadata"]), None, client_key, record["workspace_id"], record["owner_user_id"])
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute(f"INSERT INTO jobs ({columns}) VALUES ({','.join(['%s']*19)}) ON CONFLICT (workspace_id,idempotency_key) DO NOTHING RETURNING *", values)
            inserted = cursor.fetchone()
            if inserted is None:
                cursor.execute("SELECT * FROM jobs WHERE workspace_id=%s AND idempotency_key=%s", (record["workspace_id"], client_key))
                return self.decode(cursor.fetchone()), False
        created = self.decode(inserted)
        self.event(created["job_id"], "job.queued", 0, {})
        return created, True

    def claim_job(self, job_id):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("UPDATE jobs SET status='claimed' WHERE job_id=%s AND status='queued' RETURNING *", (job_id,))
            return self.decode(cursor.fetchone())

    def get_job(self, job_id): return self._one("SELECT * FROM jobs WHERE job_id=%s", (job_id,))
    def list_jobs(self, session_id): return self._many("SELECT * FROM jobs WHERE session_id=%s ORDER BY created_at", (session_id,))

    def waiting_jobs(self, dependency_id):
        return self._many("SELECT * FROM jobs WHERE status='waiting_on_dependency' AND depends_on ? %s", (dependency_id,))

    def event(self, job_id, event_type, progress, data):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (job_id,))
            cursor.execute("SELECT COALESCE(MAX(sequence),0)+1 AS sequence FROM events WHERE job_id=%s", (job_id,))
            sequence = cursor.fetchone()["sequence"]
            record = {"job_id": job_id, "sequence": sequence, "type": event_type, "timestamp": self.now(), "progress": progress, "data": data}
            cursor.execute("INSERT INTO events (job_id,sequence,type,timestamp,progress,data) VALUES (%s,%s,%s,%s,%s,%s)", (job_id, sequence, event_type, record["timestamp"], progress, self._json(data)))
        return self.decode(record)

    def events(self, job_id, after=0): return self._many("SELECT * FROM events WHERE job_id=%s AND sequence>%s ORDER BY sequence", (job_id, after))

    def update_job(self, job_id, status, **fields):
        allowed = {"started_at", "ended_at", "error", "attempt", "output_artifacts"}
        values = {"status": status, **{key: value for key, value in fields.items() if key in allowed}}
        assignments, params = [], []
        for key, value in values.items():
            assignments.append(f"{key}=%s")
            params.append(self._json(value) if key in {"error", "output_artifacts"} and value is not None else value)
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute(f"UPDATE jobs SET {','.join(assignments)} WHERE job_id=%s", (*params, job_id))

    def start_attempt(self, job_id, attempt):
        now = self.now()
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO attempts (job_id,attempt,status,started_at) VALUES (%s,%s,'running',%s) ON CONFLICT (job_id,attempt) DO UPDATE SET status='running',started_at=EXCLUDED.started_at,ended_at=NULL,error=NULL", (job_id, attempt, now))
        self.update_job(job_id, "running", started_at=now, ended_at=None, error=None)

    def finish_attempt(self, job_id, attempt, status, error=None):
        now = self.now()
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("UPDATE attempts SET status=%s,ended_at=%s,error=%s WHERE job_id=%s AND attempt=%s", (status, now, self._json(error) if error else None, job_id, attempt))
        self.update_job(job_id, status, ended_at=now, error=error)

    def attempts(self, job_id): return self._many("SELECT * FROM attempts WHERE job_id=%s ORDER BY attempt", (job_id,))

    def delete_session(self, session_id):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT path FROM artifacts WHERE session_id=%s FOR UPDATE", (session_id,))
            artifacts = cursor.fetchall()
            for artifact in artifacts: self.artifact_storage.delete(artifact["path"])
            cursor.execute("DELETE FROM sessions WHERE session_id=%s", (session_id,))
            deleted = cursor.rowcount
        return bool(deleted)

    def create_artifact(self, payload):
        artifact_id = f"art_{uuid4().hex}"
        session = self.get_session(payload["session_id"])
        key = f'{session["workspace_id"]}/{payload["session_id"]}/{artifact_id}'
        content = payload.pop("content")
        self.artifact_storage.put(key, content, payload["content_type"])
        retention = payload.pop("retention_class", "structured")
        expires = self.now() + timedelta(days=30 if retention == "raw" else 180)
        record = {"artifact_id": artifact_id, "path": key, "created_at": self.now(), "workspace_id": session["workspace_id"], "owner_user_id": session["owner_user_id"], "retention_class": retention, "pinned": False, "expires_at": expires, **payload}
        try:
            with self.connect() as db, db.cursor() as cursor:
                cursor.execute("INSERT INTO artifacts (artifact_id,session_id,kind,content_type,path,created_at,metadata,workspace_id,owner_user_id,retention_class,pinned,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s)", (artifact_id, record["session_id"], record["kind"], record["content_type"], key, record["created_at"], self._json(record["metadata"]), record["workspace_id"], record["owner_user_id"], retention, expires))
        except Exception:
            self.artifact_storage.delete(key)
            raise
        return self.decode(record)

    def reserve_artifact(self, payload):
        artifact_id = f"art_{uuid4().hex}"
        session = self.get_session(payload["session_id"])
        key = f'{session["workspace_id"]}/{payload["session_id"]}/{artifact_id}'
        retention = payload.get("retention_class", "raw")
        expires = self.now() + timedelta(days=30 if retention == "raw" else 180)
        metadata = {**payload.get("metadata", {}), "upload_status": "pending", "expected_size": payload["size"]}
        record = {"artifact_id": artifact_id, "session_id": payload["session_id"], "kind": payload["kind"], "content_type": payload["content_type"], "path": key, "created_at": self.now(), "metadata": metadata, "workspace_id": session["workspace_id"], "owner_user_id": session["owner_user_id"], "retention_class": retention, "pinned": False, "expires_at": expires}
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO artifacts (artifact_id,session_id,kind,content_type,path,created_at,metadata,workspace_id,owner_user_id,retention_class,pinned,expires_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s)", (artifact_id, record["session_id"], record["kind"], record["content_type"], key, record["created_at"], self._json(metadata), record["workspace_id"], record["owner_user_id"], retention, expires))
        return self.decode(record)

    def complete_artifact_upload(self, artifact_id):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("UPDATE artifacts SET metadata=jsonb_set(metadata,'{upload_status}',to_jsonb('complete'::text)) WHERE artifact_id=%s RETURNING *", (artifact_id,))
            return self.decode(cursor.fetchone())

    def pin_artifact(self, artifact_id, pinned):
        with self.connect() as db, db.cursor() as cursor: cursor.execute("UPDATE artifacts SET pinned=%s WHERE artifact_id=%s", (pinned, artifact_id))
        return self.get_artifact(artifact_id)

    def delete_expired_artifacts(self, now=None):
        now = now or self.now()
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("SELECT artifact_id,path FROM artifacts WHERE pinned=false AND expires_at<=%s FOR UPDATE SKIP LOCKED", (now,))
            rows = cursor.fetchall()
            for row in rows: self.artifact_storage.delete(row["path"])
            if rows: cursor.execute("DELETE FROM artifacts WHERE artifact_id=ANY(%s)", ([row["artifact_id"] for row in rows],))
        return len(rows)

    def get_artifact(self, artifact_id): return self._one("SELECT * FROM artifacts WHERE artifact_id=%s", (artifact_id,))
    def read_artifact(self, artifact_id):
        artifact = self.get_artifact(artifact_id)
        if artifact is None: raise KeyError(artifact_id)
        return self.artifact_storage.get(artifact["path"])
    def list_artifacts(self, session_id): return self._many("SELECT * FROM artifacts WHERE session_id=%s ORDER BY created_at", (session_id,))

    def upsert_workspace_membership(self, workspace_id, user_id, role="member"):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO workspace_memberships (workspace_id,user_id,role,verified_at) VALUES (%s,%s,%s,%s) ON CONFLICT (workspace_id,user_id) DO UPDATE SET role=EXCLUDED.role,verified_at=EXCLUDED.verified_at", (workspace_id, user_id, role, self.now()))

    def workspace_member(self, workspace_id, user_id):
        return self._one("SELECT * FROM workspace_memberships WHERE workspace_id=%s AND user_id=%s", (workspace_id, user_id))

    def create_service_credential(self, name, workspace_ids):
        credential_id, secret, salt = f"svc_{uuid4().hex}", os.urandom(32).hex(), os.urandom(16)
        digest = hashlib.scrypt(secret.encode(), salt=salt, n=2**14, r=8, p=1)
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute("INSERT INTO service_credentials (credential_id,name,secret_hash,salt,workspace_ids,created_at) VALUES (%s,%s,%s,%s,%s,%s)", (credential_id, name, digest, salt, workspace_ids, self.now()))
        return {"credential_id": credential_id, "secret": secret}

    def verify_service_credential(self, credential_id, secret, workspace_id):
        record = self._one("SELECT * FROM service_credentials WHERE credential_id=%s AND revoked_at IS NULL", (credential_id,))
        if not record or not workspace_id or workspace_id not in record["workspace_ids"]: return False
        digest = hashlib.scrypt(secret.encode(), salt=bytes(record["salt"]), n=2**14, r=8, p=1)
        return hmac.compare_digest(digest, bytes(record["secret_hash"]))

    def _json(self, value): return self._psycopg.types.json.Jsonb(value)
    def _one(self, sql, params):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute(sql, params); return self.decode(cursor.fetchone())
    def _many(self, sql, params):
        with self.connect() as db, db.cursor() as cursor:
            cursor.execute(sql, params); return [self.decode(row) for row in cursor.fetchall()]
