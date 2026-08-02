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
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from app.api.group_chat_state import (
    format_storage_timestamp,
    load_group_history,
    load_group_orchestration_state,
    load_session_definitions,
    reject_group_session_mutation_if_running,
    save_group_history,
    save_session_definitions,
    write_group_orchestration_state,
)
from app.core.security import get_current_user
from app.core.user_context import UserContext

from .paths import SessionLayoutPaths, ensure_session_layout
from .store import (
    blob_path,
    load_chain,
    load_head,
    read_blob,
    read_checkpoint,
    read_tree,
    save_chain,
    save_head,
    user_object_store,
    write_blob,
    write_checkpoint,
    write_tree,
)

_AUTO_CHECKPOINT_SUPPRESSED: ContextVar[bool] = ContextVar("session_state_auto_checkpoint_suppressed", default=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_user_ctx() -> UserContext:
    return get_current_user().ctx


def _session_layout(session_id: str) -> SessionLayoutPaths:
    return ensure_session_layout(_current_user_ctx(), session_id)


def _object_store(session_id: str) -> Any:
    return user_object_store(_session_layout(session_id))


def _workspace_root(session_id: str) -> Path:
    layout = _session_layout(session_id)
    layout.workspace.mkdir(parents=True, exist_ok=True)
    return layout.workspace


def _memory_root(session_id: str) -> Path:
    root = _session_layout(session_id).session_root / "memory"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_definition_snapshot(session_id: str) -> Dict[str, Any]:
    session_definitions = load_session_definitions()
    item = session_definitions.get(session_id)
    if not isinstance(item, dict):
        raise HTTPException(status_code=404, detail="Group session not found")
    allowed = {
        "id",
        "title",
        "title_auto_generated",
        "agent_names",
        "host",
        "scenario_prompt",
        "allow_agent_recruitment",
        "created_at",
        "updated_at",
    }
    return {key: copy.deepcopy(value) for key, value in item.items() if key in allowed}


def _canonical_json_bytes(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _state_hash(
    *,
    session_blob: str,
    history_blob: str,
    orchestration_state_blob: str | None,
    workspace_tree: str,
    memory_tree: str,
) -> str:
    payload = {
        "session_blob": session_blob,
        "history_blob": history_blob,
        "orchestration_state_blob": orchestration_state_blob,
        "workspace_tree": workspace_tree,
        "memory_tree": memory_tree,
    }
    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def _materialize_blob(store, blob_hash: str, dest: Path) -> None:
    src = blob_path(store, blob_hash)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    try:
        os.link(src, dest)
    except OSError:
        dest.write_bytes(read_blob(store, blob_hash))


def _store_tree(store, root: Path) -> str:
    def _build_tree(path: Path) -> Dict[str, Any]:
        entries: List[Dict[str, Any]] = []
        if path.exists() and path.is_dir():
            for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                if child.is_dir():
                    subtree = _build_tree(child)
                    entries.append(
                        {
                            "name": child.name,
                            "kind": "tree",
                            "hash": write_tree(store, subtree),
                            "mode": "040000",
                        }
                    )
                    continue
                if not child.is_file():
                    continue
                data = child.read_bytes()
                entries.append(
                    {
                        "name": child.name,
                        "kind": "blob",
                        "hash": write_blob(store, data),
                        "mode": "100644",
                        "size": len(data),
                    }
                )
        return {"type": "tree", "entries": entries}

    return write_tree(store, _build_tree(root))


def _restore_tree(store, root: Path, tree_hash: str) -> None:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

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

    _write_tree(root, tree_hash)


def _read_json_blob(store, blob_hash: str) -> Any:
    raw = read_blob(store, blob_hash).decode("utf-8", errors="ignore")
    return json.loads(raw) if raw.strip() else {}


def _blob_hash_from_tree_path(store, tree_hash: str, rel_path: str) -> str:
    parts = [part for part in str(rel_path or "").replace("\\", "/").split("/") if part]
    current_tree_hash = str(tree_hash or "").strip()
    for index, part in enumerate(parts):
        tree_obj = read_tree(store, current_tree_hash)
        entries = tree_obj.get("entries") if isinstance(tree_obj, dict) else []
        if not isinstance(entries, list):
            raise FileNotFoundError(rel_path)
        match = next((entry for entry in entries if isinstance(entry, dict) and entry.get("name") == part), None)
        if not isinstance(match, dict):
            raise FileNotFoundError(rel_path)
        kind = str(match.get("kind") or "").strip()
        child_hash = str(match.get("hash") or "").strip()
        if not child_hash:
            raise FileNotFoundError(rel_path)
        if index == len(parts) - 1:
            if kind != "blob":
                raise FileNotFoundError(rel_path)
            return child_hash
        if kind != "tree":
            raise FileNotFoundError(rel_path)
        current_tree_hash = child_hash
    raise FileNotFoundError(rel_path)


def read_workspace_text_from_checkpoint(session_id: str, checkpoint_id: str, rel_path: str) -> str:
    """Read a UTF-8 workspace file from one checkpoint's immutable workspace_tree."""
    layout = _session_layout(session_id)
    checkpoint = read_checkpoint(layout, checkpoint_id)
    store = _object_store(session_id)
    blob_hash = _blob_hash_from_tree_path(store, str(checkpoint.get("workspace_tree") or ""), rel_path)
    return read_blob(store, blob_hash).decode("utf-8")


@contextmanager
def suppress_auto_checkpoint():
    token = _AUTO_CHECKPOINT_SUPPRESSED.set(True)
    try:
        yield
    finally:
        _AUTO_CHECKPOINT_SUPPRESSED.reset(token)


def auto_checkpoint_suppressed() -> bool:
    return bool(_AUTO_CHECKPOINT_SUPPRESSED.get())


def _build_session_checkpoint(
    session_id: str,
    *,
    trigger: str,
    checkpoint_id: str | None,
    parent_checkpoint_id: str | None,
) -> Dict[str, Any]:
    """Build a complete checkpoint object without updating the session checkpoint chain."""
    store = _object_store(session_id)
    session_definition = _session_definition_snapshot(session_id)
    history = load_group_history(session_id)
    orchestration_state = load_group_orchestration_state(session_id)
    session_blob = write_blob(store, _canonical_json_bytes(session_definition))
    history_blob = write_blob(store, _canonical_json_bytes(history))
    orchestration_state_blob = write_blob(store, _canonical_json_bytes(orchestration_state)) if orchestration_state else None
    workspace_tree = _store_tree(store, _workspace_root(session_id))
    memory_tree = _store_tree(store, _memory_root(session_id))
    state_hash = _state_hash(
        session_blob=session_blob,
        history_blob=history_blob,
        orchestration_state_blob=orchestration_state_blob,
        workspace_tree=workspace_tree,
        memory_tree=memory_tree,
    )
    last_message_id = str(history[-1].get("message_id") or "").strip() if history else None
    return {
        "checkpoint_id": checkpoint_id,
        "parent_checkpoint_id": parent_checkpoint_id,
        "created_at": _now(),
        "trigger": trigger,
        "session_blob": session_blob,
        "history_blob": history_blob,
        "orchestration_state_blob": orchestration_state_blob,
        "workspace_tree": workspace_tree,
        "memory_tree": memory_tree,
        "state_hash": state_hash,
        "last_message_id": last_message_id,
    }


def capture_session_checkpoint(session_id: str, *, trigger: str = "manual_snapshot", force: bool = False) -> Dict[str, Any]:
    """Capture the current file-backed session state as a checkpoint object."""
    if auto_checkpoint_suppressed():
        return {"skipped": True, "trigger": trigger}

    layout = _session_layout(session_id)
    chain = load_chain(layout)
    head = load_head(layout)
    checkpoint_id = f"checkpoint-{uuid.uuid4().hex[:16]}"
    checkpoint = _build_session_checkpoint(
        session_id,
        trigger=trigger,
        checkpoint_id=checkpoint_id,
        parent_checkpoint_id=head,
    )
    if not force and head and trigger not in {"manual_snapshot", "rollback"}:
        try:
            current = read_checkpoint(layout, head)
            if str(current.get("state_hash") or "") == str(checkpoint.get("state_hash") or ""):
                return {**current, "existing": True}
        except Exception:
            pass

    write_checkpoint(layout, checkpoint_id, checkpoint)
    chain.append(checkpoint_id)
    save_chain(layout, chain)
    save_head(layout, checkpoint_id)
    return checkpoint


def list_session_checkpoints(session_id: str) -> List[Dict[str, Any]]:
    """Return checkpoint objects in chain order."""
    layout = _session_layout(session_id)
    checkpoints: List[Dict[str, Any]] = []
    for checkpoint_id in load_chain(layout):
        try:
            checkpoints.append(read_checkpoint(layout, checkpoint_id))
        except Exception:
            continue
    return checkpoints


def _checkpoint_from_id(session_id: str, checkpoint_id: str) -> Dict[str, Any]:
    layout = _session_layout(session_id)
    if checkpoint_id not in load_chain(layout):
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    checkpoint = read_checkpoint(layout, checkpoint_id)
    if not checkpoint:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return checkpoint


def _copy_blob(source_store, target_store, blob_hash: str | None) -> str | None:
    if not blob_hash:
        return None
    return write_blob(target_store, read_blob(source_store, blob_hash))


def _copy_tree(source_store, target_store, tree_hash: str) -> str:
    tree_obj = read_tree(source_store, tree_hash)
    for entry in tree_obj.get("entries", []) if isinstance(tree_obj, dict) else []:
        if not isinstance(entry, dict):
            continue
        kind = str(entry.get("kind") or "")
        child_hash = str(entry.get("hash") or "")
        if not child_hash:
            continue
        if kind == "blob":
            _copy_blob(source_store, target_store, child_hash)
        elif kind == "tree":
            _copy_tree(source_store, target_store, child_hash)
    return write_tree(target_store, tree_obj)


def _apply_checkpoint(session_id: str, checkpoint: Dict[str, Any], *, source_session_id: str | None = None) -> None:
    source_id = source_session_id or session_id
    source_store = _object_store(source_id)
    layout = _session_layout(session_id)
    session_definition = _read_json_blob(source_store, str(checkpoint["session_blob"]))
    history = _read_json_blob(source_store, str(checkpoint["history_blob"]))
    orchestration_blob = checkpoint.get("orchestration_state_blob")
    orchestration_state = _read_json_blob(source_store, str(orchestration_blob)) if orchestration_blob else {}
    if not isinstance(session_definition, dict) or not isinstance(history, list):
        raise HTTPException(status_code=500, detail="Invalid checkpoint")

    _restore_tree(source_store, layout.workspace, str(checkpoint["workspace_tree"]))
    _restore_tree(source_store, _memory_root(session_id), str(checkpoint["memory_tree"]))
    with suppress_auto_checkpoint():
        session_definitions = load_session_definitions()
        current = session_definitions.get(session_id) if isinstance(session_definitions.get(session_id), dict) else {}
        restored = copy.deepcopy(session_definition)
        restored["updated_at"] = format_storage_timestamp()
        restored.setdefault("created_at", current.get("created_at") or restored.get("created_at") or format_storage_timestamp())
        session_definitions[session_id] = restored
        save_session_definitions(session_definitions)
        save_group_history(session_id, history)
        write_group_orchestration_state(session_id, orchestration_state if isinstance(orchestration_state, dict) else {})


def _checkpoint_for_message(session_id: str, *, message_id: str | None = None) -> Dict[str, Any]:
    checkpoints = list_session_checkpoints(session_id)
    if not message_id:
        if not checkpoints:
            raise HTTPException(status_code=404, detail="Checkpoint not found")
        return checkpoints[-1]
    history = load_group_history(session_id)
    message_positions = {
        str(item.get("message_id") or "").strip(): idx
        for idx, item in enumerate(history)
        if isinstance(item, dict) and str(item.get("message_id") or "").strip()
    }
    target_idx = message_positions.get(message_id)
    if target_idx is None:
        raise HTTPException(status_code=404, detail="Message not found")
    for checkpoint in reversed(checkpoints):
        if str(checkpoint.get("last_message_id") or "") == message_id:
            return checkpoint
    best: Dict[str, Any] | None = None
    best_idx = -1
    for checkpoint in checkpoints:
        checkpoint_message_id = str(checkpoint.get("last_message_id") or "").strip()
        checkpoint_idx = message_positions.get(checkpoint_message_id)
        if checkpoint_idx is None or checkpoint_idx > target_idx:
            continue
        if checkpoint_idx >= best_idx:
            best = checkpoint
            best_idx = checkpoint_idx
    if best is not None:
        return best
    raise HTTPException(status_code=404, detail="Checkpoint not found for message")


def _copy_session_state(source_session_id: str, target_session_id: str, checkpoint: Dict[str, Any]) -> Dict[str, Any]:
    source_store = _object_store(source_session_id)
    layout = _session_layout(target_session_id)
    target_store = _object_store(target_session_id)
    session_definition = _read_json_blob(source_store, str(checkpoint["session_blob"]))
    if not isinstance(session_definition, dict):
        raise HTTPException(status_code=500, detail="Invalid checkpoint")
    copied = copy.deepcopy(checkpoint)
    copied["checkpoint_id"] = f"checkpoint-{uuid.uuid4().hex[:16]}"
    copied["parent_checkpoint_id"] = None
    copied["trigger"] = "clone"
    copied["session_blob"] = _copy_blob(source_store, target_store, str(checkpoint["session_blob"]))
    copied["history_blob"] = _copy_blob(source_store, target_store, str(checkpoint["history_blob"]))
    copied["orchestration_state_blob"] = _copy_blob(source_store, target_store, checkpoint.get("orchestration_state_blob"))
    copied["workspace_tree"] = _copy_tree(source_store, target_store, str(checkpoint["workspace_tree"]))
    copied["memory_tree"] = _copy_tree(source_store, target_store, str(checkpoint["memory_tree"]))
    copied["state_hash"] = _state_hash(
        session_blob=str(copied["session_blob"]),
        history_blob=str(copied["history_blob"]),
        orchestration_state_blob=copied.get("orchestration_state_blob"),
        workspace_tree=str(copied["workspace_tree"]),
        memory_tree=str(copied["memory_tree"]),
    )

    base_title = str(session_definition.get("title") or "新对话").strip() or "新对话"
    if not base_title.endswith("· 分叉"):
        session_definition["title"] = f"{base_title} · 分叉"
    session_now = format_storage_timestamp()
    session_definition["updated_at"] = session_now
    session_definition["created_at"] = session_now
    with suppress_auto_checkpoint():
        session_definitions = load_session_definitions()
        session_definitions[target_session_id] = session_definition
        save_session_definitions(session_definitions)
        history = _read_json_blob(source_store, str(checkpoint["history_blob"]))
        save_group_history(target_session_id, history if isinstance(history, list) else [])
        orchestration_blob = checkpoint.get("orchestration_state_blob")
        orchestration_state = _read_json_blob(source_store, str(orchestration_blob)) if orchestration_blob else {}
        write_group_orchestration_state(target_session_id, orchestration_state if isinstance(orchestration_state, dict) else {})
    _restore_tree(target_store, layout.workspace, str(copied["workspace_tree"]))
    _restore_tree(target_store, _memory_root(target_session_id), str(copied["memory_tree"]))
    write_checkpoint(layout, str(copied["checkpoint_id"]), copied)
    save_chain(layout, [str(copied["checkpoint_id"])])
    save_head(layout, str(copied["checkpoint_id"]))
    return copied


def clone_session_from_checkpoint(
    session_id: str,
    *,
    checkpoint_id: Optional[str] = None,
    message_id: Optional[str] = None,
) -> Dict[str, Any]:
    reject_group_session_mutation_if_running(session_id, operation="cloning")
    normalized_checkpoint_id = str(checkpoint_id or "").strip()
    normalized_message_id = str(message_id or "").strip()
    if normalized_checkpoint_id:
        source = _checkpoint_from_id(session_id, normalized_checkpoint_id)
    elif normalized_message_id:
        source = _checkpoint_for_message(session_id, message_id=normalized_message_id)
    else:
        layout = _session_layout(session_id)
        source = _build_session_checkpoint(
            session_id,
            trigger="clone",
            checkpoint_id=None,
            parent_checkpoint_id=load_head(layout),
        )
    new_session_id = f"group-{uuid.uuid4().hex[:12]}"
    copied = _copy_session_state(session_id, new_session_id, source)
    cloned_session_definition = load_session_definitions().get(new_session_id) or {}
    source_checkpoint_id = source.get("checkpoint_id") if isinstance(source.get("checkpoint_id"), str) else None
    return {
        "source_session_id": session_id,
        "session_id": new_session_id,
        "title": str(cloned_session_definition.get("title") or "").strip() or None,
        "checkpoint_id": copied["checkpoint_id"],
        "source_checkpoint_id": source_checkpoint_id,
    }


async def rollback_session_to_checkpoint(session_id: str, checkpoint_id: str) -> Dict[str, Any]:
    reject_group_session_mutation_if_running(session_id, operation="rollback")
    layout = _session_layout(session_id)
    chain = load_chain(layout)
    if checkpoint_id not in chain:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    checkpoint = read_checkpoint(layout, checkpoint_id)
    _apply_checkpoint(session_id, checkpoint)
    rollback_checkpoint = capture_session_checkpoint(session_id, trigger="rollback")
    return {
        "session_id": session_id,
        "checkpoint_id": rollback_checkpoint.get("checkpoint_id"),
        "source_checkpoint_id": checkpoint_id,
    }


async def rollback_session_to_message(
    session_id: str,
    *,
    message_id: Optional[str] = None,
    checkpoint_id: Optional[str] = None,
) -> Dict[str, Any]:
    if checkpoint_id:
        return await rollback_session_to_checkpoint(session_id, checkpoint_id)
    if not message_id:
        raise HTTPException(status_code=400, detail="checkpoint_id or message_id is required")
    checkpoint = _checkpoint_for_message(session_id, message_id=message_id)
    return await rollback_session_to_checkpoint(session_id, str(checkpoint["checkpoint_id"]))
