"""应用级初始化：按用户懒加载 MCP，不在启动时连接全局实例。"""
import logging

logger = logging.getLogger(__name__)

_initialized = False


async def ensure_mcp_and_skills_initialized() -> None:
    """
    兼容旧调用点：MCP 与 Skills 均在请求路径内按当前用户懒加载，
    此处仅保证幂等且不阻塞启动。
    """
    global _initialized
    if _initialized:
        return
    logger.info("书童四九：MCP / Skills 按用户懒加载，跳过进程级全局初始化")
    _initialized = True
