"""用户设置中 Skill/MCP 引用关系的更新服务。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.core.user_context import get_current_user_context


def _read_json_list(path: Path) -> List[Dict[str, Any]] | None:
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return raw if isinstance(raw, list) else None


def _write_json_list(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def replace_skill_path_in_user_configs(old_path: str, new_path: str) -> None:
    """Skill directory path changes should update stored path fields only."""
    if not old_path or not new_path or old_path == new_path:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    path = (user_ctx.config_dir / "agents.json").resolve()
    raw = _read_json_list(path)
    if raw is None:
        return
    changed = False
    for inst in raw:
        if not isinstance(inst, dict):
            continue
        skills = inst.get("skills")
        if not isinstance(skills, list):
            continue
        updated = []
        changed_row = False
        for item in skills:
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            if str(copied.get("directory_name") or "").strip() == old_path:
                copied["directory_name"] = new_path
                changed_row = True
            updated.append(copied)
        if changed_row:
            inst["skills"] = updated
            changed = True
    if changed:
        try:
            _write_json_list(path, raw)
        except Exception:
            pass
    preset_path = (user_ctx.config_dir / "session_presets.json").resolve()
    presets = _read_json_list(preset_path)
    if presets is None:
        return
    changed = False
    for preset in presets:
        if not isinstance(preset, dict) or not isinstance(preset.get("host_config"), dict):
            continue
        hc = preset["host_config"]
        if str(hc.get("skill_directory") or "").strip() == old_path:
            hc["skill_directory"] = new_path
            changed = True
    if changed:
        try:
            _write_json_list(preset_path, presets)
        except Exception:
            pass


def remove_skill_path_from_user_configs(skill_path: str, skill_name: str = "") -> None:
    """删除技能后保留引用名称，目录路径仅用于缺失显示。"""
    path_name = (skill_path or "").strip()
    if not path_name:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    paths = [
        (user_ctx.config_dir / "agents.json").resolve(),
        (user_ctx.config_dir / "session_presets.json").resolve(),
    ]
    for path in paths:
        raw = _read_json_list(path)
        if raw is None:
            continue
        changed = False
        for row in raw:
            if not isinstance(row, dict):
                continue
            targets = [row]
            if isinstance(row.get("host_config"), dict):
                targets.append(row["host_config"])
            for target in targets:
                if "skill_directory" in target and str(target.get("skill_directory") or "").strip() == path_name and skill_name:
                    target["skill_name"] = skill_name
                    changed = True
                    continue
                skills = target.get("skills")
                if not isinstance(skills, list):
                    continue
                updated = []
                changed_row = False
                for item in skills:
                    if not isinstance(item, dict):
                        continue
                    copied = dict(item)
                    if str(copied.get("directory_name") or "").strip() == path_name and skill_name:
                        copied["name"] = skill_name
                        changed_row = True
                    updated.append(copied)
                if changed_row:
                    target["skills"] = updated
                    changed = True
        if changed:
            try:
                _write_json_list(path, raw)
            except Exception:
                pass
