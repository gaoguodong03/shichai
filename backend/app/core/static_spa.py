"""前端静态资源挂载与 SPA 回退。"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_static_spa(app: FastAPI) -> bool:
    """挂载 STATIC_DIR 指向的前端构建产物；成功返回 True。"""
    static_dir = os.getenv("STATIC_DIR")
    if not static_dir or not Path(static_dir).is_dir():
        return False

    static_root = Path(static_dir)
    app.mount("/assets", StaticFiles(directory=static_root / "assets"), name="assets")
    index_file = static_root / "index.html"

    @app.get("/")
    async def index():
        return FileResponse(index_file)

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """前端路由回退：非 API、非 assets 的请求返回 index.html。"""
        if path.startswith("api"):
            raise HTTPException(404)
        file_path = static_root / path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(index_file)

    return True
