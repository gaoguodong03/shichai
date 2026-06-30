"""Skill id -> stable model function names for run_skill_script_* tools."""
from __future__ import annotations

import hashlib
import re

_TOOL_NAME_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def build_skill_script_tool_name(directory_name: str) -> str:
    """构造符合工具命名约束的 run_skill_script 工具名。

    部分模型供应商要求 function.name 严格匹配 ^[a-zA-Z0-9_\\.-]+$。
    对包含中文/空格等字符的 directory_name，需要做安全化，否则会在请求阶段被拒绝。
    """
    raw = str(directory_name or "").strip()
    if not raw:
        return "run_skill_script_default"
    sanitized = _TOOL_NAME_INVALID_CHARS_RE.sub("_", raw).strip("_.-")
    if not sanitized:
        sanitized = "skill"
    if sanitized != raw:
        suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        sanitized = f"{sanitized}_{suffix}"
    return f"run_skill_script_{sanitized}"
