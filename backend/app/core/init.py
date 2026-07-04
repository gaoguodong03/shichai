"""应用级初始化：启动时预热已存在用户的轻量 MCP / Skills 资源。"""
import logging
from pathlib import Path

from app.core.user_context import get_user_context_for, users_data_root
from app.mcp.manager import ensure_user_mcp_config_loaded
from app.skills.loader import get_skills_loader_for_user

logger = logging.getLogger(__name__)

_initialized = False


def _skills_dir_has_skill_files(skills_dir: Path) -> bool:
    if not skills_dir.is_dir():
        return False
    try:
        return any((child / "SKILL.md").is_file() for child in skills_dir.iterdir() if child.is_dir())
    except OSError:
        return False


def _user_has_startup_resources(user_dir: Path) -> bool:
    resources = user_dir / "resources"
    tools_dir = resources / "tools"
    has_tools = False
    if tools_dir.is_dir():
        try:
            has_tools = any((child / "tool.json").is_file() for child in tools_dir.iterdir() if child.is_dir())
        except OSError:
            has_tools = False
    return _skills_dir_has_skill_files(resources / "skills") or has_tools


def _known_usernames() -> list[str]:
    root = users_data_root()
    if not root.exists():
        return []
    try:
        return sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir() and p.name.strip() and not p.name.startswith(".") and _user_has_startup_resources(p)
        )
    except Exception:  # noqa: BLE001
        logger.exception("mcp_skills_startup_scan_failed root=%s", root)
        return []


async def _load_user_mcp_and_skills(username: str) -> tuple[int, int, int]:
    ctx = get_user_context_for(username)
    skills_count = 0
    if _skills_dir_has_skill_files(ctx.skills_dir):
        skills_loader = get_skills_loader_for_user(username, ctx.skills_dir)
        skills_count = len(getattr(skills_loader, "skills", {}) or {})

    mcp_server_count = 0
    mcp_tool_count = 0
    if ctx.tools_dir.is_dir():
        mcp_manager = await ensure_user_mcp_config_loaded(username)
        mcp_server_count = len(getattr(mcp_manager, "server_configs", []) or [])
        # 启动期只读配置，不连接 MCP Server；这里仅统计已经存在的工具缓存。
        mcp_tool_count = len(getattr(mcp_manager, "tools", {}) or {})

    return (skills_count, mcp_server_count, mcp_tool_count)


async def ensure_mcp_and_skills_initialized() -> None:
    """启动时直接加载已有用户的 Skills 与 MCP 配置，后续调用保持幂等。

    注意：这里不主动连接 MCP Server。连接动作只发生在对话运行、测试连接、
    查看工具列表等明确需要工具能力的路径，避免启动期扫全量用户时拉起大量 MCP。
    """
    global _initialized
    if _initialized:
        return
    usernames = _known_usernames()
    logger.info("书童四九：开始预热 MCP / Skills 配置 users=%s", len(usernames))

    ok_count = 0
    failed_count = 0
    for username in usernames:
        try:
            skills_count, mcp_server_count, mcp_tool_count = await _load_user_mcp_and_skills(username)
            ok_count += 1
            logger.info(
                "mcp_skills_startup_user_loaded user=%s skills=%s mcp_servers=%s mcp_tools=%s",
                username,
                skills_count,
                mcp_server_count,
                mcp_tool_count,
            )
        except Exception as exc:  # noqa: BLE001
            failed_count += 1
            logger.exception("mcp_skills_startup_user_failed user=%s err=%s", username, exc)

    logger.info(
        "mcp_skills_startup_done users_total=%s ok=%s failed=%s",
        len(usernames),
        ok_count,
        failed_count,
    )
    _initialized = True
