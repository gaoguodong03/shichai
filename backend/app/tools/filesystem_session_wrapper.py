"""为 filesystem / file-reader MCP 工具按会话做 path 校验与重写，使 path 限定在当前会话工作区 workspaces/{session_id}/ 下。"""
import os
import json
import asyncio
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    from langchain.tools import Tool
except Exception:
    class Tool:  # type: ignore
        def __init__(self, name: str, description: str, func):
            self.name = name
            self.description = description
            self.func = func

from app.api.files import WORKSPACES_SUBDIR, get_agent_outputs_root


def _agent_outputs_rel_prefix() -> str:
    """当前用户 agent 输出根目录相对于 backend 目录的路径（供 MCP 传 path 用）。"""
    root = get_agent_outputs_root().resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    backend_root = Path(__file__).resolve().parents[2]
    rel = os.path.relpath(root, backend_root)
    if rel.startswith(".."):
        raise RuntimeError(f"agent_outputs 目录必须位于 backend 目录下，当前为: {root}")
    return rel.replace("\\", "/")


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

    rel_prefix = _agent_outputs_rel_prefix()
    path = path.lstrip("/")
    if not path:
        return f"{rel_prefix}/{WORKSPACES_SUBDIR}/{session_id}"
    # 已是 workspaces/{session_id}/ 形式
    prefix_ws = f"{WORKSPACES_SUBDIR}/{session_id}"
    if path.startswith(prefix_ws + "/") or path == prefix_ws:
        pass
    else:
        # 仅文件名或子路径，补全为当前会话 workspace
        path = f"{prefix_ws}/{path}" if path else prefix_ws
    # 供 MCP 解析：相对 backend 的路径
    if not path.startswith(rel_prefix):
        path = f"{rel_prefix}/{path}"
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
    """包装 filesystem MCP 工具：调用前将 path 限制并重写为当前会话 workspace。包装后的 func 保持与 orig 一致（异步则仍为异步），避免 coroutine 未被 await。"""
    orig_func = getattr(tool, "func", None)
    if not callable(orig_func):
        return tool

    async def wrapped_func(*args: Any, **kwargs: Any) -> str:
        # LangChain Tool 可能用 *args 或 **kwargs 传参
        if kwargs:
            kwargs = _ensure_path_in_session(kwargs, session_id)
        elif args and isinstance(args[0], dict):
            kwargs = _ensure_path_in_session(dict(args[0]), session_id)
            args = ()
        elif args and isinstance(args[0], str):
            kwargs = _ensure_path_in_session({"path": args[0]}, session_id)
            args = ()
        result = orig_func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    return Tool(
        name=tool.name,
        description=tool.description,
        func=wrapped_func,
    )


def wrap_filesystem_tools(tools: List[Tool], session_id: Optional[str]) -> List[Tool]:
    """对工具列表中所有 filesystem_ 或 file-reader_ 开头的工具按 session_id 包装，path 限定到当前会话工作区；session_id 为空则不包装。"""
    if not session_id:
        return tools
    out = []
    for t in tools:
        if getattr(t, "name", "").startswith("filesystem_") or getattr(t, "name", "").startswith("file-reader_"):
            out.append(wrap_filesystem_tool_for_session(t, session_id))
        else:
            out.append(t)
    return out
