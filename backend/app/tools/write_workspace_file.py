"""写入当前会话工作区文件工具 — 经 OpenSandbox 挂载写入 /workspace。"""
import json
import re
from datetime import datetime

from pydantic import BaseModel, Field

from app.agent.tool_spec import ToolSpec
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.api.files import get_workspace_root
from app.core.security import get_current_user

_FINAL_FILENAME_TIMESTAMP_RE = re.compile(r"(?<=-)(?:19|20)\d{12}(?:\d{2})?(?=\.[^/.]+$)")


class WriteWorkspaceFileInput(BaseModel):
    """write_workspace_file 的入参。一次调用必须同时传 path 和 content。"""

    path: str = Field(
        description=(
            "工作区内相对路径。项目生成的新文件名统一使用 文件名-YYYYMMDDHHMMSS00.扩展名，"
            "例如 notes/report-<时间戳>.md；工具会把 <时间戳> 或文件名末尾已有时间戳替换为服务器当前时间。"
            "只有用户明确指定已有路径或固定文件名时才按用户原文使用。"
        )
    )
    content: str = Field(
        default="",
        description="要保存的完整文本内容；若为空则工具会报错并提示重新传入。与 path 在同一次调用中一起传入。",
    )
    overwrite: bool = Field(
        default=False,
        description=(
            "是否允许覆盖同名文件。默认 false；需要修改已有文件时优先使用 edit_workspace_file，"
            "或新建符合 文件名-YYYYMMDDHHMMSS00.扩展名 的新文件。"
        ),
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


def _normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _current_workspace_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S") + "00"


def _normalize_generated_timestamp(path: str) -> str:
    timestamp = _current_workspace_timestamp()
    normalized = path.replace("-<时间戳>.", f"-{timestamp}.")
    return _FINAL_FILENAME_TIMESTAMP_RE.sub(timestamp, normalized)


def create_write_workspace_file_tool(workspace_id: str) -> ToolSpec:
    """
    新建写入当前会话 workspace 文件的工具。
    workspace_id 为 session_id 或 group_session_id；写入经 SandboxService + OpenSandbox。
    """

    async def _write_to_workspace_file(path: str, content: str = "", overwrite: bool = False, **kwargs) -> str:
        path_value = _normalize_path(path) or _normalize_path(kwargs.get("path")) or _normalize_path(kwargs.get("__arg1")) or ""
        content_value = _normalize_content(content, **kwargs)
        allow_overwrite = _normalize_bool(overwrite) or _normalize_bool(kwargs.get("overwrite"))
        path_value = path_value.strip()
        if not path_value:
            return "错误：write_workspace_file 需要提供 path（workspace 内相对路径，例如 notes/report-<时间戳>.md）。"
        if not content_value:
            return (
                "错误：content 为空。未传 content 时系统会用本条回复的正文作为要保存的内容；若本条回复无正文，请在本条中写出要保存的内容后重试，或调用时显式传入 content。"
            )
        normalized = _normalize_generated_timestamp(path_value.strip("/").replace("\\", "/"))
        if ".." in normalized:
            return "错误：路径不能包含 ..。"
        ws_root = get_workspace_root(workspace_id)
        target = (ws_root / normalized).resolve()
        if not str(target).startswith(str(ws_root.resolve())):
            return f"错误：路径 {path_value} 不在当前工作区内。"
        if target.exists() and not allow_overwrite:
            return (
                f"错误：文件已存在：{normalized}。为避免覆盖已有正文或工作区产物，"
                "write_workspace_file 默认不覆盖同名文件。请改用符合 文件名-YYYYMMDDHHMMSS00.扩展名 的新文件名，"
                "或在确需覆盖时显式传入 overwrite=true。"
            )
        svc = get_shared_sandbox_service()
        try:
            user_id = get_current_user().username
            await svc.write_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=normalized,
                content=str(content_value),
            )
        except Exception as e:
            return f"错误：写入工作区文件失败 - {e}"
        return f"已写入当前 Chat 工作区文件：{normalized}"

    return ToolSpec.from_function(
        name="write_workspace_file",
        description=(
            "将文本内容写入当前 Chat 对应的工作区（workspace）中的文件（经 OpenSandbox /workspace）。\n"
            "- path: 工作区内相对路径。项目生成的新文件名统一使用 文件名-YYYYMMDDHHMMSS00.扩展名，"
            "例如 'notes/report-<时间戳>.md'；工具会把 <时间戳> 或文件名末尾已有时间戳替换为服务器当前时间。"
            "用户明确指定已有路径或固定文件名时按用户原文使用。\n"
            "- content: 要保存的完整文本内容。"
        ),
        coroutine=_write_to_workspace_file,
        args_schema=WriteWorkspaceFileInput,
    )
