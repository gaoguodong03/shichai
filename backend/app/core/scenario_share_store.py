"""公开分享对象：ZIP 存于 backend/data/scenario_shares/，registry.json 记录元数据。"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_SHARE_ID_RE = re.compile(r"^[a-f0-9]{12}$")
_ALLOWED_OBJECT_TYPES = {"scene", "expert", "skill", "mcp"}


def scenario_shares_root() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "scenario_shares"


def validate_share_id(share_id: str) -> bool:
    return bool(_SHARE_ID_RE.match((share_id or "").strip()))


def _registry_path() -> Path:
    return scenario_shares_root() / "registry.json"


def load_registry() -> Dict[str, Any]:
    p = _registry_path()
    if not p.is_file():
        return {"version": 1, "entries": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def save_registry(data: Dict[str, Any]) -> None:
    root = scenario_shares_root()
    root.mkdir(parents=True, exist_ok=True)
    _registry_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_share_entry(share_id: str) -> Optional[Dict[str, Any]]:
    if not validate_share_id(share_id):
        return None
    reg = load_registry()
    e = reg.get("entries", {}).get(share_id)
    return e if isinstance(e, dict) else None


def _entry_source_ref(entry: Dict[str, Any]) -> str:
    return str(entry.get("source_ref") or entry.get("source_preset_id") or "").strip()


def _entry_object_type(entry: Dict[str, Any]) -> str:
    t = str(entry.get("object_type") or "").strip().lower()
    return t if t in _ALLOWED_OBJECT_TYPES else "scene"


def find_share_id_for_object(created_by: str, object_type: str, source_ref: str) -> Optional[str]:
    """同一发布者 + 对象类型 + 来源 id 已存在时返回既有 share_id（链接固定）。"""
    u = (created_by or "").strip()
    otype = (object_type or "").strip().lower()
    sid = (source_ref or "").strip()
    if not u or not sid or otype not in _ALLOWED_OBJECT_TYPES:
        return None
    reg = load_registry()
    for share_id, e in reg.get("entries", {}).items():
        if not isinstance(e, dict):
            continue
        if (
            str(e.get("created_by") or "").strip() == u
            and _entry_object_type(e) == otype
            and _entry_source_ref(e) == sid
        ):
            if validate_share_id(str(share_id)):
                return str(share_id)
    return None


def find_share_id_for_source(created_by: str, source_preset_id: str) -> Optional[str]:
    """兼容旧接口：场景分享按 source_preset_id 查找。"""
    return find_share_id_for_object(created_by, "scene", source_preset_id)


def bundle_path_for_share(share_id: str) -> Optional[Path]:
    e = get_share_entry(share_id)
    if not e:
        return None
    fn = str(e.get("filename") or "").strip() or f"{share_id}.zip"
    if ".." in fn or "/" in fn or "\\" in fn:
        return None
    root = scenario_shares_root().resolve()
    p = (root / fn).resolve()
    try:
        p.relative_to(root)
    except ValueError:
        return None
    if not p.is_file():
        return None
    return p


def create_public_share(zip_bytes: bytes, meta: Dict[str, Any]) -> str:
    """写入 ZIP 与 registry，返回 12 位 hex share_id。"""
    root = scenario_shares_root()
    root.mkdir(parents=True, exist_ok=True)
    share_id = ""
    for _ in range(16):
        cand = secrets.token_hex(6)
        zp = root / f"{cand}.zip"
        if not zp.exists():
            share_id = cand
            break
    if not share_id:
        raise RuntimeError("无法分配分享 id")
    zpath = root / f"{share_id}.zip"
    zpath.write_bytes(zip_bytes)
    reg = load_registry()
    entries = reg.setdefault("entries", {})
    now = datetime.now(timezone.utc).isoformat()
    obj_type = str(meta.get("object_type") or "scene").strip().lower()
    if obj_type not in _ALLOWED_OBJECT_TYPES:
        obj_type = "scene"
    source_ref = str(meta.get("source_ref") or meta.get("source_preset_id") or "").strip()
    payload = dict(meta)
    payload["object_type"] = obj_type
    payload["source_ref"] = source_ref
    if obj_type == "scene" and not payload.get("source_preset_id"):
        payload["source_preset_id"] = source_ref
    entries[share_id] = {**payload, "filename": f"{share_id}.zip", "created_at": now}
    save_registry(reg)
    return share_id


def upsert_public_share(zip_bytes: bytes, meta: Dict[str, Any]) -> str:
    """同一发布者 + object_type + source_ref 复用同一 share_id 并覆盖 ZIP；否则新建。"""
    source = str(meta.get("source_ref") or meta.get("source_preset_id") or "").strip()
    obj_type = str(meta.get("object_type") or "scene").strip().lower()
    if obj_type not in _ALLOWED_OBJECT_TYPES:
        obj_type = "scene"
    user = str(meta.get("created_by") or "").strip()
    root = scenario_shares_root()
    root.mkdir(parents=True, exist_ok=True)
    existing = find_share_id_for_object(user, obj_type, source)
    reg = load_registry()
    entries = reg.setdefault("entries", {})
    now = datetime.now(timezone.utc).isoformat()

    if existing:
        share_id = existing
        zpath = root / f"{share_id}.zip"
        zpath.write_bytes(zip_bytes)
        prev = dict(entries.get(share_id, {}))
        prev.update(
            {
                **meta,
                "filename": f"{share_id}.zip",
                "object_type": obj_type,
                "source_ref": source,
                "preset_name": str(meta.get("preset_name") or ""),
                "source_preset_id": source if obj_type == "scene" else str(meta.get("source_preset_id") or ""),
                "created_by": user,
                "updated_at": now,
            }
        )
        if not prev.get("created_at"):
            prev["created_at"] = now
        entries[share_id] = prev
        save_registry(reg)
        return share_id

    return create_public_share(zip_bytes, meta)
