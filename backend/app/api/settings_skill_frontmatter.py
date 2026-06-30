"""Skill frontmatter and allowed-tools helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel

class SkillCreate(BaseModel):
    """新建 Skill 请求"""

    name: Optional[str] = None
    description: Optional[str] = None


class SkillUpdate(BaseModel):
    """更新 Skill 请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    body: Optional[str] = None
    allowed_tools: Optional[Dict[str, Any]] = None


ALLOWED_TOOLS_FM_KEY = "allowed-tools"


def parse_frontmatter_lenient(frontmatter_text: str) -> Dict[str, Any]:
    """解析 frontmatter：优先 YAML，失败时回退到宽容 key:value 解析。"""
    try:
        parsed = yaml.safe_load(frontmatter_text) or {}
        if isinstance(parsed, dict):
            return parsed
        return {}
    except Exception:
        result: Dict[str, Any] = {}
        for raw in (frontmatter_text or "").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or ":" not in line:
                continue
            k, v = line.split(":", 1)
            key = (k or "").strip()
            if not key:
                continue
            val = (v or "").strip()
            if val.lower() == "true":
                result[key] = True
            elif val.lower() == "false":
                result[key] = False
            else:
                result[key] = val.strip("'\"")
        return result


def _list_tool_names(raw: Any) -> List[str]:
    if not isinstance(raw, list):
        return []
    return list(dict.fromkeys(str(x).strip() for x in raw if str(x).strip()))


def _http_api_names_from_section(section: Any) -> List[str]:
    if not isinstance(section, dict):
        return []
    return _list_tool_names(section.get("http_api") or section.get("http-api"))


def tool_names_from_frontmatter(fm: Dict[str, Any]) -> List[str]:
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    if isinstance(at, dict):
        names = _list_tool_names(at.get("mcp")) + _http_api_names_from_section(at)
        return list(dict.fromkeys(names))
    return []


def python_doc_from_allowed_tools(fm: Dict[str, Any]) -> str:
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    py: Any = ""
    if isinstance(at, dict):
        py = at.get("python")
    if isinstance(py, str):
        return py
    if py is None:
        return ""
    if isinstance(py, list):
        return "\n".join(str(x).strip() for x in py if str(x).strip())
    return str(py)


def runtime_tools_only(normalized: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mcp": list(normalized.get("mcp") or []),
        "http_api": list(normalized.get("http_api") or []),
        "python": str(normalized.get("python") or ""),
    }


def normalized_allowed_tools_dict(fm: Dict[str, Any]) -> Dict[str, Any]:
    """从当前 frontmatter 归一化 allowed-tools。"""
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    section = at if isinstance(at, dict) else {}
    return {
        "mcp": _list_tool_names(section.get("mcp")),
        "http_api": _http_api_names_from_section(section),
        "python": python_doc_from_allowed_tools(fm),
    }


def normalize_allowed_tools_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """校验并归一化 API 传入的 allowed_tools 体。"""
    mcp_raw = raw.get("mcp")
    mcp_list = list(dict.fromkeys(str(x).strip() for x in (mcp_raw if isinstance(mcp_raw, list) else []) if str(x).strip()))
    http_raw = raw.get("http_api") or raw.get("http-api")
    http_api_list = _list_tool_names(http_raw)
    py = raw.get("python", "")
    py_str = py if isinstance(py, str) else ("" if py is None else str(py))
    return {
        "mcp": mcp_list,
        "http_api": http_api_list,
        "python": py_str,
    }


def sanitize_skill_frontmatter_for_write(fm: Dict[str, Any]) -> None:
    """写入前：只保留 Skill 资源契约字段。"""
    normalized = normalized_allowed_tools_dict(fm)
    runtime_tools = runtime_tools_only(normalized)
    clean = {
        "name": str(fm.get("name") or "").strip(),
        "description": str(fm.get("description") or "").strip(),
        ALLOWED_TOOLS_FM_KEY: runtime_tools,
    }
    fm.clear()
    fm.update(clean)
