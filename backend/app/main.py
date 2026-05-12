"""FastAPI 应用入口。"""
import os
import sys

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import register_api_routes
from app.core.dev_bootstrap import auto_bootstrap_opensandbox, reuse_existing_backend
from app.core.lifespan import lifespan
from app.core.runtime_env import prepare_runtime_env
from app.core.static_spa import mount_static_spa


prepare_runtime_env()


def create_app() -> FastAPI:
    app = FastAPI(
        title="书童四九 API",
        description="书童四九 — 多用户隔离的 Agent 对话与工具平台（MCP / Skills）",
        version="0.1.0",
        lifespan=lifespan,
    )

    cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_api_routes(app)

    if not mount_static_spa(app):
        @app.get("/")
        async def root():
            return {"message": "书童四九 API", "version": "0.1.0"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("APP_HOST", "0.0.0.0")
    port = int(os.getenv("APP_PORT", "8000"))
    probe_host = "127.0.0.1" if host == "0.0.0.0" else host
    if reuse_existing_backend(probe_host, port):
        sys.exit(0)
    auto_bootstrap_opensandbox()
    uvicorn.run(app, host=host, port=port)
