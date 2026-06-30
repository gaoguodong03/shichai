"""Session workspace layout policy for user-level sandboxes."""
from __future__ import annotations

from pathlib import Path

_SANDBOX_SESSIONS_ROOT = "/workspace"


def sandbox_sessions_root() -> str:
    return _SANDBOX_SESSIONS_ROOT


def sandbox_session_dir(session_id: str) -> str:
    sid = (session_id or "").strip().strip("/")
    if not sid:
        sid = "session"
    return f"{_SANDBOX_SESSIONS_ROOT}/{sid}"


def host_sessions_root_from_workspace(workspace_path: Path) -> Path:
    """Infer host sessions directory from a session workspace path."""
    wp = workspace_path.resolve()
    if wp.name == "workspace" and wp.parent.name.startswith("group-"):
        return wp.parent.parent
    if wp.parent.name == "workspaces":
        return wp.parent.parent
    return wp.parent


def host_session_dir(host_workspace_or_sessions_root: Path, session_id: str) -> Path:
    root = host_workspace_or_sessions_root.resolve()
    if root.name == "workspaces":
        return (root / session_id).resolve()
    session_root = (root / session_id).resolve()
    workspace = session_root / "workspace"
    if workspace.exists() or not (root / "workspaces" / session_id).exists():
        return workspace
    return (root / "workspaces" / session_id).resolve()
