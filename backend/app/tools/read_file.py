"""读取引用文件工具 - 经 OpenSandbox 挂载的工作区路径读取（不经宿主直读）。"""
import json
from pathlib import Path
from typing import Optional

from langchain_core.tools import StructuredTool

try:
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    from pydantic.v1 import BaseModel, Field  # type: ignore

from app.agent.read_path_utils import looks_like_url_or_remote_path, strip_llm_junk_from_read_path
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.api.files import WORKSPACES_SUBDIR, get_agent_outputs_root, get_workspace_root_path
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
            "错误：read_file 只能读取当前工作区内的相对路径文件，不能使用网页链接。"
            "请使用诸如 github-weekly-snapshot.md 或 memory/facts.md。"
        )
    cleaned = strip_llm_junk_from_read_path(raw) or raw
    root = get_agent_outputs_root().resolve()
    normalized = cleaned.lstrip("/")
    # Backward compatibility for old skill prompts:
    # under user-single-sandbox layout, scripts config lives at session root.
    if normalized in {"scripts/config.json"} or normalized.endswith("/scripts/config.json"):
        normalized = "config.json"
    if ".." in normalized:
        return "", "错误：路径不能包含 ..。"
    if not session_id:
        if not normalized:
            return "", "错误：未提供文件路径。"
        full = (root / normalized).resolve()
        if not str(full).startswith(str(root)):
            return "", f"错误：路径 {path} 不在允许的目录内。"
        try:
            rel = str(full.relative_to(root)).replace("\\", "/")
        except ValueError:
            return "", f"错误：路径 {path} 不在允许的目录内。"
        return rel, None

    prefix = f"{WORKSPACES_SUBDIR}/{session_id}"
    if not normalized.startswith(prefix + "/") and normalized != prefix:
        normalized = f"{prefix}/{normalized}" if normalized else prefix
    full = (root / normalized).resolve()
    ws_root = get_workspace_root_path(session_id).resolve()
    if not str(full).startswith(str(ws_root)):
        return "", "错误：仅允许读取当前会话工作区内的文件，请使用工作区相对路径（例如 notes/report.md）。"
    rel = str(full.relative_to(ws_root)).replace("\\", "/")
    return rel, None


def create_read_file_tool(session_id: Optional[str] = None) -> StructuredTool:
    """创建读取引用文件工具；有 session_id 时仅允许该会话 workspace，经 SandboxService + OpenSandbox 读 /workspace。"""

    async def _read_file(path: str = "", **kwargs) -> str:
        raw = _normalize_path(path) or _normalize_path(kwargs.get("__arg1")) or _normalize_path(kwargs.get("path"))
        rel, err = _workspace_relative_for_session(session_id=session_id or "", path=raw)
        if err:
            return err
        if not session_id:
            return "错误：read_file 需要会话上下文（session_id），请使用群聊工作区工具链。"
        ws_root = get_workspace_root_path(session_id)
        svc = get_shared_sandbox_service()
        try:
            user_id = get_current_user().username
            text = await svc.read_workspace_text(
                user_id=user_id,
                session_id=session_id,
                workspace_path=ws_root,
                rel_path=rel,
                tool_call_id=f"read_file:{rel}",
            )
        except FileNotFoundError:
            try:
                hints: list[str] = []
                target_name = Path(rel).name.lower()
                for p in ws_root.rglob("*"):
                    if not p.is_file():
                        continue
                    rr = str(p.relative_to(ws_root)).replace("\\", "/")
                    if target_name and p.name.lower() == target_name:
                        hints.append(rr)
                    elif target_name and target_name in p.name.lower():
                        hints.append(rr)
                    if len(hints) >= 5:
                        break
                if hints:
                    return (
                        f"错误：文件不存在：{raw}\n"
                        "你可能想读取以下路径（均在当前工作区）：\n- " + "\n- ".join(hints)
                    )
            except Exception:
                pass
            return f"错误：文件不存在：{raw}"
        except UnicodeDecodeError:
            return f"错误：{raw} 不是 UTF-8 文本。"
        except Exception as e:
            return f"错误：读取文件失败 - {e}"
        return text

    return StructuredTool.from_function(
        name="read_file",
        description=(
            "读取用户引用的文件内容。path 为工作区内相对路径（如 report.md 或 notes/report.txt）；"
            "文件经 OpenSandbox 在挂载的 /workspace 下读取，而非宿主进程直读。"
        ),
        coroutine=_read_file,
        args_schema=ReadFileInput,
    )
