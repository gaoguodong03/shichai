"""为 filesystem MCP 工具按会话做 path 校验与重写，避免重复提供 read_file。"""
import os
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from langchain.tools import Tool

from app.api.files import AGENT_OUTPUTS_DIR, WORKSPACES_SUBDIR

# MCP server 通常以 backend 为 cwd 启动，需传相对 backend 的路径才能解析到正确文件
_REL_PREFIX = os.path.relpath(Path(AGENT_OUTPUTS_DIR).resolve(), Path.cwd()) if Path(AGENT_OUTPUTS_DIR).exists() else "data/agent-outputs"
if _REL_PREFIX.startswith(".."):
    _REL_PREFIX = "data/agent-outputs"  # 兜底


def _path_arg_keys() -> List[str]:
    return ["path", "path_to_file", "pathToFile", "filename"]


def _normalize_path_for_session(path: str, session_id: str) -> str:
    """确保 path 落在 workspaces/{session_id}/ 下，并返回 MCP 可解析的路径（相对 backend）。

    兼容一些旧模板 / LLM 误用的调用方式，例如把
        '{"__arg1": "错误文字.md"}'
    整个 JSON 字符串塞到 path 里。
    此时应先解析 JSON，提取其中的 path 或 __arg1，再做 workspace 前缀拼接。
    """
    raw = (path or "").strip()
    # 若 path 看起来是 JSON，尝试从中提取真正的路径字段
    if raw.startswith("{") and raw.endswith("}"):
        try:
            data = json.loads(raw)
            extracted = str(data.get("path") or data.get("__arg1") or "").strip()
            if extracted:
                path = extracted
            else:
                path = raw
        except Exception:
            path = raw
    else:
        path = raw

    path = path.lstrip("/")
    if not path:
        return f"{_REL_PREFIX}/{WORKSPACES_SUBDIR}/{session_id}"
    # 已是 workspaces/{session_id}/ 形式
    prefix_ws = f"{WORKSPACES_SUBDIR}/{session_id}"
    if path.startswith(prefix_ws + "/") or path == prefix_ws:
        pass
    else:
        # 仅文件名或子路径，补全为当前会话 workspace
        path = f"{prefix_ws}/{path}" if path else prefix_ws
    # 供 MCP 解析：相对 backend 的路径
    if not path.startswith(_REL_PREFIX):
        path = f"{_REL_PREFIX}/{path}"
    return path


def _ensure_path_in_session(args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """若 args 中含 path 类参数，则限制在 workspaces/{session_id}/ 并重写为 MCP 可解析路径。"""
    out = dict(args)
    for key in _path_arg_keys():
        if key not in out:
            continue
        val = out[key]
        if isinstance(val, str):
            out[key] = _normalize_path_for_session(val, session_id)
        break
    return out


def wrap_filesystem_tool_for_session(tool: Tool, session_id: str) -> Tool:
    """包装 filesystem MCP 工具：调用前将 path 限制并重写为当前会话 workspace。"""
    orig_func: Callable[..., str] = tool.func

    def wrapped_func(*args: Any, **kwargs: Any) -> str:
        # LangChain Tool 可能用 *args 或 **kwargs 传参
        if kwargs:
            kwargs = _ensure_path_in_session(kwargs, session_id)
        elif args and isinstance(args[0], dict):
            kwargs = _ensure_path_in_session(dict(args[0]), session_id)
            args = ()
        elif args and isinstance(args[0], str):
            kwargs = _ensure_path_in_session({"path": args[0]}, session_id)
            args = ()
        return orig_func(*args, **kwargs)

    return Tool(
        name=tool.name,
        description=tool.description,
        func=wrapped_func,
    )


def wrap_filesystem_tools(tools: List[Tool], session_id: Optional[str]) -> List[Tool]:
    """对工具列表中所有 filesystem_ 开头的工具按 session_id 包装；session_id 为空则不包装。"""
    if not session_id:
        return tools
    out = []
    for t in tools:
        if t.name.startswith("filesystem_"):
            out.append(wrap_filesystem_tool_for_session(t, session_id))
        else:
            out.append(t)
    return out
