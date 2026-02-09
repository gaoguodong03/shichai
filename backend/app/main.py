"""FastAPI 应用入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import chat, settings, files
from app.mcp.manager import get_mcp_manager
from dotenv import load_dotenv
import os
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
    title="DHA API",
    description="Digital Human Agent - Chat API with MCP and Skills",
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

@app.get("/")
async def root():
    return {"message": "DHA API", "version": "0.1.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
