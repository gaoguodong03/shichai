"""Visibility rules for files exposed to agent workspace tools."""
from __future__ import annotations


_INTERNAL_DIAGNOSTIC_FILES: set[str] = set()

_INTERNAL_DIAGNOSTIC_PREFIXES = (
    "memory/messages/",
)


def normalize_workspace_rel_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("/").rstrip("/")


def is_internal_diagnostic_workspace_path(path: str) -> bool:
    rel = normalize_workspace_rel_path(path)
    if not rel:
        return False
    if rel in _INTERNAL_DIAGNOSTIC_FILES:
        return True
    return any(rel.startswith(prefix) for prefix in _INTERNAL_DIAGNOSTIC_PREFIXES)


def internal_diagnostic_path_error(path: str) -> str:
    rel = normalize_workspace_rel_path(path)
    return (
        f"错误：{rel or path} 是平台内部排障日志，不作为专家工作区输入。"
        "请读取用户明确提供的工作区文件；调度任务会由平台直接放在本轮提示词中。"
    )
