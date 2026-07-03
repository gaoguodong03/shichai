"""按 Agent 组装工具列表的统一入口（统一会话）。

build_tools_for_group_chat：按「本轮解析出的 Skill」在 SKILL.md frontmatter 中声明的工具名称决定可加载的 MCP（未声明则不调 MCP）；
工具完全由当前 Skill frontmatter 声明决定；不再用专家资源字段二次收紧。
内置工作区工具与 call_api 是运行时自带能力，不作为专家资源字段保存。
run_skill_script_<directory_name> → wrap。
"""
from pathlib import Path
import json
import re
from typing import Any, Dict, List, Optional

from app.api.settings_mcp import load_mcp_config
from app.api.settings_skill_store import get_mcp_servers_for_skill
from app.api.settings_secrets import load_api_secret_values
from app.api.files import get_workspace_root
from app.core.security import get_current_user
from app.mcp.manager import (
    _missing_mcp_placeholders,
    _transport_from_server_config,
    ensure_user_mcp_config_loaded,
)
from app.agent.session_workspace_policy import sandbox_session_dir
from app.agent.skill_tool_naming import build_skill_script_tool_name
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.agent.workspace_visibility import is_internal_diagnostic_workspace_path
from app.tools.call_api import call_api
from app.tools.http_api_tool import create_http_api_tool
from app.tools.read_file import create_read_file_tool
from app.tools.run_skill_script import create_run_skill_script_tool, skill_has_skill_md
from app.tools.write_workspace_file import create_write_workspace_file_tool
from app.tools.filesystem_session_wrapper import wrap_filesystem_tools
from app.agent.tool_spec import ToolSpec

from pydantic import BaseModel, Field


class EditWorkspaceFileInput(BaseModel):
    path: str = Field(description="工作区内相对路径，例如 notes/report.md")
    old_text: str = Field(description="要替换的旧文本")
    new_text: str = Field(description="替换后的新文本")


class RenameWorkspaceFileInput(BaseModel):
    path: str = Field(description="原文件相对路径")
    new_name: str = Field(description="新文件名或新相对路径（如 notes/key.md，可用于移动）")


