"""读取引用文件工具 - 经 OpenSandbox 挂载的工作区路径读取（不经宿主直读）。"""
from pydantic import BaseModel, Field

from app.agent.platform_prompts import render_platform_prompt
from app.agent.tool_spec import ToolSpec
from app.agent.read_path_utils import looks_like_url_or_remote_path, strip_llm_junk_from_read_path
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.agent.workspace_visibility import (
    WorkspacePathError,
    internal_diagnostic_path_error,
    internal_system_path_error,
    is_internal_diagnostic_workspace_path,
    is_internal_system_workspace_path,
    normalize_public_workspace_path,
)
from app.api.files import get_workspace_root_path
from app.core.security import get_current_user


class ReadFileInput(BaseModel):
    path: str = Field(default="", description=render_platform_prompt("tool.schema.read_workspace_file.path.v1", {}))


def _normalize_path(path_or_input) -> str:
    if path_or_input is None:
        return ""
    s = str(path_or_input).strip()
    if not s:
        return ""
    if s.startswith("{") and s.endswith("}"):
        raise ValueError(render_platform_prompt("workspace.read_file.json_wrapped_path_error.v1", {}))
    return s


def _workspace_relative_for_session(*, session_id: str, path: str) -> tuple[str, str | None]:
    """返回 (相对 workspace 根的路径, 错误信息)。"""
    raw = (path or "").strip()
    if not raw:
        return "", render_platform_prompt("workspace.read_file.missing_path.v1", {})
    if looks_like_url_or_remote_path(raw):
        return "", render_platform_prompt("workspace.read_file.remote_path_error.v1", {})
    cleaned = strip_llm_junk_from_read_path(raw) or raw
    normalized = cleaned.strip().replace("\\", "/")
    pseudo_names = {"stdout", "stderr", "returncode", "exit_code"}
    if normalized.strip("/") in pseudo_names:
        return "", render_platform_prompt("workspace.read_file.pseudo_field_error.v1", {"field": normalized})
    if not session_id:
        return "", render_platform_prompt("workspace.read_file.missing_session.v1", {})

    ws_root = get_workspace_root_path(session_id).resolve()
    current_prefix = f"sessions/{session_id}/workspace"
    if normalized == current_prefix:
        normalized = ""
    elif normalized.startswith(current_prefix + "/"):
        normalized = normalized[len(current_prefix) + 1 :]
    try:
        normalized = normalize_public_workspace_path(normalized)
    except WorkspacePathError as exc:
        if exc.code == "internal_system_path":
            return "", internal_system_path_error(normalized or raw)
        return "", f"错误：{exc}"
    full = (ws_root / normalized).resolve()
    try:
        rel = str(full.relative_to(ws_root)).replace("\\", "/")
    except ValueError:
        return "", render_platform_prompt("workspace.read_file.outside_workspace.v1", {})
    return rel, None


def create_read_file_tool(session_id: str) -> ToolSpec:
    """新建读取引用文件工具；有 session_id 时仅允许该会话 workspace，经 SandboxService + OpenSandbox 读 /workspace。"""

    async def _read_file(path: str = "", **kwargs) -> str:
        try:
            raw = _normalize_path(path) or _normalize_path(kwargs.get("path"))
        except ValueError as exc:
            return str(exc)
        rel, err = _workspace_relative_for_session(session_id=session_id or "", path=raw)
        if err:
            return err
        if is_internal_system_workspace_path(rel):
            return internal_system_path_error(rel)
        if is_internal_diagnostic_workspace_path(rel):
            return internal_diagnostic_path_error(rel)
        ws_root = get_workspace_root_path(session_id)
        svc = get_shared_sandbox_service()
        try:
            user_id = get_current_user().user_id
            text = await svc.read_workspace_text(
                user_id=user_id,
                session_id=session_id,
                workspace_path=ws_root,
                rel_path=rel,
            )
        except FileNotFoundError:
            return render_platform_prompt("workspace.read_file.not_found.v1", {"path": raw})
        except UnicodeDecodeError:
            return render_platform_prompt("workspace.read_file.non_utf8.v1", {"path": raw})
        except Exception as e:
            return render_platform_prompt("workspace.read_file.read_failed.v1", {"error": e})
        return text

    return ToolSpec.from_function(
        name="read_workspace_file",
        description=render_platform_prompt("tool.description.read_workspace_file.v1", {}),
        coroutine=_read_file,
        args_schema=ReadFileInput,
    )
