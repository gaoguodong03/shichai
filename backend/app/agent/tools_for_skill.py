"""按 DHA 组装工具列表的统一入口（统一会话）。

build_tools_for_group_chat：按「本轮解析出的 Skill」的 mcp_server_ids（及内置 fallback）决定可加载的 MCP；
专家的 dha.mcp_server_ids 若配置则与上述列表取交集，作为实例级收紧；不再从全局运行时额外注入
Linkup/Exa 等 URL 工具。内置工作区工具与 call_api 按专家 dha 的 file_capabilities / url_capability 注入；
run_skill_script_<skill_id> → wrap。
"""
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.api.settings import get_mcp_servers_for_skill
from app.api.dha import merge_file_capabilities
from app.api.files import get_workspace_root
from app.agent.host_plan import is_host_plan_reserved_path
from app.core.security import get_current_user
from app.mcp.manager import ensure_user_mcp_bootstrapped
from app.agent.sandbox_service import to_workspace_inner_path
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
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


class EditWorkspaceFileInput(BaseModel):
    path: str = Field(description="工作区内相对路径，例如 notes/report.md")
    old_text: str = Field(description="要替换的旧文本")
    new_text: str = Field(description="替换后的新文本")


class RenameWorkspaceFileInput(BaseModel):
    path: str = Field(description="原文件相对路径")
    new_name: str = Field(description="新文件名或新相对路径（如 notes/key.md，可用于移动）")


class MkdirWorkspaceInput(BaseModel):
    path: str = Field(description="要创建的目录相对路径，例如 notes/archive")


class ListWorkspaceDirectoryInput(BaseModel):
    path: str = Field(description="目录相对路径，留空表示工作区根目录", default="")


def _filter_redundant_workspace_mcp_tools(tools: List) -> List:
    """与内置工作区工具重复的 MCP 文本/列表能力不再注入，避免绕过 OpenSandbox 直读写宿主 data。"""
    redundant = {"file-reader_read_file", "file-reader_write_file", "file-reader_list_directory"}
    out: List = []
    for t in tools:
        if getattr(t, "name", "") in redundant:
            continue
        out.append(t)
    return out


def _create_builtin_workspace_tools(workspace_id: str) -> List:
    ws_root = get_workspace_root(workspace_id)

    def _rel_safe(path: str) -> str:
        normalized = str(path or "").strip("/").replace("..", "")
        probe = (ws_root / normalized).resolve()
        if not str(probe).startswith(str(ws_root.resolve())):
            raise ValueError("路径不在当前工作区")
        return normalized

    async def _edit_workspace_file(path: str, old_text: str, new_text: str) -> str:
        if is_host_plan_reserved_path(path):
            return (
                "错误：memory/host_plan.md 为用户可编辑的任务清单，智能体工具禁止修改；"
                "请用户在侧边栏工作区中编辑。"
            )
        rel = _rel_safe(path)
        svc = get_shared_sandbox_service()
        try:
            content = await svc.read_workspace_text(
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
                tool_call_id=f"edit:{rel}",
            )
        except FileNotFoundError:
            return "错误：文件不存在或是目录。"
        except Exception as e:
            return f"错误：读取失败 - {e}"
        if old_text not in content:
            return "错误：未找到要替换的文本。"
        try:
            await svc.write_workspace_text(
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
                content=content.replace(old_text, new_text),
                tool_call_id=f"edit-write:{rel}",
            )
        except Exception as e:
            return f"错误：写入失败 - {e}"
        return f"已编辑文件：{path}"

    async def _rename_workspace_file(path: str, new_name: str) -> str:
        if is_host_plan_reserved_path(path):
            return (
                "错误：memory/host_plan.md 为用户可编辑的任务清单，智能体工具禁止移动或重命名；"
                "请用户在侧边栏工作区中操作。"
            )
        cleaned = str(new_name or "").strip().replace("\\", "/")
        if is_host_plan_reserved_path(cleaned) or is_host_plan_reserved_path(cleaned.lstrip("/")):
            return "错误：不能将文件移动或重命名为 memory/host_plan.md（该路径保留给用户任务清单）。"
        if not cleaned:
            return "错误：new_name 不能为空。"
        if ".." in cleaned:
            return "错误：new_name 非法。"
        src_rel = _rel_safe(path)
        if "/" in cleaned:
            dst_rel = _rel_safe(cleaned)
        else:
            dst_rel = str((Path(src_rel).parent / cleaned).as_posix()).lstrip("/")
            dst_rel = _rel_safe(dst_rel)
        svc = get_shared_sandbox_service()
        try:
            await svc.exec_workspace_shell(
                session_id=workspace_id,
                workspace_path=ws_root,
                argv=["mv", to_workspace_inner_path(src_rel), to_workspace_inner_path(dst_rel)],
                tool_call_id=f"mv:{src_rel}->{dst_rel}",
            )
        except Exception as e:
            return f"错误：重命名失败 - {e}"
        return f"已重命名文件：{dst_rel}"

    async def _mkdir_workspace(path: str) -> str:
        cleaned = str(path or "").strip().replace("\\", "/").strip("/")
        if not cleaned:
            return "错误：path 不能为空。"
        if ".." in cleaned:
            return "错误：path 非法。"
        if is_host_plan_reserved_path(cleaned):
            return "错误：不能创建保留路径 memory/host_plan.md。"
        rel = _rel_safe(cleaned)
        svc = get_shared_sandbox_service()
        try:
            await svc.mkdir_workspace(session_id=workspace_id, workspace_path=ws_root, rel_path=rel, turn_id="mkdir")
        except Exception as e:
            return f"错误：创建目录失败 - {e}"
        return f"已创建目录：{rel}"

    async def _list_workspace_directory(path: str = "") -> str:
        cleaned = str(path or "").strip().replace("\\", "/").strip("/")
        if cleaned:
            try:
                _rel_safe(cleaned)
            except ValueError:
                return "错误：路径不在当前工作区。"
        svc = get_shared_sandbox_service()
        try:
            res = await svc.exec_workspace_shell(
                session_id=workspace_id,
                workspace_path=ws_root,
                argv=["sh", "-c", f"cd /workspace/{cleaned} && find . -mindepth 1 | sort"],
                tool_call_id="list-find",
            )
        except Exception as e:
            return f"错误：列出目录失败 - {e}"
        stdout = str((res or {}).get("stdout") or (res or {}).get("output") or "").strip()
        prefix = cleaned or "."
        if not stdout:
            return f"目录 {prefix} 下：（空）"
        return f"目录 {prefix} 下的内容（含子目录）：\n{stdout}"

    return [
        create_read_file_tool(session_id=workspace_id),
        create_write_workspace_file_tool(workspace_id),
        StructuredTool.from_function(
            name="edit_workspace_file",
            description="在当前工作区对文本文件做增量编辑（按 old_text 替换为 new_text）。",
            coroutine=_edit_workspace_file,
            args_schema=EditWorkspaceFileInput,
        ),
        StructuredTool.from_function(
            name="rename_workspace_file",
            description="重命名或移动当前工作区内的文件/目录。new_name 可传新名称，或传相对路径（如 notes/key.md）。",
            coroutine=_rename_workspace_file,
            args_schema=RenameWorkspaceFileInput,
        ),
        StructuredTool.from_function(
            name="mkdir_workspace",
            description="在当前工作区创建目录。",
            coroutine=_mkdir_workspace,
            args_schema=MkdirWorkspaceInput,
        ),
        StructuredTool.from_function(
            name="list_workspace_directory",
            description="递归列出当前工作区目录内容（含子目录）。",
            coroutine=_list_workspace_directory,
            args_schema=ListWorkspaceDirectoryInput,
        ),
    ]


