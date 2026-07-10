"""为 filesystem MCP 工具按会话做 path 校验与重写，使 path 限定在当前会话工作区 {session_id}/workspace/ 下。"""
import os
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.agent.tool_spec import ToolSpec
from app.agent.read_path_utils import looks_like_url_or_remote_path
from app.agent.path_whitelist_guard import ensure_within_root, normalize_rel_path
from app.api.files import get_agent_outputs_root


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
    """确保 path 落在 {session_id}/workspace/ 下，并返回 MCP 可解析的路径（相对 backend）。

    path 必须是工具 schema 中的命名参数值，不能是 JSON 包装字符串。
    """
    raw = (path or "").strip()
    if raw.startswith("{") and raw.endswith("}"):
        raise ValueError("path 不能是 JSON 包装字符串；请按工具 schema 传 path 参数。")
    path = raw

    rel_prefix = _agent_outputs_rel_prefix()
    path = path.lstrip("/")
    if not path:
        return f"{rel_prefix}/{session_id}/workspace"
    # 已是 {session_id}/workspace 形式
    prefix_ws = f"{session_id}/workspace"
    if path.startswith(prefix_ws + "/") or path == prefix_ws:
        pass
    else:
        # 仅文件名或子路径，补全为当前会话 workspace
        path = f"{prefix_ws}/{normalize_rel_path(path)}" if path else prefix_ws
    # 使用 canonical path 防止 ../../ 与符号链接越界
    root = get_agent_outputs_root().resolve()
    target = (root / path).resolve()
    session_root = (root / session_id / "workspace").resolve()
    ensure_within_root(target, session_root)
    path = str(target.relative_to(root)).replace("\\", "/")
    # 供 MCP 解析：相对 backend 的路径
    if not path.startswith(rel_prefix):
        path = f"{rel_prefix}/{path}"
    return path


def _ensure_path_in_session(args: Dict[str, Any], session_id: str) -> Dict[str, Any]:
    """若 args 中含 path 类参数，则限制在 {session_id}/workspace/ 并重写为 MCP 可解析路径。"""
    out = dict(args)
    for key in _path_arg_keys():
        if key not in out:
            continue
        val = out[key]
        if isinstance(val, str):
            out[key] = _normalize_path_for_session(val, session_id)
        break
    return out


def wrap_filesystem_tool_for_session(tool: ToolSpec, session_id: str) -> ToolSpec:
    """包装 filesystem MCP 工具：调用前将 path 限制并重写为当前会话 workspace。包装后的 func 保持与 orig 一致（异步则仍为异步），避免 coroutine 未被 await。"""
    orig_func = getattr(tool, "func", None)
    if not callable(orig_func):
        return tool

    async def wrapped_func(*args: Any, **kwargs: Any) -> str:
        if args:
            return "错误：filesystem 工具必须按 schema 传 path 参数，不接受位置参数。"
        peek = ""
        if kwargs:
            for key in _path_arg_keys():
                v = kwargs.get(key)
                if isinstance(v, str) and v.strip():
                    peek = v.strip()
                    break
        if peek and looks_like_url_or_remote_path(peek):
            return (
                "错误：path 不能为网页链接，请使用当前会话工作区内的相对路径"
                "（例如 github-weekly-snapshot.md）。"
            )
        if kwargs:
            kwargs = _ensure_path_in_session(kwargs, session_id)
        result = orig_func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result

    return ToolSpec.from_function(
        name=getattr(tool, "name", ""),
        description=getattr(tool, "description", ""),
        func=wrapped_func,
        args_schema=getattr(tool, "args_schema", None),
    )


def wrap_filesystem_tools(tools: List[ToolSpec], session_id: Optional[str]) -> List[ToolSpec]:
    """对工具列表中所有 filesystem_ 开头的工具按 session_id 包装，path 限定到当前会话工作区；session_id 为空则不包装。"""
    if not session_id:
        return tools
    out = []
    for t in tools:
        if getattr(t, "name", "").startswith("filesystem_"):
            out.append(wrap_filesystem_tool_for_session(t, session_id))
        else:
            out.append(t)
    return out
