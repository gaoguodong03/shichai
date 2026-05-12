"""设置导入 bundle 时的冲突检测与引用更新。"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from app.core.scenario_bundle import copy_bundle_skills_to_user, list_skill_ids_in_bundle_skills_dir
from app.core.settings_references import replace_skill_id_in_user_configs


def normalized_name_key(raw: Any) -> str:
    return str(raw or "").strip().casefold()


def mcp_conflict_id_map(existing_servers: List[Dict[str, Any]], bundle_servers: List[Dict[str, Any]]) -> Dict[str, str]:
    by_id = {str(s.get("id") or "").strip(): s for s in existing_servers if str(s.get("id") or "").strip()}
    id_map: Dict[str, str] = {}
    for incoming in bundle_servers:
        incoming_id = str(incoming.get("id") or "").strip()
        incoming_name = normalized_name_key(incoming.get("name"))
        if not incoming_id:
            continue
        for old_id, old in by_id.items():
            if old_id == incoming_id:
                continue
            if incoming_name and normalized_name_key(old.get("name")) == incoming_name:
                id_map[old_id] = incoming_id
    return id_map


def _read_skill_frontmatter(skill_dir: Path) -> Dict[str, Any]:
    path = skill_dir / "SKILL.md"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.strip().startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def skill_conflict_id_map(bundle_dir: Path, user_skills_dir: Path, skill_ids: List[str]) -> Dict[str, str]:
    id_map: Dict[str, str] = {}
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    existing_by_id: Dict[str, str] = {}
    existing_name_to_ids: Dict[str, List[str]] = {}
    for child in sorted(user_skills_dir.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        fm = _read_skill_frontmatter(child)
        sid = child.name
        existing_by_id[sid] = normalized_name_key(fm.get("name") or sid)
        if existing_by_id[sid]:
            existing_name_to_ids.setdefault(existing_by_id[sid], []).append(sid)

    for incoming_id in skill_ids:
        src = bundle_dir / "skills" / incoming_id
        if not src.is_dir() or not (src / "SKILL.md").is_file():
            continue
        fm = _read_skill_frontmatter(src)
        incoming_name_key = normalized_name_key(fm.get("name") or incoming_id)
        conflict_ids: List[str] = []
        if incoming_id in existing_by_id:
            conflict_ids.append(incoming_id)
        if incoming_name_key:
            conflict_ids.extend(old_id for old_id in existing_name_to_ids.get(incoming_name_key, []) if old_id != incoming_id)
        for old_id in dict.fromkeys(conflict_ids):
            id_map[old_id] = incoming_id
    return id_map


def copy_bundle_skills_to_user_by_name(bundle_dir: Path, user_skills_dir: Path) -> Tuple[List[str], List[str], Dict[str, str]]:
    skill_ids = list_skill_ids_in_bundle_skills_dir(bundle_dir)
    id_map = skill_conflict_id_map(bundle_dir, user_skills_dir, skill_ids)
    overwritten = sorted(id_map.keys())
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    for old_id in overwritten:
        old_dir = user_skills_dir / old_id
        if old_dir.is_dir():
            shutil.rmtree(old_dir, ignore_errors=True)
    imported, _skipped = copy_bundle_skills_to_user(bundle_dir, user_skills_dir, overwrite=True)
    for old_id, new_id in id_map.items():
        replace_skill_id_in_user_configs(old_id, new_id)
    return imported, overwritten, id_map
