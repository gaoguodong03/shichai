"""按 Agent 组装工具列表的统一入口（统一会话）。

build_tools_for_group_chat：按「本轮解析出的 Skill」在 SKILL.md frontmatter 中声明的工具名称决定可加载的 MCP（未声明则不调 MCP）；
工具完全由当前 Skill frontmatter 声明决定；不再用专家资源字段二次收紧。
内置工作区工具是平台默认能力；HTTP API 必须由当前 Skill allowed-tools 声明。
run_skill_script_<directory_name> → wrap。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.api.settings_mcp import load_mcp_config
from app.api.settings_skill_store import get_mcp_servers_for_skill
from app.api.settings_env_vars import load_env_var_values
from app.core.security import get_current_user
from app.mcp.manager import (
    _missing_mcp_placeholders,
    _transport_from_server_config,
    ensure_user_mcp_config_loaded,
)
from app.agent.builtin_workspace_tools import create_builtin_workspace_tools
from app.agent.skill_tool_naming import build_skill_script_tool_name
from app.agent.skill_tool_naming import build_read_skill_file_tool_name
from app.tools.http_api_tool import create_http_api_tool
from app.tools.run_skill_script import create_run_skill_script_tool, skill_has_skill_md
from app.tools.read_skill_file import create_read_skill_file_tool
from app.tools.filesystem_session_wrapper import wrap_filesystem_tools
from app.agent.tool_spec import ToolSpec
from app.agent.platform_prompts import render_platform_prompt

logger = logging.getLogger(__name__)


def _filter_redundant_workspace_mcp_tools(tools: List) -> List:
    """与内置工作区工具重复的 MCP 文本/列表能力不再注入，避免绕过 OpenSandbox 直读写宿主 data。"""
    redundant = {"file-reader_read_file", "file-reader_write_file", "file-reader_list_directory"}
    out: List = []
    for t in tools:
        if getattr(t, "name", "") in redundant:
            continue
        out.append(t)
    return out


_FILE_CAP_TO_TOOL = (
    ("read", "read_workspace_file"),
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
    env_vars: Dict[str, str],
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for server_name in tool_server_names:
        row = configured_rows.get(server_name)
        if not isinstance(row, dict):
            issues.append(
                {
                    "server": server_name,
                    "code": "mcp_config_missing",
                    "message": render_platform_prompt("tool.result.mcp_config_missing.v1", {}),
                    "missing": [],
                }
            )
            continue
        transport = _transport_from_server_config(row)
        transport_type = str(transport.get("type") or "stdio")
        missing: List[str] = []
        if transport_type == "stdio":
            for value in (transport.get("env") or {}).values():
                missing.extend(_missing_mcp_placeholders(value, env_vars))
        elif transport_type in ("http", "streamable_http", "sse"):
            raw_url = str(transport.get("url") or transport.get("base_url") or "")
            missing.extend(_missing_mcp_placeholders(raw_url, env_vars))
            for value in (transport.get("headers") or {}).values():
                missing.extend(_missing_mcp_placeholders(value, env_vars))
        if missing:
            missing = sorted(set(missing))
            issues.append(
                {
                    "server": server_name,
                    "code": "mcp_secret_missing",
                    "message": render_platform_prompt("tool.result.mcp_secret_missing.v1", {}),
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
                "message": render_platform_prompt("tool.result.mcp_configuration_unavailable.v1", {}),
                "missing": missing,
                "issues": issues,
            },
            ensure_ascii=False,
        )

    return ToolSpec.from_function(
        name="mcp_configuration_status",
        description=render_platform_prompt("tool.description.mcp_configuration_status.v1", {}),
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
    - 内置工作区工具是平台默认能力；HTTP API 只按当前 Skill allowed-tools 注入；
    - 仅为本轮 resolved_skill 注入 run_skill_script_<directory_name>（需 scripts/manifest.json）。
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
        env_vars = load_env_var_values()
    except Exception:
        env_vars = {}
    mcp_config_issues = _mcp_configuration_issues(tool_server_names, configured_rows, env_vars)

    mgr = None
    all_tools = []
    # 仅当本轮技能声明了 MCP 依赖时才加载用户 MCP 配置并连接对应 server；
    # 避免纯脚本类技能被 Linkup/Exa 等远程 MCP 冷启动拖慢。
    if tool_server_names:
        try:
            mgr = await ensure_user_mcp_config_loaded(get_current_user().user_id)
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
        create_builtin_workspace_tools(workspace_id), agent_profile
    )
    extras: List = [t for t in builtin_workspace_tools if getattr(t, "name", "") not in tool_names]
    if http_api_rows:
        for row in http_api_rows:
            tool = create_http_api_tool(row, env_vars=env_vars, workspace_id=workspace_id)
            if getattr(tool, "name", "") not in tool_names:
                extras.append(tool)
                tool_names.add(getattr(tool, "name", ""))
    if mcp_config_issues:
        extras.append(_create_mcp_configuration_status_tool(mcp_config_issues))
    tools = tools + extras
    tool_names = {getattr(t, "name", "") for t in tools}
    # 只有本轮标准脚本 Skill 才注入 run_skill_script，避免未选中 Skill 的脚本入口进入主路径。
    if rid and rid != "default" and skill_has_skill_md(rid):
        run_tool = create_run_skill_script_tool(rid, workspace_id, "workspace_all")
        run_tool.name = build_skill_script_tool_name(rid)
        if run_tool.name not in tool_names:
            tools.append(run_tool)
            tool_names.add(run_tool.name)

    # 有附加文件（references/assets/other）时注入只读读取工具
    if rid and rid != "default":
        read_tool = create_read_skill_file_tool(rid)
        read_tool.name = build_read_skill_file_tool_name(rid)
        if read_tool.name not in tool_names:
            tools.append(read_tool)
            tool_names.add(read_tool.name)

    return wrap_filesystem_tools(tools, workspace_id)
