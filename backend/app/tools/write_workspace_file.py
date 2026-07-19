"""写入当前会话工作区文件工具 — 经 OpenSandbox 挂载写入 /workspace。"""
import json
import logging
import re

from pydantic import BaseModel, Field

from app.agent.platform_prompts import render_platform_prompt
from app.agent.tool_spec import ToolSpec
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.agent.workspace_visibility import WorkspacePathError, internal_system_path_error, normalize_public_workspace_path
from app.api.files import get_workspace_root
from app.core.security import get_current_user

logger = logging.getLogger(__name__)

_DSML_TOOL_CALL_RE = re.compile(r"<｜｜DSML｜｜(?:tool_calls|invoke|parameter)\b")
_PLAIN_TOOL_CALL_RE = re.compile(
    r"^\s*(?:write_workspace_file|edit_workspace_file|rename_workspace_file|list_workspace_directory|read_workspace_file|read_file)\s*\(",
    re.S,
)


class WriteWorkspaceFileInput(BaseModel):
    """write_workspace_file 的入参。一次调用必须同时传 path 和 content。"""

    path: str = Field(description=render_platform_prompt("tool.schema.write_workspace_file.path.v1", {}))
    content: str = Field(
        description=render_platform_prompt("tool.schema.write_workspace_file.content.v1", {}),
    )
    overwrite: bool = Field(
        default=False,
        description=render_platform_prompt("tool.schema.write_workspace_file.overwrite.v1", {}),
    )


def _normalize_path(path_or_input) -> str:
    if path_or_input is None:
        return ""
    s = str(path_or_input).strip()
    if not s:
        return ""
    if s.startswith("{") and s.endswith("}"):
        raise ValueError(render_platform_prompt("workspace.write_file.json_wrapped_path_error.v1", {}))
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


def _checkpoint_workspace_write(workspace_id: str) -> None:
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(workspace_id, trigger="workspace_changed", force=True)
    except Exception:
        logger.warning("workspace checkpoint failed after write_workspace_file: %s", workspace_id, exc_info=True)


def create_write_workspace_file_tool(workspace_id: str) -> ToolSpec:
    """
    新建写入当前会话 workspace 文件的工具。
    workspace_id 为 session_id 或 group_session_id；写入经 SandboxService + OpenSandbox。
    """

    async def _write_to_workspace_file(path: str, content: str = "", overwrite: bool = False, **kwargs) -> str:
        try:
            path_value = _normalize_path(path) or _normalize_path(kwargs.get("path")) or ""
        except ValueError as exc:
            return str(exc)
        content_value = _normalize_content(content)
        allow_overwrite = _normalize_bool(overwrite)
        path_value = path_value.strip()
        if not path_value:
            return render_platform_prompt("workspace.write_file.missing_path.v1", {})
        if not content_value:
            return render_platform_prompt("workspace.write_file.missing_content.v1", {})
        if _looks_like_model_tool_call_payload(content_value):
            return render_platform_prompt("workspace.write_file.tool_call_payload_content_error.v1", {})
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
            return render_platform_prompt("workspace.write_file.outside_workspace.v1", {"path": path_value})
        if target.exists() and not allow_overwrite:
            return render_platform_prompt("workspace.write_file.exists_no_overwrite.v1", {"path": normalized})
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
            return render_platform_prompt("workspace.write_file.write_failed.v1", {"error": e})
        _checkpoint_workspace_write(workspace_id)
        return render_platform_prompt("workspace.write_file.success.v1", {"path": normalized})

    return ToolSpec.from_function(
        name="write_workspace_file",
        description=render_platform_prompt("tool.description.write_workspace_file.v1", {}),
        coroutine=_write_to_workspace_file,
        args_schema=WriteWorkspaceFileInput,
    )
