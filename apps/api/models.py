"""Versioned API contracts shared by the first control-plane implementation."""
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    waiting_on_dependency = "waiting_on_dependency"
    succeeded = "succeeded"
    failed = "failed"
    cancel_requested = "cancel_requested"
    cancelled = "cancelled"


class SessionCreate(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    external_ref: dict[str, str] = Field(default_factory=dict)


class JobCreate(BaseModel):
    session_id: str
    type: str
    version: str = "1.0"
    pipeline_run_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    input_artifacts: list[str] = Field(default_factory=list)
    seed: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = None


class ArtifactCreate(BaseModel):
    session_id: str
    kind: str
    content_type: str = "application/json"
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    retention_class: Literal["raw", "structured"] = "structured"


class ArtifactPin(BaseModel):
    pinned: bool


class PresignedArtifactCreate(BaseModel):
    session_id: str
    kind: str
    content_type: str
    size: int = Field(gt=25 * 1024 * 1024, le=1024 * 1024 * 1024)
    metadata: dict[str, Any] = Field(default_factory=dict)
    retention_class: Literal["raw", "structured"] = "raw"
    multipart: bool = False


class MultipartPart(BaseModel):
    ETag: str
    PartNumber: int = Field(ge=1, le=10_000)


class MultipartComplete(BaseModel):
    upload_id: str | None = None
    parts: list[MultipartPart] = Field(default_factory=list)


class LegacyGitHubImport(BaseModel):
    repository: str
    branch: str
