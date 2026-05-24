"""Helpers for mirroring aggregate config rows into per-resource JSON files."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, Iterable

from app.core.atomic_json import atomic_write_json


def resource_filename_for_id(resource_id: str) -> str:
    """Return a filesystem-safe JSON filename for a resource id."""
    rid = str(resource_id or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in rid)
    return safe.strip("._") or "resource"


def legacy_resource_json_filename_for_id(resource_id: str) -> str:
    """Return the legacy flat JSON filename for a resource id."""
    safe = resource_filename_for_id(resource_id)
    return f"{safe}.json"


def mirror_rows_to_resource_dir(
    rows: Iterable[Dict[str, Any]],
    resource_dir: Path,
    id_key: str,
    *,
    body_filename: str,
) -> None:
    """Write one standard resource body file per row and remove stale mirrors."""
    resource_dir.mkdir(parents=True, exist_ok=True)
    desired: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get(id_key) or "").strip()
        if not rid:
            continue
        dirname = resource_filename_for_id(rid)
        desired.add(dirname)
        payload = dict(row)
        payload.setdefault("id", rid)
        atomic_write_json(resource_dir / dirname / body_filename, payload)

        legacy_file = resource_dir / legacy_resource_json_filename_for_id(rid)
        try:
            legacy_file.unlink()
        except FileNotFoundError:
            pass

    for existing in resource_dir.iterdir():
        if existing.is_file() and existing.suffix == ".json":
            try:
                existing.unlink()
            except FileNotFoundError:
                pass
            continue
        if not existing.is_dir() or existing.name.startswith(".") or existing.name in desired:
            continue
        if (existing / body_filename).is_file():
            shutil.rmtree(existing, ignore_errors=True)
