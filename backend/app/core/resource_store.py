"""Helpers for mirroring aggregate config rows into per-resource JSON files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable

from app.core.atomic_json import atomic_write_json


def resource_filename_for_id(resource_id: str) -> str:
    """Return a filesystem-safe JSON filename for a resource id."""
    rid = str(resource_id or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in rid)
    safe = safe.strip("._") or "resource"
    return f"{safe}.json"


def mirror_rows_to_resource_dir(rows: Iterable[Dict[str, Any]], resource_dir: Path, id_key: str) -> None:
    """Write one JSON file per row and remove stale mirrored JSON files."""
    resource_dir.mkdir(parents=True, exist_ok=True)
    desired: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get(id_key) or "").strip()
        if not rid:
            continue
        filename = resource_filename_for_id(rid)
        desired.add(filename)
        atomic_write_json(resource_dir / filename, row)

    for existing in resource_dir.glob("*.json"):
        if existing.name not in desired:
            try:
                existing.unlink()
            except FileNotFoundError:
                pass
