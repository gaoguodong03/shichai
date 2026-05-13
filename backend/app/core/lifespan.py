"""FastAPI 生命周期管理。"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.runtime_env import is_truthy_env
from app.mcp.manager import cleanup_all_mcp_runtimes


def _startup_prewarm_all_users_enabled() -> bool:
    return is_truthy_env("SANDBOX_PREWARM_ALL_USERS", "0")


def _startup_prewarm_timeout_ms() -> int:
    raw = (
        os.getenv("SANDBOX_PREWARM_ALL_USERS_TIMEOUT_MS")
        or os.getenv("SANDBOX_LOGIN_PREWARM_TIMEOUT_MS")
        or "600000"
    )
    try:
        return max(120_000, int(raw or "600000"))
    except ValueError:
        logging.getLogger("app.main").warning(
            "sandbox_env_invalid_int name=SANDBOX_PREWARM_ALL_USERS_TIMEOUT_MS value=%s",
            raw,
        )
        return 600_000


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
    logging.getLogger("httpx").setLevel(logging.WARNING)
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
        prewarm_enabled = _startup_prewarm_all_users_enabled()
        if prewarm_enabled:
            async def prewarm_all_users() -> None:
                timeout_ms = _startup_prewarm_timeout_ms()
                log.info("sandbox_prewarm_all_users_start timeout_ms=%s", timeout_ms)
                result = await sandbox_service.prewarm_all_known_users(reason="startup", timeout_ms=timeout_ms)
                log.info(
                    "sandbox_prewarm_all_users_done users_total=%s ok=%s failed=%s timeout_ms=%s",
                    result.get("users_total", 0),
                    result.get("ok", 0),
                    result.get("failed", 0),
                    timeout_ms,
                )

            prewarm_task = asyncio.create_task(prewarm_all_users())
        else:
            log.info("sandbox_prewarm_all_users_disabled")
    except Exception as e:
        log.exception("sandbox_backend_startup_failed: %s", e)
        raise
    from app.core.init import ensure_mcp_and_skills_initialized

    await ensure_mcp_and_skills_initialized()
    yield
    if prewarm_task is not None and not prewarm_task.done():
        prewarm_task.cancel()
    await cleanup_all_mcp_runtimes()
