"""FastAPI 应用入口"""
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api import settings, files, auth, dha, group_chat, sessions, public_scenario
from app.mcp.manager import cleanup_all_mcp_runtimes
from dotenv import load_dotenv
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from pathlib import Path
from contextlib import asynccontextmanager

# 显式加载 backend/.env（__file__ 为 app/main.py，parent.parent 为 backend）
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)
load_dotenv()  # 仍从 cwd 再加载一次，兼容在 backend 目录下启动


def _apply_runtime_env_defaults() -> None:
    """填充本地/默认部署所需环境变量；显式环境变量与 .env 优先。"""
    default_sandbox_image = "crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.11.1"
    if platform.machine().lower() in {"arm64", "aarch64"}:
        default_sandbox_image = "st49-skill-sandbox:local"
    defaults = {
        "OPENSANDBOX_DOMAIN": "127.0.0.1:8091",
        "OPENSANDBOX_PROTOCOL": "http",
        "OPENSANDBOX_USE_SERVER_PROXY": "0",
        "OPENSANDBOX_REQUEST_TIMEOUT_SEC": "900",
        "UNIFIED_TOOL_GATEWAY_ENABLED": "1",
        "SANDBOX_BASE_IMAGE": default_sandbox_image,
        "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
        "SANDBOX_FIXED_MEMORY_MB": "2048",
        "SANDBOX_ALLOW_NETWORK": "0",
        "SANDBOX_NETWORK_TOOL_ALLOWLIST": "run_skill_script",
        "SKILL_SCRIPT_TIMEOUT": "600",
        "SANDBOX_SCRIPT_GATEWAY_SLACK_MS": "600000",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_apply_runtime_env_defaults()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。MCP 必须在 lifespan 内初始化与清理，保证 enter/exit 在同一 asyncio 任务，否则 anyio 会报 cancel scope 跨任务错误。"""
    _lvl_name = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    _lvl = getattr(logging, _lvl_name, logging.INFO)
    logging.basicConfig(
        level=_lvl,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        force=True,
    )
    _log = logging.getLogger("app.main")
    prewarm_task: asyncio.Task | None = None
    try:
        from app.agent.sandbox_workspace_access import get_shared_sandbox_service

        sandbox_service = get_shared_sandbox_service()
        _log.info("sandbox_backend_startup=%s", sandbox_service.backend_label())
        always_on = _is_truthy_env("SANDBOX_ALWAYS_ON", "0")
        prewarm_enabled = _is_truthy_env("SANDBOX_PREWARM_ALL_USERS", "1" if always_on else "0")
        if prewarm_enabled:
            async def _prewarm_all_users() -> None:
                result = await sandbox_service.prewarm_all_known_users(reason="startup")
                _log.info(
                    "sandbox_prewarm_all_users_done users_total=%s ok=%s failed=%s",
                    result.get("users_total", 0),
                    result.get("ok", 0),
                    result.get("failed", 0),
                )

            prewarm_task = asyncio.create_task(_prewarm_all_users())
    except Exception as e:
        _log.exception("sandbox_backend_startup_failed: %s", e)
        raise
    from app.core.init import ensure_mcp_and_skills_initialized
    # 启动时：在 lifespan 任务中初始化 MCP/Skills，与下方 cleanup 同一任务
    await ensure_mcp_and_skills_initialized()
    yield
    if prewarm_task is not None and not prewarm_task.done():
        prewarm_task.cancel()
    # 关闭时：在同一任务中清理 MCP 连接，避免 RuntimeError: exit cancel scope in a different task
    await cleanup_all_mcp_runtimes()

app = FastAPI(
    title="书童四九 API",
    description="书童四九 — 多用户隔离的 Agent 对话与工具平台（MCP / Skills）",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 配置
cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由（统一会话：sessions；group_chat 提供归档等辅助路由与实现复用）
app.include_router(settings.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(dha.router, prefix="/api")
app.include_router(group_chat.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(public_scenario.router, prefix="/api")

# Docker/生产：挂载前端静态并 SPA 回退
_static_dir = os.getenv("STATIC_DIR")
if _static_dir and Path(_static_dir).is_dir():
    _static_root = Path(_static_dir)
    app.mount("/assets", StaticFiles(directory=_static_root / "assets"), name="assets")
    _index = _static_root / "index.html"
    @app.get("/")
    async def index():
        return FileResponse(_index)
    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """前端路由回退：非 API、非 assets 的请求返回 index.html"""
        if path.startswith("api"):
            from fastapi import HTTPException
            raise HTTPException(404)
        f = _static_root / path
        if f.is_file():
            return FileResponse(f)
        return FileResponse(_index)
else:
    @app.get("/")
    async def root():
        return {"message": "书童四九 API", "version": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}


def _can_connect(host: str, port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:  # nosec B310 - local health check only
            return 200 <= int(getattr(resp, "status", 0)) < 300
    except Exception:
        return False


def _is_truthy_env(name: str, default: str = "1") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_opensandbox_target() -> tuple[str, int]:
    raw = (os.getenv("OPENSANDBOX_DOMAIN") or os.getenv("OPEN_SANDBOX_DOMAIN") or "127.0.0.1:8091").strip()
    if "://" not in raw:
        raw = "http://" + raw
    parsed = urlparse(raw)
    host = parsed.hostname or "127.0.0.1"
    port = int(parsed.port or 8091)
    return host, port


def _auto_bootstrap_opensandbox() -> None:
    """Local dev bootstrap: auto `docker compose up -d opensandbox-server` when 8091 is unreachable."""
    if not _is_truthy_env("AUTO_START_OPENSANDBOX", "1"):
        return
    host, port = _parse_opensandbox_target()
    if _can_connect(host, port):
        return

    backend_root = Path(__file__).resolve().parent.parent
    repo_root = backend_root.parent
    compose_file = (os.getenv("OPENSANDBOX_COMPOSE_FILE") or "").strip()
    if compose_file:
        compose_path = Path(compose_file).expanduser()
        if not compose_path.is_absolute():
            compose_path = (repo_root / compose_path).resolve()
    else:
        candidates = [repo_root / "docker-compose.yml", repo_root / "docker-compose.1panel.yml"]
        compose_path = next((p for p in candidates if p.exists()), candidates[-1])

    print(f"[startup] OpenSandbox 不可达 {host}:{port}，尝试自动启动 docker compose: {compose_path} ...")
    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(compose_path), "up", "-d", "opensandbox-server"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as e:  # noqa: BLE001
        print(f"[startup] 自动启动 OpenSandbox 失败：{e}")
        return

    if proc.returncode != 0:
        out = (proc.stderr or proc.stdout or "").strip()
        print(f"[startup] 自动启动 OpenSandbox 失败：{out}")
        return

    for _ in range(20):
        if _can_connect(host, port) and _http_ok(f"http://{host}:{port}/health"):
            print("[startup] OpenSandbox 已就绪。")
            return
        time.sleep(0.5)
    print("[startup] OpenSandbox 仍未就绪，请检查 Docker Desktop 或 `docker compose logs opensandbox-server`。")


def _reuse_existing_backend(host: str, port: int) -> bool:
    """If backend already running, skip a second bind and exit gracefully."""
    if not _is_truthy_env("REUSE_EXISTING_BACKEND", "1"):
        return False
    if not _can_connect(host, port):
        return False
    if _http_ok(f"http://{host}:{port}/health"):
        print(f"[startup] 检测到后端已在运行：http://{host}:{port} ，本次不重复启动。")
        return True
    print(f"[startup] 端口 {port} 已被占用且不是当前服务，请先释放端口后重试。")
    return True


if __name__ == "__main__":
    import uvicorn

    _host = os.getenv("APP_HOST", "0.0.0.0")
    _port = int(os.getenv("APP_PORT", "8000"))
    _probe_host = "127.0.0.1" if _host == "0.0.0.0" else _host
    if _reuse_existing_backend(_probe_host, _port):
        sys.exit(0)
    _auto_bootstrap_opensandbox()
    uvicorn.run(app, host=_host, port=_port)
