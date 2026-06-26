"""Per-user / per-session path layout for git-like session state.

Canonical layout (multi-tenant isolated under data/users/{user_id}/):

    blob/                         # content-addressable file objects (shared across sessions)
    trees/                        # content-addressable directory tree objects
    sessions/
      group_sessions_meta.json
      {session_id}/
        history.json              # runtime chat history (JSON)
        chat.md                   # exported chat for agents / checkpoints
        workspace/                # live working tree (like git checkout)
        state/
          HEAD.json
          chain.json
          commits/

Legacy layout is migrated lazily on first access.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.user_context import UserContext

logger = logging.getLogger(__name__)

LEGACY_HISTORY_PREFIX = "group_history_"
LEGACY_WORKSPACES_DIR = "workspaces"
LEGACY_SESSION_STATE_DIR = "session_state"


@dataclass(frozen=True)
class UserObjectStorePaths:
    """User-scoped CAS object store (blob + tree), shared by all sessions."""

    root: Path
    blobs: Path
    trees: Path

    @classmethod
    def from_user_ctx(cls, user_ctx: UserContext) -> UserObjectStorePaths:
        root = user_ctx.base_dir.resolve()
        blobs = root / "blob"
        trees = root / "trees"
        for path in (blobs, trees):
            path.mkdir(parents=True, exist_ok=True)
        return cls(root=root, blobs=blobs, trees=trees)


@dataclass(frozen=True)
class SessionLayoutPaths:
    """All on-disk paths for a single session."""

    session_id: str
    session_root: Path
    history: Path
    chat_md: Path
    workspace: Path
    state_root: Path
    commits: Path
    head: Path
    chain: Path

    @classmethod
    def from_user_ctx(cls, user_ctx: UserContext, session_id: str) -> SessionLayoutPaths:
        sid = (session_id or "").strip()
        session_root = (user_ctx.sessions_dir / sid).resolve()
        state_root = session_root / "state"
        return cls(
            session_id=sid,
            session_root=session_root,
            history=session_root / "history.json",
            chat_md=session_root / "chat.md",
            workspace=session_root / "workspace",
            state_root=state_root,
            commits=state_root / "commits",
            head=state_root / "HEAD.json",
            chain=state_root / "chain.json",
        )


def legacy_history_path(user_ctx: UserContext, session_id: str) -> Path:
    return user_ctx.sessions_dir / f"{LEGACY_HISTORY_PREFIX}{session_id}.json"


def legacy_workspace_path(user_ctx: UserContext, session_id: str) -> Path:
    return user_ctx.sessions_dir / LEGACY_WORKSPACES_DIR / session_id


def legacy_session_state_root(user_ctx: UserContext, session_id: str) -> Path:
    return user_ctx.base_dir / LEGACY_SESSION_STATE_DIR / "sessions" / session_id


def legacy_object_store(user_ctx: UserContext) -> UserObjectStorePaths:
    root = (user_ctx.base_dir / LEGACY_SESSION_STATE_DIR).resolve()
    return UserObjectStorePaths(
        root=root,
        blobs=root / "blobs",
        trees=root / "trees",
    )


def _move_path(src: Path, dest: Path) -> bool:
    if not src.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if dest.is_dir():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    shutil.move(str(src), str(dest))
    return True


def migrate_session_layout(user_ctx: UserContext, session_id: str) -> SessionLayoutPaths:
    """Move legacy scattered paths into sessions/{session_id}/ when needed."""
    layout = SessionLayoutPaths.from_user_ctx(user_ctx, session_id)
    layout.session_root.mkdir(parents=True, exist_ok=True)
    layout.state_root.mkdir(parents=True, exist_ok=True)
    layout.commits.mkdir(parents=True, exist_ok=True)

    _move_path(legacy_history_path(user_ctx, session_id), layout.history)

    legacy_ws = legacy_workspace_path(user_ctx, session_id)
    if legacy_ws.exists() and not layout.workspace.exists():
        _move_path(legacy_ws, layout.workspace)

    legacy_state = legacy_session_state_root(user_ctx, session_id)
    if legacy_state.exists():
        for name, dest in (
            ("chat.md", layout.chat_md),
            ("HEAD.json", layout.head),
            ("chain.json", layout.chain),
        ):
            _move_path(legacy_state / name, dest)
        legacy_commits = legacy_state / "commits"
        if legacy_commits.exists() and not any(layout.commits.iterdir()):
            _move_path(legacy_commits, layout.commits)

    # Migrate user-level object store: session_state/{blobs,trees} -> {blob,trees}
    store = UserObjectStorePaths.from_user_ctx(user_ctx)
    legacy = legacy_object_store(user_ctx)
    for legacy_dir, new_dir in ((legacy.blobs, store.blobs), (legacy.trees, store.trees)):
        if not legacy_dir.exists():
            continue
        new_dir.mkdir(parents=True, exist_ok=True)
        for child in legacy_dir.iterdir():
            target = new_dir / child.name
            if target.exists():
                continue
            try:
                shutil.move(str(child), str(target))
            except OSError:
                logger.warning("migrate object store item failed: %s -> %s", child, target, exc_info=True)

    return layout


def ensure_session_layout(user_ctx: UserContext, session_id: str) -> SessionLayoutPaths:
    layout = migrate_session_layout(user_ctx, session_id)
    layout.workspace.mkdir(parents=True, exist_ok=True)
    return layout


def resolve_history_path(user_ctx: UserContext, session_id: str) -> Path:
    layout = SessionLayoutPaths.from_user_ctx(user_ctx, session_id)
    if layout.history.exists():
        return layout.history
    legacy = legacy_history_path(user_ctx, session_id)
    if legacy.exists():
        return legacy
    return layout.history


def resolve_workspace_path(user_ctx: UserContext, session_id: str) -> Path:
    layout = SessionLayoutPaths.from_user_ctx(user_ctx, session_id)
    if layout.workspace.exists():
        return layout.workspace
    legacy = legacy_workspace_path(user_ctx, session_id)
    if legacy.exists():
        return legacy
    return layout.workspace
