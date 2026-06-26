from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException

from app.api.group_chat_state import (
    load_group_history,
    load_group_meta,
    save_group_history,
    save_group_meta,
)
from app.core.security import get_current_user
from app.core.user_context import UserContext

from .markdown import format_session_chat_markdown as _build_session_chat_markdown, parse_session_chat_markdown
from .paths import SessionLayoutPaths, ensure_session_layout
from .store import user_object_store
from .store import (
    blob_path,
    load_chain,
    load_head,
    prune_commits,
    read_blob,
    read_commit,
    read_tree,
    save_chain,
    save_head,
    write_blob,
    write_commit,
    write_tree,
)

_AUTO_CHECKPOINT_SUPPRESSED: ContextVar[bool] = ContextVar("session_state_auto_checkpoint_suppressed", default=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_user_ctx() -> UserContext:
    return get_current_user().ctx


def _session_layout(session_id: str) -> SessionLayoutPaths:
    return ensure_session_layout(_current_user_ctx(), session_id)


def _object_store() -> Any:
    return user_object_store(_current_user_ctx())


def _workspace_root(session_id: str) -> Path:
    layout = _session_layout(session_id)
    layout.workspace.mkdir(parents=True, exist_ok=True)
    return layout.workspace


def _session_meta_snapshot(session_id: str) -> Dict[str, Any]:
    meta = load_group_meta()
    item = meta.get(session_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Group session not found")
    snapshot = copy.deepcopy(item)
    for key in (
        "runtime_state",
        "pending_owner_agent_id",
        "pending_skill_id",
        "pending_phase",
        "pending_required_user_fields",
        "pending_handoff_reason",
    ):
        snapshot.pop(key, None)
    return snapshot


def _canonical_state_hash(meta_snapshot: Dict[str, Any], tree_hash: str, chat_hash: str) -> str:
    payload = {
        "meta": meta_snapshot,
        "tree": tree_hash,
        "chat": chat_hash,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _materialize_blob(store, blob_hash: str, dest: Path) -> None:
    """Write blob bytes to workspace; hardlink when possible for storage reuse."""
    src = blob_path(store, blob_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        dest.write_bytes(read_blob(store, blob_hash))


def _store_workspace_tree(store, workspace_root: Path) -> str:
    def _build_tree(path: Path) -> Dict[str, Any]:
        entries: List[Dict[str, Any]] = []
        if path.exists() and path.is_dir():
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if child.is_dir():
                    subtree = _build_tree(child)
                    subtree_hash = write_tree(store, subtree)
                    entries.append(
                        {
                            "name": child.name,
                            "kind": "tree",
                            "hash": subtree_hash,
                            "mode": "040000",
                        }
                    )
                    continue
                if not child.is_file():
                    continue
                data = child.read_bytes()
                blob_hash = write_blob(store, data)
                entries.append(
                    {
                        "name": child.name,
                        "kind": "blob",
                        "hash": blob_hash,
                        "mode": "100644",
                        "size": len(data),
                    }
                )
        return {"type": "tree", "entries": entries}

    return write_tree(store, _build_tree(workspace_root))


def _restore_tree(store, workspace_root: Path, tree_hash: str) -> None:
    if workspace_root.exists():
        shutil.rmtree(workspace_root)
    workspace_root.mkdir(parents=True, exist_ok=True)

    def _write_tree(target_dir: Path, current_tree_hash: str) -> None:
        tree_obj = read_tree(store, current_tree_hash)
        entries = tree_obj.get("entries") if isinstance(tree_obj, dict) else []
        if not isinstance(entries, list):
            return
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            kind = str(entry.get("kind") or "").strip()
            child_hash = str(entry.get("hash") or "").strip()
            if not name or not child_hash:
                continue
            child_path = target_dir / name
            if kind == "tree":
                child_path.mkdir(parents=True, exist_ok=True)
                _write_tree(child_path, child_hash)
                continue
            _materialize_blob(store, child_hash, child_path)

    _write_tree(workspace_root, tree_hash)


def _restore_history(session_id: str, markdown: str) -> List[Dict[str, Any]]:
    messages = parse_session_chat_markdown(markdown)
    save_group_history(session_id, messages)
    return messages


@contextmanager
def suppress_auto_checkpoint():
    token = _AUTO_CHECKPOINT_SUPPRESSED.set(True)
    try:
        yield
    finally:
        _AUTO_CHECKPOINT_SUPPRESSED.reset(token)


def auto_checkpoint_suppressed() -> bool:
    return bool(_AUTO_CHECKPOINT_SUPPRESSED.get())


def capture_session_checkpoint(session_id: str, *, reason: str = "manual") -> Dict[str, Any]:
    if auto_checkpoint_suppressed():
        return {"skipped": True, "reason": reason}

    layout = _session_layout(session_id)
    store = _object_store()
    meta_snapshot = _session_meta_snapshot(session_id)
    workspace_root = _workspace_root(session_id)
    history = load_group_history(session_id)
    markdown = _build_session_chat_markdown(history)
    chat_hash = write_blob(store, markdown.encode("utf-8"))
    tree_hash = _store_workspace_tree(store, workspace_root)
    state_hash = _canonical_state_hash(meta_snapshot, tree_hash, chat_hash)
    layout.chat_md.write_text(markdown, encoding="utf-8")

    chain = load_chain(layout)
    head = load_head(layout)
    if head:
        try:
            head_commit = read_commit(layout, head)
            if (
                str(head_commit.get("state_hash") or "").strip() == state_hash
                and str(head_commit.get("workspace_tree") or "").strip() == tree_hash
                and str(head_commit.get("chat_blob") or "").strip() == chat_hash
            ):
                return {
                    "id": head,
                    "commit_id": head,
                    "parent": str(head_commit.get("parent") or "") or None,
                    "tree_hash": tree_hash,
                    "workspace_tree": tree_hash,
                    "chat_blob": chat_hash,
                    "state_hash": state_hash,
                    "session_meta": meta_snapshot,
                    "reason": reason,
                    "existing": True,
                }
        except Exception:
            pass

    commit_id = f"commit-{uuid.uuid4().hex[:16]}"
    commit_obj = {
        "id": commit_id,
        "parent": head,
        "created_at": _now(),
        "reason": reason,
        "state_hash": state_hash,
        "workspace_tree": tree_hash,
        "chat_blob": chat_hash,
        "session_meta": meta_snapshot,
    }
    write_commit(layout, commit_id, commit_obj)
    chain.append(commit_id)
    save_chain(layout, chain)
    save_head(layout, commit_id)
    return commit_obj


def list_session_checkpoints(session_id: str) -> List[Dict[str, Any]]:
    layout = ensure_session_layout(_current_user_ctx(), session_id)
    chain = load_chain(layout)
    checkpoints: List[Dict[str, Any]] = []
    for commit_id in chain:
        try:
            checkpoints.append(read_commit(layout, commit_id))
        except Exception:
            continue
    return checkpoints


def _copy_session_state(source_session_id: str, target_session_id: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
    store = _object_store()
    layout = _session_layout(target_session_id)
    workspace_root = _workspace_root(target_session_id)
    _restore_tree(store, workspace_root, str(snapshot["workspace_tree"]))
    markdown = read_blob(store, str(snapshot["chat_blob"])).decode("utf-8", errors="ignore")
    layout.chat_md.write_text(markdown, encoding="utf-8")
    with suppress_auto_checkpoint():
        messages = _restore_history(target_session_id, markdown)
        meta = load_group_meta()
        cloned_meta = copy.deepcopy(snapshot["session_meta"])
        base_title = str(cloned_meta.get("title") or "新对话").strip() or "新对话"
        if not base_title.endswith("· 分叉"):
            cloned_meta["title"] = f"{base_title} · 分叉"
        cloned_meta["updated_at"] = _now()
        cloned_meta["created_at"] = _now()
        meta[target_session_id] = cloned_meta
        save_group_meta(meta)
    commit_id = f"commit-{uuid.uuid4().hex[:16]}"
    commit_obj = {
        "id": commit_id,
        "parent": str(snapshot.get("commit_id") or "") or None,
        "created_at": _now(),
        "reason": f"clone:{source_session_id}",
        "state_hash": snapshot["state_hash"],
        "workspace_tree": snapshot["workspace_tree"],
        "chat_blob": snapshot["chat_blob"],
        "session_meta": copy.deepcopy(snapshot["session_meta"]),
    }
    write_commit(layout, commit_id, commit_obj)
    save_chain(layout, [commit_id])
    save_head(layout, commit_id)
    return {
        "commit_id": commit_id,
        "messages": messages,
    }


def clone_session_from_checkpoint(session_id: str) -> Dict[str, Any]:
    source_snapshot = capture_session_checkpoint(session_id, reason="clone-source")
    if source_snapshot.get("skipped"):
        raise HTTPException(status_code=400, detail="Unable to snapshot source session")
    new_session_id = f"group-{uuid.uuid4().hex[:12]}"
    result = _copy_session_state(session_id, new_session_id, source_snapshot)
    cloned_meta = load_group_meta().get(new_session_id) or {}
    return {
        "source_session_id": session_id,
        "session_id": new_session_id,
        "title": str(cloned_meta.get("title") or "").strip() or None,
        "checkpoint_id": result["commit_id"],
        "source_checkpoint_id": source_snapshot.get("id") or source_snapshot.get("commit_id"),
    }


async def rollback_session_to_checkpoint(session_id: str, checkpoint_id: str) -> Dict[str, Any]:
    layout = _session_layout(session_id)
    store = _object_store()
    chain = load_chain(layout)
    if checkpoint_id not in chain:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    workspace_root = _workspace_root(session_id)
    commit = read_commit(layout, checkpoint_id)
    tree_hash = str(commit.get("workspace_tree") or "").strip()
    chat_blob = str(commit.get("chat_blob") or "").strip()
    meta_snapshot = commit.get("session_meta") if isinstance(commit.get("session_meta"), dict) else {}
    if not tree_hash or not chat_blob:
        raise HTTPException(status_code=500, detail="Invalid checkpoint")

    from app.agent.group_session_service import _cancel_group_session_run

    await _cancel_group_session_run(session_id, reason="rollback")

    _restore_tree(store, workspace_root, tree_hash)
    markdown = read_blob(store, chat_blob).decode("utf-8", errors="ignore")
    layout.chat_md.write_text(markdown, encoding="utf-8")
    with suppress_auto_checkpoint():
        _restore_history(session_id, markdown)
        meta = load_group_meta()
        current = meta.get(session_id)
        if isinstance(current, dict):
            restored = copy.deepcopy(meta_snapshot)
            restored["updated_at"] = _now()
            restored.setdefault("created_at", current.get("created_at") or restored.get("created_at") or _now())
            meta[session_id] = restored
            save_group_meta(meta)

    keep = chain[: chain.index(checkpoint_id) + 1]
    save_chain(layout, keep)
    save_head(layout, checkpoint_id)
    prune_commits(layout, keep)
    return {
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "kept_commits": keep,
    }


def format_session_chat_markdown(messages: Iterable[Dict[str, Any]]) -> str:
    return _build_session_chat_markdown(messages)
