"""Skill frontmatter and allowed-tools helpers."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel

from app.api.settings_mcp import load_mcp_config
from app.core.settings_references import (
    merge_reference_rows_for_ids as _merge_reference_rows_for_ids,
    normalize_reference_rows as _normalize_reference_rows,
)


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
AUTO_TOOLS_FM_KEY = "auto-tools"
REFERENCE_LABELS_FM_KEY = "reference-labels"


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


def mcp_ids_from_frontmatter(fm: Dict[str, Any]) -> List[str]:
    auto = fm.get(AUTO_TOOLS_FM_KEY)
    if isinstance(auto, dict) and "mcp" in auto:
        m = auto.get("mcp")
        if isinstance(m, list):
            return list(dict.fromkeys(str(x).strip() for x in m if str(x).strip()))
        return []
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    if isinstance(at, dict) and "mcp" in at:
        m = at.get("mcp")
        if isinstance(m, list):
            return list(dict.fromkeys(str(x).strip() for x in m if str(x).strip()))
        return []
    legacy = fm.get("mcp_server_ids")
    if isinstance(legacy, list):
        return list(dict.fromkeys(str(x).strip() for x in legacy if str(x).strip()))
    return []


def python_doc_from_allowed_tools(fm: Dict[str, Any]) -> str:
    at = fm.get(ALLOWED_TOOLS_FM_KEY)
    auto = fm.get(AUTO_TOOLS_FM_KEY)
    py: Any = ""
    if isinstance(auto, dict):
        py = auto.get("python")
    if (py is None or py == "") and isinstance(at, dict):
        py = at.get("python")
    if isinstance(py, str):
        return py
    if py is None:
        return ""
    if isinstance(py, list):
        return "\n".join(str(x).strip() for x in py if str(x).strip())
    return str(py)


def mcp_reference_rows_from_frontmatter(fm: Dict[str, Any]) -> List[Dict[str, str]]:
    labels = fm.get(REFERENCE_LABELS_FM_KEY)
    if isinstance(labels, dict):
        rows = _normalize_reference_rows(labels.get("mcp"))
        if rows:
            return rows
    for source in (fm.get(AUTO_TOOLS_FM_KEY), fm.get(ALLOWED_TOOLS_FM_KEY)):
        if isinstance(source, dict):
            rows = _normalize_reference_rows(source.get("mcp_refs"))
            if rows:
                return rows
    return []


def mcp_name_lookup() -> Dict[str, str]:
    try:
        return {
            str(row.get("id") or "").strip(): str(row.get("name") or "").strip()
            for row in load_mcp_config()
            if str(row.get("id") or "").strip()
        }
    except Exception:
        return {}


def runtime_tools_only(normalized: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "mcp": list(normalized.get("mcp") or []),
        "python": str(normalized.get("python") or ""),
    }


def normalized_allowed_tools_dict(fm: Dict[str, Any]) -> Dict[str, Any]:
    """从当前 frontmatter 归一化 allowed-tools（合并旧 mcp_server_ids）。"""
    mcp_ids = list(mcp_ids_from_frontmatter(fm))
    return {
        "mcp": mcp_ids,
        "python": python_doc_from_allowed_tools(fm),
        "mcp_refs": _merge_reference_rows_for_ids(
            mcp_ids,
            mcp_reference_rows_from_frontmatter(fm),
            mcp_name_lookup(),
        ),
    }


def normalize_allowed_tools_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    """校验并归一化 API 传入的 allowed_tools 体。"""
    mcp_raw = raw.get("mcp")
    mcp_list = list(dict.fromkeys(str(x).strip() for x in (mcp_raw if isinstance(mcp_raw, list) else []) if str(x).strip()))
    py = raw.get("python", "")
    py_str = py if isinstance(py, str) else ("" if py is None else str(py))
    return {
        "mcp": mcp_list,
        "python": py_str,
        "mcp_refs": _merge_reference_rows_for_ids(
            mcp_list,
            raw.get("mcp_refs"),
            mcp_name_lookup(),
        ),
    }


def sanitize_skill_frontmatter_for_write(fm: Dict[str, Any]) -> None:
    """写入前：保证 auto-tools/allowed-tools 存在并剥离已废弃键。"""
    normalized = normalized_allowed_tools_dict(fm)
    runtime_tools = runtime_tools_only(normalized)
    fm[AUTO_TOOLS_FM_KEY] = runtime_tools
    fm[ALLOWED_TOOLS_FM_KEY] = runtime_tools
    ref_labels = fm.get(REFERENCE_LABELS_FM_KEY) if isinstance(fm.get(REFERENCE_LABELS_FM_KEY), dict) else {}
    ref_labels = dict(ref_labels)
    ref_labels["mcp"] = normalized.get("mcp_refs") or []
    fm[REFERENCE_LABELS_FM_KEY] = ref_labels
    for k in ("enabled", "write_mode", "mcp_server_ids", "source", "url"):
        fm.pop(k, None)
