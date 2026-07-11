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
from app.api.group_chat_state import ACTIVE_GROUP_RUNS
from app.core.security import get_current_user
from app.session_state.service import read_workspace_text_from_checkpoint


class ReadFileInput(BaseModel):
    path: str = Field(default="", description=render_platform_prompt("tool.schema.read_workspace_file.path.v1", {}))


def _normalize_path(path_or_input) -> str:
    if path_or_input is None:
        return ""
    s = str(path_or_input).strip()
    if not s:
        return ""
    if s.startswith("{") and s.endswith("}"):
        raise ValueError("path 不能是 JSON 包装字符串；请按工具 schema 传 path 参数。")
    return s


def _workspace_relative_for_session(*, session_id: str, path: str) -> tuple[str, str | None]:
    """返回 (相对 workspace 根的路径, 错误信息)。"""
    raw = (path or "").strip()
    if not raw:
        return "", "错误：未提供文件路径。"
    if looks_like_url_or_remote_path(raw):
        return "", (
            "错误：read_workspace_file 只能读取当前工作区内的相对路径文件。"
            "请使用诸如 github-weekly-snapshot.md 或 notes/report.md。"
        )
    cleaned = strip_llm_junk_from_read_path(raw) or raw
    normalized = cleaned.strip().replace("\\", "/")
    pseudo_names = {"stdout", "stderr", "returncode", "exit_code"}
    if normalized.strip("/") in pseudo_names:
        return "", render_platform_prompt("workspace.read_file.pseudo_field_error.v1", {"field": normalized})
    if not session_id:
        return "", "错误：read_workspace_file 需要会话上下文（session_id），请使用群聊工作区工具链。"

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
        return "", "错误：仅允许读取当前会话工作区内的文件，请使用工作区相对路径（例如 notes/report.md）。"
    return rel, None


def create_read_file_tool(session_id: str) -> ToolSpec:
    """新建读取引用文件工具；有 session_id 时仅允许该会话 workspace，经 SandboxService + OpenSandbox 读 /workspace。"""

    async def _read_file(path: str = "", **kwargs) -> str:
        try:
            raw = _normalize_path(path) or _normalize_path(kwargs.get("path"))
        except ValueError as exc:
            return f"错误：{exc}"
        rel, err = _workspace_relative_for_session(session_id=session_id or "", path=raw)
        if err:
            return err
        if is_internal_system_workspace_path(rel):
            return internal_system_path_error(rel)
        if is_internal_diagnostic_workspace_path(rel):
            return internal_diagnostic_path_error(rel)
        active_run = ACTIVE_GROUP_RUNS.get(session_id)
        checkpoint_id = str((active_run or {}).get("turn_started_checkpoint_id") or "").strip() if isinstance(active_run, dict) else ""
        if checkpoint_id:
            try:
                return read_workspace_text_from_checkpoint(session_id, checkpoint_id, rel)
            except FileNotFoundError:
                return render_platform_prompt("workspace.read_file.not_found.v1", {"path": raw})
            except UnicodeDecodeError:
                return f"错误：{raw} 不是 UTF-8 文本。"
            except Exception as e:
                return f"错误：读取文件失败 - {e}"
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
            return f"错误：{raw} 不是 UTF-8 文本。"
        except Exception as e:
            return f"错误：读取文件失败 - {e}"
        return text

    return ToolSpec.from_function(
        name="read_workspace_file",
        description=render_platform_prompt("tool.description.read_workspace_file.v1", {}),
        coroutine=_read_file,
        args_schema=ReadFileInput,
    )
