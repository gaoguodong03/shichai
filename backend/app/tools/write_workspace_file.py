"""写入当前会话工作区文件工具 — 经 OpenSandbox 挂载写入 /workspace。"""
import json

from pydantic import BaseModel, Field

from app.agent.tool_spec import ToolSpec
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.api.files import get_workspace_root
from app.core.security import get_current_user


class WriteWorkspaceFileInput(BaseModel):
    """write_workspace_file 的入参。一次调用必须同时传 path 和 content。"""

    path: str = Field(description="工作区内相对路径，例如 notes/report.md 或 workspace-write-test.txt")
    content: str = Field(
        default="",
        description="要保存的完整文本内容；若为空则工具会报错并提示重新传入。与 path 在同一次调用中一起传入。",
    )


def _normalize_path(path_or_input) -> str:
    if path_or_input is None:
        return ""
    if isinstance(path_or_input, dict):
        return str(path_or_input.get("path") or path_or_input.get("__arg1") or "").strip()
    s = str(path_or_input).strip()
    if not s:
        return ""
    if s.startswith("{"):
        try:
            data = json.loads(s)
            return str(data.get("path") or data.get("__arg1") or "")
        except json.JSONDecodeError:
            pass
    return s


def _normalize_content(content_or_input, **kwargs) -> str:
    if content_or_input is not None and str(content_or_input).strip():
        return str(content_or_input)
    for key in ("content", "__arg2", "text", "body"):
        val = kwargs.get(key)
        if val is not None and str(val).strip():
            return str(val)
    return ""


def create_write_workspace_file_tool(workspace_id: str) -> ToolSpec:
    """
    创建写入当前会话 workspace 文件的工具。
    workspace_id 为 session_id 或 group_session_id；写入经 SandboxService + OpenSandbox。
    """

    async def _write_to_workspace_file(path: str, content: str = "", **kwargs) -> str:
        path_value = _normalize_path(path) or _normalize_path(kwargs.get("path")) or _normalize_path(kwargs.get("__arg1")) or ""
        content_value = _normalize_content(content, **kwargs)
        path_value = path_value.strip()
        if not path_value:
            return "错误：write_workspace_file 需要提供 path（workspace 内相对路径，例如 notes/report.md）。"
        if not content_value:
            return (
                "错误：content 为空。未传 content 时系统会用本条回复的正文作为要保存的内容；若本条回复无正文，请在本条中写出要保存的内容后重试，或调用时显式传入 content。"
            )
        normalized = path_value.strip("/").replace("\\", "/")
        # Backward compatibility for old skill prompts:
        # under user-single-sandbox layout, scripts config lives at session root.
        if normalized in {"scripts/config.json"} or normalized.endswith("/scripts/config.json"):
            normalized = "config.json"
        if ".." in normalized:
            return "错误：路径不能包含 ..。"
        ws_root = get_workspace_root(workspace_id)
        target = (ws_root / normalized).resolve()
        if not str(target).startswith(str(ws_root.resolve())):
            return f"错误：路径 {path_value} 不在当前工作区内。"
        svc = get_shared_sandbox_service()
        try:
            user_id = get_current_user().username
            await svc.write_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=normalized,
                content=str(content_value),
                tool_call_id=f"write:{normalized}",
            )
        except Exception as e:
            return f"错误：写入工作区文件失败 - {e}"
        return f"已写入当前 Chat 工作区文件：{normalized}"

    return ToolSpec.from_function(
        name="write_workspace_file",
        description=(
            "将文本内容写入当前 Chat 对应的工作区（workspace）中的文件（经 OpenSandbox /workspace）。\n"
            "- path: 工作区内相对路径，例如 'notes/report.md'。\n"
            "- content: 要保存的完整文本内容。"
        ),
        coroutine=_write_to_workspace_file,
        args_schema=WriteWorkspaceFileInput,
    )
