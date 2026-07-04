"""用户资源中 Skill/MCP 引用关系的更新服务。"""
from __future__ import annotations

from typing import Any, Dict, List

from app.core.user_context import get_current_user_context


def _load_agent_rows() -> List[Dict[str, Any]]:
    from app.api.agents import load_agent_instances

    return load_agent_instances()


def _save_agent_rows(rows: List[Dict[str, Any]]) -> None:
    from app.api.agents import save_agent_instances

    save_agent_instances(rows)


def _load_scenario_rows() -> List[Dict[str, Any]]:
    from app.api.settings_presets import _load_session_preset_rows_from_resource_files

    return _load_session_preset_rows_from_resource_files()


def _save_scenario_rows(rows: List[Dict[str, Any]]) -> None:
    from app.api.settings_presets import _mirror_session_presets_to_resources

    _mirror_session_presets_to_resources(rows)


def replace_skill_path_in_user_configs(old_path: str, new_path: str) -> None:
    """Skill directory path changes should update stored path fields only."""
    if not old_path or not new_path or old_path == new_path:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    raw = _load_agent_rows()
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
        _save_agent_rows(raw)
    presets = _load_scenario_rows()
    changed = False
    for preset in presets:
        if not isinstance(preset, dict) or not isinstance(preset.get("host_config"), dict):
            continue
        hc = preset["host_config"]
        if str(hc.get("skill_directory") or "").strip() == old_path:
            hc["skill_directory"] = new_path
            changed = True
    if changed:
        _save_scenario_rows(presets)


def remove_skill_path_from_user_configs(skill_path: str, skill_name: str = "") -> None:
    """删除技能后保留引用名称，目录路径仅用于缺失显示。"""
    path_name = (skill_path or "").strip()
    if not path_name:
        return
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return
    resource_sets = [
        (_load_agent_rows(), _save_agent_rows),
        (_load_scenario_rows(), _save_scenario_rows),
    ]
    for raw, save_rows in resource_sets:
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
            save_rows(raw)
