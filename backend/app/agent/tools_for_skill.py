"""按 DHA 组装工具列表的统一入口（统一会话）。

build_tools_for_group_chat：从当前用户的 MCP 运行时取工具，按 mcp_server_ids / skill MCP 依赖过滤 →
叠加 file-reader/filesystem、call_api → 为每个 skill 注入 run_skill_script_<skill_id> → wrap。
"""
import hashlib
import re
from typing import Any, Dict, List

from app.api.settings import get_mcp_servers_for_skill
from app.api.files import get_workspace_root
from app.core.security import get_current_user
from app.mcp.manager import ensure_user_mcp_bootstrapped
from app.tools.call_api import call_api
from app.tools.read_file import create_read_file_tool
from app.tools.run_skill_script import create_run_skill_script_tool, skill_has_skill_md
from app.tools.write_workspace_file import create_write_workspace_file_tool
from app.tools.filesystem_session_wrapper import wrap_filesystem_tools
from langchain_core.tools import StructuredTool

try:
    from langchain_core.pydantic_v1 import BaseModel, Field
except ImportError:
    from pydantic.v1 import BaseModel, Field  # type: ignore

_TOOL_NAME_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def build_skill_script_tool_name(skill_id: str) -> str:
    """构造符合工具命名约束的 run_skill_script 工具名。

    部分模型供应商要求 function.name 严格匹配 ^[a-zA-Z0-9_\\.-]+$。
    对包含中文/空格等字符的 skill_id，需要做安全化，否则会在请求阶段被拒绝。
    """
    raw = str(skill_id or "").strip()
    if not raw:
        return "run_skill_script_default"
    sanitized = _TOOL_NAME_INVALID_CHARS_RE.sub("_", raw).strip("_.-")
    if not sanitized:
        sanitized = "skill"
    # 仅在发生字符变换时追加哈希，兼顾可读性与唯一性
    if sanitized != raw:
        suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
        sanitized = f"{sanitized}_{suffix}"
    return f"run_skill_script_{sanitized}"


def _resolve_server_ids_with_aliases(server_ids: List[str], available_ids: set[str]) -> List[str]:
    """将历史 server id 映射到当前可用 id（如 fetch -> linkup）。"""
    alias = {
        "fetch": "linkup",
    }
    out: List[str] = []
    for sid in server_ids:
        if sid in available_ids:
            out.append(sid)
            continue
        mapped = alias.get(sid)
        if mapped and mapped in available_ids:
            out.append(mapped)
    return list(dict.fromkeys(out))


def _is_write_tool(name: str) -> bool:
    """是否为写文件类工具（排除）。"""
    if (name or "").startswith("filesystem_"):
        return "write" in (name or "") or "edit" in (name or "")
    return (name or "") == "file-reader_write_file"


def _file_tools(all_tools: List, allow_write: bool) -> List:
    """从 all_tools 中筛出 file-reader 与 filesystem 工具。allow_write=False 时仅保留只读工具。"""
    result = []
    for t in all_tools:
        n = getattr(t, "name", "")
        if n.startswith("filesystem_") and (allow_write or not _is_write_tool(n)):
            result.append(t)
        elif n.startswith("file-reader_") and (allow_write or n != "file-reader_write_file"):
            result.append(t)
    return result


def _url_tools(all_tools: List) -> List:
    """从 all_tools 中筛出 URL 抓取/搜索类工具（默认给所有专家）。"""
    result = []
    for t in all_tools:
        n = (getattr(t, "name", "") or "").lower()
        if not n:
            continue
        if n.startswith("linkup_") or n.startswith("exa_"):
            result.append(t)
            continue
        if any(k in n for k in ("fetch", "search", "crawl", "url", "web")):
            result.append(t)
    return result


class EditWorkspaceFileInput(BaseModel):
    path: str = Field(description="工作区内相对路径，例如 notes/report.md")
    old_text: str = Field(description="要替换的旧文本")
    new_text: str = Field(description="替换后的新文本")


class DeleteWorkspaceFileInput(BaseModel):
    path: str = Field(description="工作区内相对路径")


class RenameWorkspaceFileInput(BaseModel):
    path: str = Field(description="原文件相对路径")
    new_name: str = Field(description="新文件名或新相对路径（如 notes/key.md，可用于移动）")


