"""FastAPI 生命周期管理。"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.mcp.manager import cleanup_all_mcp_runtimes


def _startup_prewarm_all_users_enabled() -> bool:
    return False


def _startup_orphan_cleanup_timeout_sec() -> int:
    raw = os.getenv("SANDBOX_ORPHAN_CLEANUP_TIMEOUT_SEC") or "30"
    try:
        return max(1, int(raw or "30"))
    except ValueError:
        logging.getLogger("app.main").warning(
            "sandbox_env_invalid_int name=SANDBOX_ORPHAN_CLEANUP_TIMEOUT_SEC value=%s",
            raw,
        )
        return 30


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
        try:
            cleanup_result = await asyncio.wait_for(
                sandbox_service.cleanup_orphan_sandboxes_on_startup(),
                timeout=_startup_orphan_cleanup_timeout_sec(),
            )
            log.info(
                "sandbox_orphan_cleanup_startup_result enabled=%s deleted=%s failed=%s",
                cleanup_result.get("enabled"),
                len(list(cleanup_result.get("deleted") or [])),
                len(list(cleanup_result.get("failed") or [])),
            )
        except asyncio.TimeoutError:
            log.warning("sandbox_orphan_cleanup_startup_timeout")
        except Exception as e:  # noqa: BLE001
            log.warning("sandbox_orphan_cleanup_startup_failed err=%s", e)
        log.info("sandbox_prewarm_all_users_removed")
    except Exception as e:
        log.exception("sandbox_backend_startup_failed: %s", e)
        raise
    from app.core.init import ensure_mcp_and_skills_initialized

    await ensure_mcp_and_skills_initialized()
    yield
    await cleanup_all_mcp_runtimes()
