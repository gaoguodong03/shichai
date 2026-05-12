"""FastAPI 生命周期管理。"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.runtime_env import is_truthy_env
from app.mcp.manager import cleanup_all_mcp_runtimes


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。MCP enter/exit 必须保持在同一 asyncio 任务。"""
    lvl_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    lvl = getattr(logging, lvl_name, logging.INFO)
    logging.basicConfig(
        level=lvl,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )
    log = logging.getLogger("app.main")
    prewarm_task: asyncio.Task | None = None
    try:
        from app.agent.sandbox_workspace_access import get_shared_sandbox_service

        sandbox_service = get_shared_sandbox_service()
        log.info("sandbox_backend_startup=%s", sandbox_service.backend_label())
        log.info(
            "sandbox_images_config standard=%s playwright=%s base=%s",
            os.getenv("SANDBOX_STANDARD_IMAGE", ""),
            os.getenv("SANDBOX_PLAYWRIGHT_IMAGE", ""),
            os.getenv("SANDBOX_BASE_IMAGE", ""),
        )
        always_on = is_truthy_env("SANDBOX_ALWAYS_ON", "0")
        prewarm_enabled = is_truthy_env("SANDBOX_PREWARM_ALL_USERS", "1" if always_on else "0")
        if prewarm_enabled:
            async def prewarm_all_users() -> None:
                result = await sandbox_service.prewarm_all_known_users(reason="startup")
                log.info(
                    "sandbox_prewarm_all_users_done users_total=%s ok=%s failed=%s",
                    result.get("users_total", 0),
                    result.get("ok", 0),
                    result.get("failed", 0),
                )

            prewarm_task = asyncio.create_task(prewarm_all_users())
    except Exception as e:
        log.exception("sandbox_backend_startup_failed: %s", e)
        raise
    from app.core.init import ensure_mcp_and_skills_initialized

    await ensure_mcp_and_skills_initialized()
    yield
    if prewarm_task is not None and not prewarm_task.done():
        prewarm_task.cancel()
    await cleanup_all_mcp_runtimes()