_FILE_CAP_TO_TOOL = (
    ("read", "read_file"),
    ("write", "write_workspace_file"),
    ("edit", "edit_workspace_file"),
    ("rename", "rename_workspace_file"),
    ("mkdir", "mkdir_workspace"),
    ("list_dir", "list_workspace_directory"),
)


def _filter_builtin_workspace_tools(all_builtin: List, dha: Dict[str, Any]) -> List:
    caps = merge_file_capabilities(dha.get("file_capabilities"))
    allowed = {name for key, name in _FILE_CAP_TO_TOOL if caps.get(key)}
    return [t for t in all_builtin if getattr(t, "name", "") in allowed]


async def build_tools_for_group_chat(
    dha: Dict[str, Any],
    workspace_id: str,
    resolved_skill_id: Optional[str] = None,
) -> List:
    """
    按「本轮生效的 Skill」组装群聊 MCP 工具。
    - 仅允许 get_mcp_servers_for_skill(resolved_skill_id) 中的 MCP（含 SKILL  frontmatter 与 fallback）；
    - 若 dha["mcp_server_ids"] 非空，与上式取交集，作为实例级收紧；
    - 不再合并专家上全部 skill_ids 的 MCP，也不从全局运行时额外注入 Linkup/Exa。
    - 内置工作区工具按 dha["file_capabilities"]；call_api 仅当 dha["url_capability"] 为真；
    - 为 dha["skill_ids"] 中每个 skill 注入 run_skill_script_<skill_id>（磁盘上存在 SKILL 时）。
    """
    rid = str(resolved_skill_id or "").strip() or "default"
    skill_servers = list(dict.fromkeys(get_mcp_servers_for_skill(rid)))
    expert_ids = dha.get("mcp_server_ids") or []
    if expert_ids:
        es = {str(x).strip() for x in expert_ids if str(x).strip()}
        server_ids = [x for x in skill_servers if x in es]
    else:
        server_ids = skill_servers

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
    tools = _filter_redundant_workspace_mcp_tools(tools)
    tool_names = {getattr(t, "name", "") for t in tools}
    builtin_workspace_tools = _filter_builtin_workspace_tools(
        _create_builtin_workspace_tools(workspace_id), dha
    )
    extras: List = [t for t in builtin_workspace_tools if getattr(t, "name", "") not in tool_names]
    if bool(dha.get("url_capability", True)):
        extras.append(call_api)
    tools = tools + extras
    tool_names = {getattr(t, "name", "") for t in tools}
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
