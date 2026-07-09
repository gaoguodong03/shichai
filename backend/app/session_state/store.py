from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.atomic_json import atomic_write_json
from .paths import SessionLayoutPaths, UserObjectStorePaths, ensure_session_layout


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json(data: Any) -> bytes:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def user_object_store(layout: SessionLayoutPaths) -> UserObjectStorePaths:
    return UserObjectStorePaths.from_session_layout(layout)


def write_blob(store: UserObjectStorePaths, data: bytes) -> str:
    blob_hash = _sha256_bytes(data)
    blob_path = store.blobs / blob_hash
    if not blob_path.exists():
        blob_path.write_bytes(data)
    return blob_hash


def read_blob(store: UserObjectStorePaths, blob_hash: str) -> bytes:
    return (store.blobs / blob_hash).read_bytes()


def blob_path(store: UserObjectStorePaths, blob_hash: str) -> Path:
    return store.blobs / blob_hash


def write_tree(store: UserObjectStorePaths, tree_obj: Dict[str, Any]) -> str:
    tree_bytes = _canonical_json(tree_obj)
    tree_hash = _sha256_bytes(tree_bytes)
    tree_path = store.trees / f"{tree_hash}.json"
    if not tree_path.exists():
        tree_path.write_bytes(tree_bytes)
    return tree_hash


def read_tree(store: UserObjectStorePaths, tree_hash: str) -> Dict[str, Any]:
    raw = (store.trees / f"{tree_hash}.json").read_text(encoding="utf-8")
    data = json.loads(raw)
    return data if isinstance(data, dict) else {"type": "tree", "entries": []}


def write_checkpoint(layout: SessionLayoutPaths, checkpoint_id: str, checkpoint_obj: Dict[str, Any]) -> Path:
    checkpoint_path = layout.snapshots / f"{checkpoint_id}.json"
    atomic_write_json(checkpoint_path, checkpoint_obj)
    return checkpoint_path


def read_checkpoint(layout: SessionLayoutPaths, checkpoint_id: str) -> Dict[str, Any]:
    checkpoint_path = layout.snapshots / f"{checkpoint_id}.json"
    data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def load_chain(layout: SessionLayoutPaths) -> List[str]:
    chain_path = layout.chain
    if not chain_path.exists():
        return []
    try:
        data = json.loads(chain_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def save_chain(layout: SessionLayoutPaths, chain: Iterable[str]) -> None:
    atomic_write_json(layout.chain, [str(item) for item in chain if str(item).strip()])


def load_head(layout: SessionLayoutPaths) -> Optional[str]:
    head_path = layout.head
    if not head_path.exists():
        return None
    try:
        data = json.loads(head_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    head = str(data.get("head") or "").strip() if isinstance(data, dict) else ""
    return head or None


def save_head(layout: SessionLayoutPaths, checkpoint_id: Optional[str]) -> None:
    atomic_write_json(layout.head, {"head": checkpoint_id or ""})


def prune_checkpoints(layout: SessionLayoutPaths, keep_checkpoint_ids: Iterable[str]) -> None:
    keep = {str(item).strip() for item in keep_checkpoint_ids if str(item).strip()}
    if not layout.snapshots.exists():
        return
    for checkpoint_path in layout.snapshots.glob("*.json"):
        if checkpoint_path.stem in keep:
            continue
        try:
            checkpoint_path.unlink()
        except OSError:
            pass


def clear_directory_contents(path: Path) -> None:
    if not path.exists():
        return
    for child in path.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)


SessionStatePaths = SessionLayoutPaths
ensure_session_state_layout = ensure_session_layout
