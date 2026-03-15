"""按 DHA 组装工具列表的统一入口（统一会话，单聊已下线）。

使用 build_tools_for_group_chat：按 DHA 的 mcp_server_ids 或 skill 的 MCP 依赖过滤 →
叠加只读 file-reader/filesystem、call_api → 为每个 skill 注入 run_skill_script_<skill_id> →
过滤写文件 → wrap。
"""
from typing import Any, Dict, List

from app.api.settings import get_mcp_servers_for_skill
from app.tools.call_api import call_api
from app.tools.run_skill_script import create_run_skill_script_tool
from app.tools.filesystem_session_wrapper import wrap_filesystem_tools


def _is_write_tool(name: str) -> bool:
    """是否为写文件类工具（排除）。"""
    if (name or "").startswith("filesystem_"):
        return "write" in (name or "") or "edit" in (name or "")
    return (name or "") == "file-reader_write_file"


def _readonly_file_tools(all_tools: List) -> List:
    """从 all_tools 中筛出只读的 file-reader 与 filesystem 工具。"""
    result = []
    for t in all_tools:
        n = getattr(t, "name", "")
        if n.startswith("filesystem_") and not _is_write_tool(n):
            result.append(t)
        elif n.startswith("file-reader_") and n != "file-reader_write_file":
            result.append(t)
    return result


def build_tools_for_group_chat(
    all_tools: List,
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
    if server_ids:
        tools = [t for t in all_tools if "_" in getattr(t, "name", "") and getattr(t, "name", "").split("_", 1)[0] in server_ids]
    else:
        tools = []
    file_tools = _readonly_file_tools(all_tools)
    tool_names = {getattr(t, "name", "") for t in tools}
    tools = tools + [t for t in file_tools if getattr(t, "name", "") not in tool_names] + [call_api]
    # 为 DHA 的每个技能注入 run_skill_script，名称带 skill_id 避免覆盖，方便图标生成等用脚本而非 MCP 文件工具
    for skill_id in (dha.get("skill_ids") or []):
        run_tool = create_run_skill_script_tool(skill_id)
        run_tool.name = f"run_skill_script_{skill_id}"
        if run_tool.name not in tool_names:
            tools.append(run_tool)
            tool_names.add(run_tool.name)
    tools = [t for t in tools if not _is_write_tool(getattr(t, "name", ""))]
    return wrap_filesystem_tools(tools, workspace_id)
