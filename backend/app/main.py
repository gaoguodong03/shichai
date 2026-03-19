"""FastAPI 应用入口"""
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api import settings, files, auth, dha, group_chat, sessions
from app.core.security import user_context_dependency
from app.mcp.manager import get_mcp_manager
from dotenv import load_dotenv
import os
from pathlib import Path
from contextlib import asynccontextmanager

# 显式加载 backend/.env（__file__ 为 app/main.py，parent.parent 为 backend）
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)
load_dotenv()  # 仍从 cwd 再加载一次，兼容在 backend 目录下启动

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。MCP 必须在 lifespan 内初始化与清理，保证 enter/exit 在同一 asyncio 任务，否则 anyio 会报 cancel scope 跨任务错误。"""
    from app.core.init import ensure_mcp_and_skills_initialized
    # 启动时：在 lifespan 任务中初始化 MCP/Skills，与下方 cleanup 同一任务
    await ensure_mcp_and_skills_initialized()
    yield
    # 关闭时：在同一任务中清理 MCP 连接，避免 RuntimeError: exit cancel scope in a different task
    await get_mcp_manager().cleanup()

app = FastAPI(
    title="心像 EchoTwin API",
    description="EchoTwin - Expert Collaboration Platform with MCP and Skills",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(user_context_dependency)],
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

# 注册路由（单聊 chat 已下线，统一使用 sessions + group_chat）
app.include_router(settings.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(dha.router, prefix="/api")
app.include_router(group_chat.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")

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
        return {"message": "心像 EchoTwin API", "version": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
