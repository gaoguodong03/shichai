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
    # MCP 初始化失败不应阻塞整个后端启动：没有 MCP 时仍可使用基础对话与本地脚本能力。
    try:
        from app.mcp.manager import get_mcp_manager
        mgr = get_mcp_manager()
        await mgr.initialize_all()
        logger.info("MCP Manager 初始化完成，加载了 %s 个工具", len(mgr.tools))
    except asyncio.CancelledError as e:
        # MCP 初始化过程中被 anyio/asyncio 取消（常见于某些 stdio server 卡死/超时）。
        # 这里直接降级，不再阻塞服务启动。
        logger.exception("MCP Manager 初始化被取消（将降级运行，不影响服务启动）: %s", e)
    except BaseException as e:
        logger.exception("MCP Manager 初始化失败（将降级运行，不影响服务启动）: %s", e)
    try:
        from app.skills.loader import get_skills_loader
        loader = get_skills_loader()
        loader.load_all_skills()
        logger.info("Skills Loader 初始化完成，加载了 %s 个技能", len(loader.skills))
    except Exception as e:
        logger.exception("Skills Loader 初始化失败（将降级运行，不影响服务启动）: %s", e)
    _initialized = True
    logger.info("MCP 与 Skills 初始化完成")
