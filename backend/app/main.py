"""FastAPI 应用入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.api import chat, settings, files, auth, dha, group_chat
from app.mcp.manager import get_mcp_manager
from dotenv import load_dotenv
import os
from pathlib import Path
from contextlib import asynccontextmanager

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    yield
    # 关闭时清理 MCP 连接
    await get_mcp_manager().cleanup()

app = FastAPI(
    title="心像 EchoTwin API",
    description="EchoTwin - Personal AI Twin with MCP and Skills",
    version="0.1.0",
    lifespan=lifespan
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

# 注册路由
app.include_router(chat.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(dha.router, prefix="/api")
app.include_router(group_chat.router, prefix="/api")

# Docker/生产：挂载前端静态并 SPA 回退
_static_dir = os.getenv("STATIC_DIR")
if _static_dir and Path(_static_dir).is_dir():
    app.mount("/assets", StaticFiles(directory=Path(_static_dir) / "assets"), name="assets")
    _index = Path(_static_dir) / "index.html"
    @app.get("/")
    async def index():
        return FileResponse(_index)
    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """前端路由回退：非 API、非 assets 的请求返回 index.html"""
        if path.startswith("api"):
            from fastapi import HTTPException
            raise HTTPException(404)
        f = Path(_static_dir) / path
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
