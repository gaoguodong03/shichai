"""读取引用文件工具 - 支持用户消息中的【文件引用：path】；按会话隔离时仅允许 workspaces/{session_id}/ 下"""
import json
from pathlib import Path
from typing import Optional

try:
    from langchain.tools import Tool
except Exception:
    class Tool:  # type: ignore
        def __init__(self, name: str, description: str, func):
            self.name = name
            self.description = description
            self.func = func

from app.api.files import WORKSPACES_SUBDIR, get_agent_outputs_root


def _normalize_path(path_or_input) -> str:
    """从多种输入格式提取 path 字符串。兼容 arun(tool_input) 传入的 JSON 字符串。"""
    if path_or_input is None:
        return ""
    s = str(path_or_input).strip()
    if not s:
        return ""
    # arun 可能传入 JSON 字符串 '{"__arg1": "test.docx"}'，需解析
    if s.startswith("{"):
        try:
            data = json.loads(s)
            return str(data.get("path") or data.get("__arg1") or "")
        except json.JSONDecodeError:
            pass
    return s


def _read_file_content(path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> str:
    """读取文件。path 为相对当前用户 agent 输出根的路径，或 workspace 内相对路径。
    当 session_id 给定时，仅允许读取 workspaces/{session_id}/ 下的文件。"""
    path = _normalize_path(path) or _normalize_path(kwargs.get("__arg1")) or _normalize_path(kwargs.get("path"))
    root = get_agent_outputs_root().resolve()
    root.mkdir(parents=True, exist_ok=True)
    normalized = (path or "").strip("/").replace("..", "")
    if not normalized:
        return "错误：未提供文件路径。"
    if session_id:
        # 按会话隔离：必须落在 workspaces/{session_id}/ 下
        prefix = f"{WORKSPACES_SUBDIR}/{session_id}"
        if not normalized.startswith(prefix + "/") and normalized != prefix:
            # 若用户传的是 workspace 内相对路径（如 report.md），补全前缀
            normalized = f"{prefix}/{normalized}" if normalized else prefix
        full = (root / normalized).resolve()
        ws_root = (root / WORKSPACES_SUBDIR / session_id).resolve()
        if not str(full).startswith(str(ws_root)):
            return f"错误：仅允许读取当前会话工作区内的文件（workspaces/{session_id}/...）。"
    else:
        full = (root / normalized).resolve()
        if not str(full).startswith(str(root)):
            return f"错误：路径 {path} 不在允许的目录内。"
    if not full.exists():
        return f"错误：文件不存在：{path}"
    if full.is_dir():
        return f"错误：{path} 是目录，无法读取。"
    try:
        return full.read_text(encoding="utf-8")
    except Exception as e:
        return f"错误：读取文件失败 - {e}"


def create_read_file_tool(session_id: Optional[str] = None):
    """创建读取引用文件工具。session_id 给定时仅允许读取该会话 workspace 内文件。"""
    def _func(path: Optional[str] = None, **kwargs) -> str:
        return _read_file_content(path=path, session_id=session_id, **kwargs)

    return Tool(
        name="read_file",
        description=(
            "读取用户引用的文件内容。当用户消息中出现【文件引用：path】时，必须先用此工具读取该文件。"
            "path 为工作区内相对路径（如 report.md 或 notes/report.txt）。仅能读取当前会话工作区内的文件。"
        ),
        func=_func,
    )
