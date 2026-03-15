"""应用级初始化：MCP 与 Skills 只初始化一次，供单聊与群聊共用。"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_initialized = False


async def ensure_mcp_and_skills_initialized() -> None:
    """
    确保 MCP Manager 与 Skills Loader 已初始化（全局只执行一次）。
    单聊与群聊在入口处调用本函数；单聊随后可再执行「从磁盘加载会话历史」等自有逻辑。
    """
    global _initialized
    if _initialized:
        return
    logger.info("开始初始化 MCP Manager 和 Skills Loader")
    try:
        from app.mcp.manager import get_mcp_manager
        mgr = get_mcp_manager()
        await mgr.initialize_all()
        logger.info("MCP Manager 初始化完成，加载了 %s 个工具", len(mgr.tools))
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.exception("Failed to initialize MCP managers: %s", e)
        raise
    try:
        from app.skills.loader import get_skills_loader
        loader = get_skills_loader()
        loader.load_all_skills()
        logger.info("Skills Loader 初始化完成，加载了 %s 个技能", len(loader.skills))
    except Exception as e:
        logger.exception("Failed to load skills: %s", e)
        raise
    _initialized = True
    logger.info("MCP 与 Skills 初始化完成")
