"""写入当前会话工作区文件工具 — 经 OpenSandbox 挂载写入 /workspace。"""
import json
import re

from pydantic import BaseModel, Field

from app.agent.tool_spec import ToolSpec
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.agent.workspace_visibility import WorkspacePathError, internal_system_path_error, normalize_public_workspace_path
from app.api.files import get_workspace_root
from app.core.security import get_current_user

_DSML_TOOL_CALL_RE = re.compile(r"<｜｜DSML｜｜(?:tool_calls|invoke|parameter)\b")
_PLAIN_TOOL_CALL_RE = re.compile(
    r"^\s*(?:write_workspace_file|edit_workspace_file|rename_workspace_file|list_workspace_directory|read_workspace_file|read_file)\s*\(",
    re.S,
)


class WriteWorkspaceFileInput(BaseModel):
    """write_workspace_file 的入参。一次调用必须同时传 path 和 content。"""

    path: str = Field(
        description=(
            "工作区内相对路径。项目生成的新文件名统一使用 文件名-当前文件时间戳.扩展名，"
            "例如 notes/report-2026070422145700.md；工具按传入 path 原样写入，不替换或校验时间戳。"
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
            "或新建符合 文件名-当前文件时间戳.扩展名 的新文件。"
        ),
    )


def _normalize_path(path_or_input) -> str:
    if path_or_input is None:
        return ""
    s = str(path_or_input).strip()
    if not s:
        return ""
    if s.startswith("{") and s.endswith("}"):
        raise ValueError("path 不能是 JSON 包装字符串；请按工具 schema 传 path 参数。")
    return s


def _normalize_content(content_or_input) -> str:
    if content_or_input is not None and str(content_or_input).strip():
        return str(content_or_input)
    return ""


def _normalize_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _looks_like_model_tool_call_payload(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    if _DSML_TOOL_CALL_RE.search(text):
        return True
    if _PLAIN_TOOL_CALL_RE.match(text):
        return True
    if text.startswith("{") and text.endswith("}"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return False
        if not isinstance(payload, dict):
            return False
        action = str(payload.get("action") or "").strip().lower()
        has_tool_name = bool(payload.get("tool") or payload.get("name"))
        return action == "tool_call" and has_tool_name
    return False


def create_write_workspace_file_tool(workspace_id: str) -> ToolSpec:
    """
    新建写入当前会话 workspace 文件的工具。
    workspace_id 为 session_id 或 group_session_id；写入经 SandboxService + OpenSandbox。
    """

    async def _write_to_workspace_file(path: str, content: str = "", overwrite: bool = False, **kwargs) -> str:
        try:
            path_value = _normalize_path(path) or _normalize_path(kwargs.get("path")) or ""
        except ValueError as exc:
            return f"错误：{exc}"
        content_value = _normalize_content(content)
        allow_overwrite = _normalize_bool(overwrite)
        path_value = path_value.strip()
        if not path_value:
            return "错误：write_workspace_file 需要提供 path（workspace 内相对路径，例如 notes/report-2026070422145700.md）。"
        if not content_value:
            return (
                "错误：content 为空。未传 content 时系统会用本条回复的正文作为要保存的内容；若本条回复无正文，请在本条中写出要保存的内容后重试，或调用时显式传入 content。"
            )
        if _looks_like_model_tool_call_payload(content_value):
            return (
                "错误：content 不是可保存的最终正文，已拒绝写入工作区。"
                "请把要保存的完整正文传给 content。"
            )
        try:
            normalized = normalize_public_workspace_path(path_value)
        except WorkspacePathError as exc:
            if exc.code == "internal_system_path":
                return internal_system_path_error(path_value)
            return f"错误：{exc}"
        ws_root = get_workspace_root(workspace_id)
        target = (ws_root / normalized).resolve()
        try:
            target.relative_to(ws_root.resolve())
        except ValueError:
            return f"错误：路径 {path_value} 不在当前工作区内。"
        if target.exists() and not allow_overwrite:
            return (
                f"错误：文件已存在：{normalized}。为避免覆盖已有正文或工作区产物，"
                "write_workspace_file 默认不覆盖同名文件。请改用符合 文件名-当前文件时间戳.扩展名 的新文件名，"
                "或在确需覆盖时显式传入 overwrite=true。"
            )
        svc = get_shared_sandbox_service()
        try:
            user_id = get_current_user().user_id
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
            "- path: 工作区内相对路径。项目生成的新文件名统一使用 文件名-当前文件时间戳.扩展名，"
            "例如 'notes/report-2026070422145700.md'；工具按传入 path 原样写入，不替换或校验时间戳。\n"
            "- content: 要保存的完整文本内容。"
        ),
        coroutine=_write_to_workspace_file,
        args_schema=WriteWorkspaceFileInput,
    )
