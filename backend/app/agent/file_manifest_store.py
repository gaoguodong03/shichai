"""Session artifact manifest store (local disk source-of-truth)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.files import get_workspace_root_path

MANIFEST_DIR = "memory"
MANIFEST_FILE = "file_manifest.json"


def _workspace_root(session_id: str) -> Path:
    root = get_workspace_root_path(session_id)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _manifest_path(session_id: str) -> Path:
    mem = _workspace_root(session_id) / MANIFEST_DIR
    mem.mkdir(parents=True, exist_ok=True)
    return mem / MANIFEST_FILE


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


@dataclass
class FileManifestItem:
    file_id: str
    path: str
    sha256: str
    size: int
    task_id: str
    producer_dha_id: str
    created_at: str
    tags: List[str]
    token_version: int = 0


def load_manifest(session_id: str) -> List[Dict[str, Any]]:
    p = _manifest_path(session_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_manifest(session_id: str, items: List[Dict[str, Any]]) -> None:
    p = _manifest_path(session_id)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def append_manifest_item(
    *,
    session_id: str,
    abs_file_path: Path,
    file_id: str,
    task_id: str,
    producer_dha_id: str,
    tags: Optional[List[str]] = None,
    token_version: int = 0,
) -> Dict[str, Any]:
    ws = _workspace_root(session_id).resolve()
    target = abs_file_path.resolve()
    if not str(target).startswith(str(ws)):
        raise ValueError("file path out of session workspace scope")
    if not target.exists() or not target.is_file():
        raise FileNotFoundError(str(target))
    item = FileManifestItem(
        file_id=file_id,
        path=str(target.relative_to(ws)).replace("\\", "/"),
        sha256=_sha256_file(target),
        size=target.stat().st_size,
        task_id=task_id,
        producer_dha_id=producer_dha_id,
        created_at=datetime.now(timezone.utc).isoformat(),
        tags=list(tags or []),
        token_version=int(token_version),
    )
    all_items = load_manifest(session_id)
    all_items.append(asdict(item))
    save_manifest(session_id, all_items)
    return asdict(item)
