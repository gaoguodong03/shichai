"""Skill storage, discovery, and SKILL.md read/write helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import HTTPException

from app.api.settings_mcp import load_mcp_config
from app.api.settings_skill_frontmatter import (
    normalized_allowed_tools_dict,
    parse_frontmatter_lenient,
)
from app.core.mcp_skill_resolution import resolve_skill_mcp_declarations
from app.core.user_settings_paths import skills_dir_path
from app.skills.loader import get_builtin_skills_dir


def _get_skills_dir() -> Path:
    """根据当前用户返回 skills 目录。"""
    return skills_dir_path()


def skill_dir_for_directory_name(directory_name: str) -> Optional[Path]:
    safe_directory_name = (directory_name or "").strip()
    if not safe_directory_name or ".." in safe_directory_name or "/" in safe_directory_name or "\\" in safe_directory_name:
        return None
    base = _get_skills_dir().resolve()
    d = (base / safe_directory_name).resolve()
    if d.is_dir() and str(d).startswith(str(base)) and (d / "SKILL.md").is_file():
        return d
    br = get_builtin_skills_dir()
    if not br.exists():
        return None
    br = br.resolve()
    d2 = (br / safe_directory_name).resolve()
    if d2.is_dir() and str(d2).startswith(str(br)) and (d2 / "SKILL.md").is_file():
        return d2
    return None


def read_skill_file(skill_dir: Path) -> tuple[Dict, str]:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.exists():
        return {}, ""
    content = skill_file.read_text(encoding="utf-8")
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            fm = parse_frontmatter_lenient(parts[1])
            return fm, parts[2].lstrip("\n")
    return {}, content


def write_skill_file(skill_dir: Path, frontmatter: Dict, body: str):
    skill_file = skill_dir / "SKILL.md"
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    skill_file.write_text(content, encoding="utf-8")


def skill_display_name_from_dir(skill_dir: Path, fallback_directory_name: str) -> str:
    try:
        fm, _ = read_skill_file(skill_dir)
        return str(fm.get("name") or fallback_directory_name).strip() or fallback_directory_name
    except Exception:
        return fallback_directory_name


def skill_item_from_skill_dir(skill_dir: Path) -> Optional[Dict[str, Any]]:
    """从单个 skill 目录解析一条技能清单项（与 load_skills_config 原逻辑一致）。"""
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None
    frontmatter = parse_frontmatter_lenient(parts[1])
    return {
        "directory_name": skill_dir.name,
        "name": frontmatter.get("name", skill_dir.name),
        "description": frontmatter.get("description", ""),
        "path": str(skill_dir),
        "allowed_tools": normalized_allowed_tools_dict(frontmatter),
    }


def load_skills_config() -> List[Dict[str, Any]]:
    """加载 skills 目录下所有 SKILL.md 的 frontmatter 作为配置列表。"""
    skills: List[Dict[str, Any]] = []
    for root in (_get_skills_dir(), get_builtin_skills_dir()):
        if not root.exists():
            continue
        for skill_dir in root.iterdir():
            if not skill_dir.is_dir():
                continue
            item = skill_item_from_skill_dir(skill_dir)
            if item is not None and not any(existing["directory_name"] == item["directory_name"] for existing in skills):
                skills.append(item)
    return skills


def validate_skill_tool_names(
    tool_names: Optional[List[str]],
) -> List[str]:
    names = [str(x).strip() for x in (tool_names or []) if str(x).strip()]
    if not names:
        return []
    resolved, missing = resolve_skill_mcp_declarations(names, load_mcp_config())
    if missing:
        raise HTTPException(status_code=400, detail=f"MCP Server 不存在: {', '.join(missing)}")
    return resolved


def get_mcp_servers_for_skill(directory_name: str) -> List[str]:
    d = skill_dir_for_directory_name(directory_name)
    if not d:
        return []
    fm, _ = read_skill_file(d)
    allowed = normalized_allowed_tools_dict(fm)
    ids = list(allowed.get("mcp") or []) + list(allowed.get("http_api") or [])
    if not ids:
        return []
    resolved, _missing = resolve_skill_mcp_declarations(ids, load_mcp_config())
    return resolved