def _create_builtin_workspace_tools(workspace_id: str) -> List:
    ws_root = get_workspace_root(workspace_id)

    def _safe_path(path: str):
        normalized = str(path or "").strip("/").replace("..", "")
        target = (ws_root / normalized).resolve()
        if not str(target).startswith(str(ws_root)):
            raise ValueError("路径不在当前工作区")
        return target

    def _edit_workspace_file(path: str, old_text: str, new_text: str) -> str:
        target = _safe_path(path)
        if not target.exists() or target.is_dir():
            return "错误：文件不存在或是目录。"
        content = target.read_text(encoding="utf-8")
        if old_text not in content:
            return "错误：未找到要替换的文本。"
        target.write_text(content.replace(old_text, new_text), encoding="utf-8")
        return f"已编辑文件：{path}"

    def _delete_workspace_file(path: str) -> str:
        target = _safe_path(path)
        if not target.exists():
            return "错误：文件不存在。"
        if target.is_dir():
            return "错误：仅支持删除文件，不支持目录。"
        target.unlink()
        return f"已删除文件：{path}"

    def _rename_workspace_file(path: str, new_name: str) -> str:
        target = _safe_path(path)
        if not target.exists() or target.is_dir():
            return "错误：文件不存在或是目录。"
        cleaned = str(new_name or "").strip().replace("\\", "/")
        if not cleaned:
            return "错误：new_name 不能为空。"
        if ".." in cleaned:
            return "错误：new_name 非法。"
        # 兼容：仅文件名=同目录重命名；含 / = 工作区内目标相对路径（可移动）。
        if "/" in cleaned:
            new_path = _safe_path(cleaned)
        else:
            new_path = (target.parent / cleaned).resolve()
            if not str(new_path).startswith(str(ws_root)):
                return "错误：目标路径不在当前工作区。"
        new_path.parent.mkdir(parents=True, exist_ok=True)
        target.rename(new_path)
        rel = str(new_path.relative_to(ws_root)).replace("\\", "/")
        return f"已重命名文件：{rel}"

    return [
        create_read_file_tool(session_id=workspace_id),
        create_write_workspace_file_tool(workspace_id),
        StructuredTool.from_function(
            name="edit_workspace_file",
            description="在当前工作区对文本文件做增量编辑（按 old_text 替换为 new_text）。",
            func=_edit_workspace_file,
            args_schema=EditWorkspaceFileInput,
        ),
        StructuredTool.from_function(
            name="delete_workspace_file",
            description="删除当前工作区内的文件。",
            func=_delete_workspace_file,
            args_schema=DeleteWorkspaceFileInput,
        ),
        StructuredTool.from_function(
            name="rename_workspace_file",
            description="重命名或移动当前工作区内的文件。new_name 可传新文件名，或传相对路径（如 notes/key.md）。",
            func=_rename_workspace_file,
            args_schema=RenameWorkspaceFileInput,
        ),
    ]


async def build_tools_for_group_chat(
    dha: Dict[str, Any],
    workspace_id: str,
) -> List:
    """
    按 DHA 配置组装群聊工具列表。
    - dha["mcp_server_ids"] 有值：仅传这些 MCP 的工具。
    - 为空：按 dha["skill_ids"] 的 MCP 依赖过滤；若技能无 MCP 依赖，仅传只读文件工具 + call_api。
    - 若 DHA 有 skill_ids，为每个 skill 注入 run_skill_script（名称 run_skill_script_<skill_id>），
      以便图标生成等技能在群聊中能直接执行 scripts/generate_image.py，避免误用 list_allowed_directories 等 MCP。
    """
    server_ids = dha.get("mcp_server_ids") or []
    if not server_ids:
        skill_ids = dha.get("skill_ids") or []
        for sid in skill_ids:
            server_ids.extend(get_mcp_servers_for_skill(sid))
        server_ids = list(dict.fromkeys(server_ids))
    else:
        skill_ids = dha.get("skill_ids") or []
    allow_write = True

    mgr = None
    all_tools = []
    try:
        mgr = await ensure_user_mcp_bootstrapped(get_current_user().username)
        all_tools = mgr.get_tools()
    except Exception:
        mgr = None
        all_tools = []

    # 需要时才连接懒加载的 MCP server
    if server_ids and mgr is not None:
        available_server_ids = {
            str(c.get("id")).strip()
            for c in (getattr(mgr, "server_configs", []) or [])
            if str(c.get("id", "")).strip()
        }
        server_ids = _resolve_server_ids_with_aliases(server_ids, available_server_ids)
        await mgr.ensure_servers_loaded(server_ids)
        all_tools = mgr.get_tools()

    if server_ids:
        tools = [t for t in all_tools if "_" in getattr(t, "name", "") and getattr(t, "name", "").split("_", 1)[0] in server_ids]
    else:
        tools = []
    file_tools = _file_tools(all_tools, allow_write=allow_write)
    url_tools = _url_tools(all_tools)
    tool_names = {getattr(t, "name", "") for t in tools}
    builtin_workspace_tools = _create_builtin_workspace_tools(workspace_id)
    tools = (
        tools
        + [t for t in file_tools if getattr(t, "name", "") not in tool_names]
        + [t for t in url_tools if getattr(t, "name", "") not in tool_names]
        + [t for t in builtin_workspace_tools if getattr(t, "name", "") not in tool_names]
        + [call_api]
    )
    # 为 DHA 的每个技能注入 run_skill_script，名称带 skill_id 避免覆盖，方便图标生成等用脚本而非 MCP 文件工具
    for skill_id in (dha.get("skill_ids") or []):
        sid = str(skill_id or "").strip()
        if not sid or not skill_has_skill_md(sid):
            # 跳过磁盘上不存在或仅有空壳的 skill_id（常见于改名后未同步专家配置）
            continue
        run_tool = create_run_skill_script_tool(sid, workspace_id, "workspace_all")
        run_tool.name = build_skill_script_tool_name(sid)
        if run_tool.name not in tool_names:
            tools.append(run_tool)
            tool_names.add(run_tool.name)
    if not allow_write:
        tools = [t for t in tools if not _is_write_tool(getattr(t, "name", ""))]
    return wrap_filesystem_tools(tools, workspace_id)
