"""应用级初始化：启动时加载已存在用户的 MCP / Skills 资源。"""
import logging

from app.core.user_context import get_user_context_for, users_data_root
from app.mcp.manager import ensure_user_mcp_bootstrapped
from app.skills.loader import get_skills_loader_for_user

logger = logging.getLogger(__name__)

_initialized = False


def _known_usernames() -> list[str]:
    root = users_data_root()
    if not root.exists():
        return []
    try:
        return sorted(
            p.name
            for p in root.iterdir()
            if p.is_dir() and p.name.strip() and not p.name.startswith(".")
        )
    except Exception:  # noqa: BLE001
        logger.exception("mcp_skills_startup_scan_failed root=%s", root)
        return []


async def _load_user_mcp_and_skills(username: str) -> tuple[int, int, int]:
    ctx = get_user_context_for(username)
    skills_loader = get_skills_loader_for_user(username, ctx.skills_dir)
    mcp_manager = await ensure_user_mcp_bootstrapped(username)
    return (
        len(getattr(skills_loader, "skills", {}) or {}),
        len(getattr(mcp_manager, "server_configs", []) or []),
        len(getattr(mcp_manager, "tools", {}) or {}),
    )


async def ensure_mcp_and_skills_initialized() -> None:
    """启动时直接加载已有用户的 Skills 与 MCP 配置，后续调用保持幂等。"""
    global _initialized
    if _initialized:
        return
    usernames = _known_usernames()
    logger.info("书童四九：开始加载 MCP / Skills 用户资源 users=%s", len(usernames))

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
