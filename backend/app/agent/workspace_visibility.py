"""Visibility and path rules for files exposed through workspace APIs/tools."""
from __future__ import annotations

import re


_INTERNAL_DIAGNOSTIC_FILES: set[str] = set()

_INTERNAL_DIAGNOSTIC_PREFIXES = (
    "memory/messages/",
)

_INTERNAL_SYSTEM_DIRS = {
    "memory",
    "checkpoints",
    "execution_logs",
    "logs",
    "runtime_logs",
    "traces",
    ".logs",
    ".runtime",
    ".internal",
}

_WINDOWS_ABSOLUTE_RE = re.compile(r"^[a-zA-Z]:/")


class WorkspacePathError(ValueError):
    """Raised when a workspace-relative path violates the public file contract."""

    def __init__(self, message: str, *, code: str = "invalid_path") -> None:
        super().__init__(message)
        self.code = code


def normalize_workspace_rel_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/").lstrip("/").rstrip("/")


def normalize_public_workspace_path(path: str, *, allow_empty: bool = False) -> str:
    """Normalize a user-visible workspace path or reject traversal/internal paths."""
    raw = str(path or "").strip().replace("\\", "/")
    if not raw:
        if allow_empty:
            return ""
        raise WorkspacePathError("path is required")
    if raw.startswith("/") or _WINDOWS_ABSOLUTE_RE.match(raw):
        raise WorkspacePathError("绝对路径不能通过文件 API 访问")
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts:
        if allow_empty:
            return ""
        raise WorkspacePathError("path is required")
    if any(part == ".." for part in parts):
        raise WorkspacePathError("路径不能包含 ..。")
    if parts[0] in _INTERNAL_SYSTEM_DIRS:
        raise WorkspacePathError(f"{parts[0]}/ 是内部系统目录，不能通过工作区文件 API 访问。", code="internal_system_path")
    return "/".join(parts)


def is_internal_system_workspace_path(path: str) -> bool:
    """Return True for top-level session-internal paths hidden from public workspace views."""
    rel = normalize_workspace_rel_path(path)
    first = rel.split("/", 1)[0] if rel else ""
    return first in _INTERNAL_SYSTEM_DIRS


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


def internal_system_path_error(path: str) -> str:
    rel = normalize_workspace_rel_path(path)
    return f"错误：{rel or path} 是内部系统目录，不能通过工作区文件工具访问。"
