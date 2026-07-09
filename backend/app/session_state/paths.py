"""Per-session checkpoint path layout.

Canonical layout (multi-tenant isolated under data/users/{user_id}/):

    sessions/
      {session_id}/
        session.json              # session definition snapshot
        history.json              # runtime chat history (JSON)
        runtime.json              # live runtime mirror for UI recovery
        workspace/                # live working tree (like git checkout)
        checkpoints/
          HEAD.json
          chain.json
          snapshots/
          objects/
            blobs/
            trees/
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.user_context import UserContext

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class UserObjectStorePaths:
    """Session-scoped CAS object store (blob + tree)."""

    root: Path
    blobs: Path
    trees: Path

    @classmethod
    def from_session_layout(cls, layout: SessionLayoutPaths) -> UserObjectStorePaths:
        root = (layout.checkpoints_root / "objects").resolve()
        blobs = root / "blobs"
        trees = root / "trees"
        for path in (blobs, trees):
            path.mkdir(parents=True, exist_ok=True)
        return cls(root=root, blobs=blobs, trees=trees)


@dataclass(frozen=True)
class SessionLayoutPaths:
    """All on-disk paths for a single session."""

    session_id: str
    session_root: Path
    session_json: Path
    history: Path
    runtime_json: Path
    workspace: Path
    checkpoints_root: Path
    snapshots: Path
    head: Path
    chain: Path

    @classmethod
    def from_user_ctx(cls, user_ctx: UserContext, session_id: str) -> SessionLayoutPaths:
        sid = (session_id or "").strip()
        session_root = (user_ctx.sessions_dir / sid).resolve()
        checkpoints_root = session_root / "checkpoints"
        return cls(
            session_id=sid,
            session_root=session_root,
            session_json=session_root / "session.json",
            history=session_root / "history.json",
            runtime_json=session_root / "runtime.json",
            workspace=session_root / "workspace",
            checkpoints_root=checkpoints_root,
            snapshots=checkpoints_root / "snapshots",
            head=checkpoints_root / "HEAD.json",
            chain=checkpoints_root / "chain.json",
        )


def ensure_session_layout(user_ctx: UserContext, session_id: str) -> SessionLayoutPaths:
    """Ensure the strict per-session layout exists."""
    layout = SessionLayoutPaths.from_user_ctx(user_ctx, session_id)
    layout.session_root.mkdir(parents=True, exist_ok=True)
    layout.checkpoints_root.mkdir(parents=True, exist_ok=True)
    layout.snapshots.mkdir(parents=True, exist_ok=True)
    UserObjectStorePaths.from_session_layout(layout)
    layout.workspace.mkdir(parents=True, exist_ok=True)
    return layout


def resolve_history_path(user_ctx: UserContext, session_id: str) -> Path:
    layout = SessionLayoutPaths.from_user_ctx(user_ctx, session_id)
    return layout.history


def resolve_workspace_path(user_ctx: UserContext, session_id: str) -> Path:
    layout = SessionLayoutPaths.from_user_ctx(user_ctx, session_id)
    return layout.workspace
