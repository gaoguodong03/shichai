"""读取引用文件工具 - 经 OpenSandbox 挂载的工作区路径读取（不经宿主直读）。"""
import json
from pydantic import BaseModel, Field

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
    path: str = Field(default="", description="工作区内相对路径，如 notes/report.md")


def _normalize_path(path_or_input) -> str:
    if path_or_input is None:
        return ""
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
        return "", (
            f"错误：{normalized} 是工具返回字段，不是工作区文件。"
            "请直接根据上一条工具结果中的 stdout/stderr/returncode 生成最终答复，不要调用 read_workspace_file。"
        )
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
        raw = _normalize_path(path) or _normalize_path(kwargs.get("__arg1")) or _normalize_path(kwargs.get("path"))
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
            user_id = get_current_user().username
            text = await svc.read_workspace_text(
                user_id=user_id,
                session_id=session_id,
                workspace_path=ws_root,
                rel_path=rel,
            )
        except FileNotFoundError:
            return f"错误：文件不存在：{raw}。不要继续猜测文件名；请先调用 list_workspace_directory 查看真实路径。"
        except UnicodeDecodeError:
            return f"错误：{raw} 不是 UTF-8 文本。"
        except Exception as e:
            return f"错误：读取文件失败 - {e}"
        return text

    return ToolSpec.from_function(
        name="read_workspace_file",
        description=(
            "读取用户引用的文件内容。path 为工作区内相对路径（如 report.md 或 notes/report.txt）；"
            "文件经 OpenSandbox 在挂载的 /workspace 下读取，而非宿主进程直读。"
        ),
        coroutine=_read_file,
        args_schema=ReadFileInput,
    )
