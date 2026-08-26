"""Per-request PostgreSQL tenant context used by row-level security policies."""
from contextvars import ContextVar

_workspace = ContextVar("workspace_id", default="")


def set_workspace(workspace_id: str) -> None:
    _workspace.set(workspace_id)


def current_workspace() -> str:
    return _workspace.get()