class MkdirWorkspaceInput(BaseModel):
    path: str = Field(description="要新建的目录相对路径，例如 notes/archive")


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
    user_id = get_current_user().username

    def _rel_safe(path: str) -> str:
        raw = str(path or "").strip().replace("\\", "/")
        if raw.startswith("/") or ".." in raw:
            raise ValueError("路径不在当前工作区")
        normalized = raw.strip("/")
        probe = (ws_root / normalized).resolve()
        if not str(probe).startswith(str(ws_root.resolve())):
            raise ValueError("路径不在当前工作区")
        return normalized

    async def _recover_single_timestamped_source(rel_path: str) -> str | None:
        rel = Path(rel_path)
        name = rel.name
        match = re.match(r"^(?P<prefix>.+-)(?:19|20)\d{12}(?:\d{2})?(?P<suffix>\.[^/.]+)$", name)
        if not match:
            return None
        parent = rel.parent.as_posix()
        rel_prefix = "" if parent == "." else parent
        svc = get_shared_sandbox_service()
        items = await svc.list_workspace_files_flat(
            user_id=user_id,
            session_id=workspace_id,
            workspace_path=ws_root,
            rel_prefix=rel_prefix,
        )
        workspace_root = sandbox_session_dir(workspace_id).rstrip("/")
        pattern = re.compile(
            "^"
            + re.escape(match.group("prefix"))
            + r"(?:19|20)\d{12}(?:\d{2})?"
            + re.escape(match.group("suffix"))
            + "$"
        )
        candidates: list[str] = []
        for item in items or []:
            raw_path = str((item or {}).get("path") or "").replace("\\", "/").rstrip("/")
            if raw_path.startswith(workspace_root + "/"):
                workspace_rel = raw_path[len(workspace_root) + 1 :]
            else:
                workspace_rel = raw_path
            candidate_rel = Path(workspace_rel)
            if candidate_rel.parent.as_posix() == rel_prefix and pattern.match(candidate_rel.name):
                candidates.append(candidate_rel.as_posix())
        unique = sorted(set(candidates))
        return unique[0] if len(unique) == 1 else None

    async def _edit_workspace_file(path: str, old_text: str, new_text: str) -> str:
        rel = _rel_safe(path)
        svc = get_shared_sandbox_service()
        try:
            content = await svc.read_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
            )
        except FileNotFoundError:
            return "错误：文件不存在或是目录。"
        except Exception as e:
            return f"错误：读取失败 - {e}"
        if old_text not in content:
            return "错误：未找到要替换的文本。"
        try:
            await svc.write_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
                content=content.replace(old_text, new_text),
            )
        except Exception as e:
            return f"错误：写入失败 - {e}"
        return f"已编辑文件：{path}"

    async def _rename_workspace_file(path: str, new_name: str) -> str:
        cleaned = str(new_name or "").strip().replace("\\", "/")
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
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                argv=[
                    "mv",
                    f"{sandbox_session_dir(workspace_id)}/{src_rel}".rstrip("/"),
                    f"{sandbox_session_dir(workspace_id)}/{dst_rel}".rstrip("/"),
                ],
                tool_call_id=f"mv:{src_rel}->{dst_rel}",
            )
        except Exception as e:
            recovered_src_rel = None
            try:
                recovered_src_rel = await _recover_single_timestamped_source(src_rel)
            except Exception:
                recovered_src_rel = None
            if not recovered_src_rel or recovered_src_rel == src_rel:
                return f"错误：重命名失败 - {e}"
            try:
                await svc.exec_workspace_shell(
                    user_id=user_id,
                    session_id=workspace_id,
                    workspace_path=ws_root,
                    argv=[
                        "mv",
                        f"{sandbox_session_dir(workspace_id)}/{recovered_src_rel}".rstrip("/"),
                        f"{sandbox_session_dir(workspace_id)}/{dst_rel}".rstrip("/"),
                    ],
                    tool_call_id=f"mv:{recovered_src_rel}->{dst_rel}",
                )
            except Exception as fallback_error:
                return f"错误：重命名失败 - {fallback_error}"
        return f"已重命名文件：{dst_rel}"

    async def _mkdir_workspace(path: str) -> str:
        cleaned = str(path or "").strip().replace("\\", "/").strip("/")
        if not cleaned:
            return "错误：path 不能为空。"
        if ".." in cleaned:
            return "错误：path 非法。"
        rel = _rel_safe(cleaned)
        svc = get_shared_sandbox_service()
        try:
            await svc.mkdir_workspace(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
            )
        except Exception as e:
            return f"错误：新建目录失败 - {e}"
        return f"已新建目录：{rel}"

    async def _list_workspace_directory(path: str = "") -> str:
        cleaned = str(path or "").strip().replace("\\", "/").strip("/")
        if cleaned:
            try:
                _rel_safe(cleaned)
            except ValueError:
                return "错误：路径不在当前工作区。"
        svc = get_shared_sandbox_service()
        try:
            items = await svc.list_workspace_files_flat(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_prefix=cleaned,
            )
        except Exception as e:
            return f"错误：列出目录失败 - {e}"
        prefix = cleaned or "."
        if not items:
            return f"目录 {prefix} 下：（空）"
        root = f"{sandbox_session_dir(workspace_id)}/{cleaned}".rstrip("/")
        workspace_root = sandbox_session_dir(workspace_id).rstrip("/")
        # OpenSandbox filesystem.search 返回的是完整路径；这里转成类似 find 的相对输出。
        rels: list[str] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            p = str(it.get("path") or "").replace("\\", "/").rstrip("/")
            if not p:
                continue
            if p == root:
                continue
            workspace_rel = ""
            if p.startswith(workspace_root + "/"):
                workspace_rel = p[len(workspace_root) + 1 :]
            if workspace_rel and is_internal_diagnostic_workspace_path(workspace_rel):
                continue
            if p.startswith(root + "/"):
                rels.append("./" + p[len(root) + 1 :])
        rels = sorted(set([r for r in rels if r != "./"]))
        if not rels:
            return f"目录 {prefix} 下：（空）"
        return f"目录 {prefix} 下的内容（含子目录）：\n" + "\n".join(rels)

    return [
        create_read_file_tool(session_id=workspace_id),
        create_write_workspace_file_tool(workspace_id),
        ToolSpec.from_function(
            name="edit_workspace_file",
            description="在当前工作区对文本文件做增量编辑（按 old_text 替换为 new_text）。",
            coroutine=_edit_workspace_file,
            args_schema=EditWorkspaceFileInput,
        ),
        ToolSpec.from_function(
            name="rename_workspace_file",
            description="重命名或移动当前工作区内的文件/目录。new_name 可传新名称，或传相对路径（如 notes/key.md）。",
            coroutine=_rename_workspace_file,
            args_schema=RenameWorkspaceFileInput,
        ),
        ToolSpec.from_function(
            name="mkdir_workspace",
            description="在当前工作区新建目录。",
            coroutine=_mkdir_workspace,
            args_schema=MkdirWorkspaceInput,
        ),
        ToolSpec.from_function(
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


def _filter_builtin_workspace_tools(all_builtin: List, agent_profile: Dict[str, Any]) -> List:
    _ = agent_profile
    allowed = {name for _key, name in _FILE_CAP_TO_TOOL}
    return [t for t in all_builtin if getattr(t, "name", "") in allowed]


def _mcp_configuration_issues(
    tool_server_names: List[str],
    configured_rows: Dict[str, Dict[str, Any]],
    secrets: Dict[str, str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for server_name in tool_server_names:
        row = configured_rows.get(server_name)
        if not isinstance(row, dict):
            issues.append(
                {
                    "server": server_name,
                    "code": "mcp_config_missing",
                    "message": "Skill 声明了该 MCP 工具，但资源中心没有对应配置。",
                    "missing": [],
                }
            )
            continue
        transport = _transport_from_server_config(row)
        transport_type = str(transport.get("type") or "stdio")
        missing: List[str] = []
        if transport_type == "stdio":
            for value in (transport.get("env") or {}).values():
                missing.extend(_missing_mcp_placeholders(value, secrets))
        elif transport_type in ("http", "streamable_http", "sse"):
            raw_url = str(transport.get("url") or transport.get("base_url") or "")
            missing.extend(_missing_mcp_placeholders(raw_url, secrets))
            for value in (transport.get("headers") or {}).values():
                missing.extend(_missing_mcp_placeholders(value, secrets))
        if missing:
            missing = sorted(set(missing))
            issues.append(
                {
                    "server": server_name,
                    "code": "mcp_secret_missing",
                    "message": "MCP 配置引用了未设置的密钥或环境变量。",
                    "missing": missing,
                }
            )
    return issues


def _create_mcp_configuration_status_tool(issues: List[Dict[str, Any]]) -> ToolSpec:
    def _status() -> str:
        missing = sorted(
            {
                str(item)
                for issue in issues
                for item in (issue.get("missing") or [])
                if str(item).strip()
            }
        )
        return json.dumps(
            {
                "ok": False,
                "code": "mcp_configuration_unavailable",
                "message": "本轮 Skill 声明的 MCP 工具未能加载，请先在资源中心配置对应密钥后重试。",
                "missing": missing,
                "issues": issues,
            },
            ensure_ascii=False,
        )

    return ToolSpec.from_function(
        name="mcp_configuration_status",
        description=(
            "查看本轮 Skill 声明但未可用的 MCP 配置问题。"
            "当检索、抓取等 MCP 工具没有出现在可用工具中时，先调用它并把缺失项告知用户。"
        ),
        func=_status,
        args_schema={"type": "object", "properties": {}},
    )


def _tool_mcp_server_name(tool: Any) -> str:
    metadata = getattr(tool, "metadata", None)
    if isinstance(metadata, dict):
        return str(metadata.get("mcp_server_name") or "").strip()
    return ""


async def build_tools_for_group_chat(
    agent_profile: Dict[str, Any],
    workspace_id: str,
    resolved_skill: Optional[str] = None,
) -> List:
    """
    按「本轮生效的 Skill」组装群聊 MCP 工具。
    - 仅允许 get_mcp_servers_for_skill(resolved_skill) 中的工具（仅 SKILL.md frontmatter 声明）；
    - 不再合并专家上全部 skills 的工具，也不从专家资源字段额外收紧；
    - 内置工作区工具与 call_api 是运行时自带能力；
    - 为 agent_profile["skills"] 中每个 skill 注入 run_skill_script_<directory_name>（磁盘上存在 SKILL 时）。
    """
    rid = str(resolved_skill or "").strip() or "default"
    configured_tool_names = list(dict.fromkeys(get_mcp_servers_for_skill(rid)))

    configured_rows = {
        str(row.get("name") or "").strip(): row
        for row in load_mcp_config()
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    }
    http_api_rows = [
        configured_rows[name]
        for name in configured_tool_names
        if str((configured_rows.get(name) or {}).get("type") or "") == "http_api"
    ]
    tool_server_names = [
        name
        for name in configured_tool_names
        if str((configured_rows.get(name) or {}).get("type") or "mcp") == "mcp"
    ]
    try:
        secrets = load_api_secret_values()
    except Exception:
        secrets = {}
    mcp_config_issues = _mcp_configuration_issues(tool_server_names, configured_rows, secrets)

    mgr = None
    all_tools = []
    # 仅当本轮技能声明了 MCP 依赖时才加载用户 MCP 配置并连接对应 server；
    # 避免纯脚本类技能被 Linkup/Exa 等远程 MCP 冷启动拖慢。
    if tool_server_names:
        try:
            mgr = await ensure_user_mcp_config_loaded(get_current_user().username)
            all_tools = mgr.get_tools()
        except Exception:
            mgr = None
            all_tools = []

    # 需要时才连接 MCP server
    if tool_server_names and mgr is not None:
        available_tool_names = {
            str(c.get("name")).strip()
            for c in (getattr(mgr, "server_configs", []) or [])
            if str(c.get("name", "")).strip()
        }
        tool_server_names = list(dict.fromkeys(sid for sid in tool_server_names if sid in available_tool_names))
        await mgr.ensure_servers_loaded(tool_server_names)
        all_tools = mgr.get_tools()

    if tool_server_names:
        allowed_servers = set(tool_server_names)
        tools = [t for t in all_tools if _tool_mcp_server_name(t) in allowed_servers]
    else:
        tools = []
    tools = _filter_redundant_workspace_mcp_tools(tools)
    tool_names = {getattr(t, "name", "") for t in tools}
    builtin_workspace_tools = _filter_builtin_workspace_tools(
        _create_builtin_workspace_tools(workspace_id), agent_profile
    )
    extras: List = [t for t in builtin_workspace_tools if getattr(t, "name", "") not in tool_names]
    if http_api_rows:
        for row in http_api_rows:
            tool = create_http_api_tool(row, secrets=secrets)
            if getattr(tool, "name", "") not in tool_names:
                extras.append(tool)
                tool_names.add(getattr(tool, "name", ""))
    if mcp_config_issues:
        extras.append(_create_mcp_configuration_status_tool(mcp_config_issues))
    else:
        extras.append(call_api)
    tools = tools + extras
    tool_names = {getattr(t, "name", "") for t in tools}
    # 为 Agent 的每个技能注入 run_skill_script，名称带目录名避免覆盖，方便图标生成等用脚本而非 MCP 文件工具
    for skill_ref in (agent_profile.get("skills") or []):
        sid = str(skill_ref.get("directory_name") if isinstance(skill_ref, dict) else "").strip()
        if not sid or not skill_has_skill_md(sid):
            # 跳过磁盘上不存在或仅有空壳的目录（常见于改名后未同步专家配置）
            continue
        run_tool = create_run_skill_script_tool(sid, workspace_id, "workspace_all")
        run_tool.name = build_skill_script_tool_name(sid)
        if run_tool.name not in tool_names:
            tools.append(run_tool)
            tool_names.add(run_tool.name)
    return wrap_filesystem_tools(tools, workspace_id)
