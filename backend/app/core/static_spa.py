"""前端静态资源挂载与 SPA 回退。"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers
from starlette.staticfiles import NotModifiedResponse


LONG_LIVED_STATIC_CACHE = "public, max-age=31536000, immutable"
HTML_CACHE = "no-cache"


class CachedStaticFiles(StaticFiles):
    def __init__(self, *args, cache_control: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    def file_response(self, full_path, stat_result, scope, status_code=200):
        request_headers = Headers(scope=scope)
        response = FileResponse(
            full_path,
            status_code=status_code,
            stat_result=stat_result,
            headers={"Cache-Control": self.cache_control},
        )
        if self.is_not_modified(response.headers, request_headers):
            return NotModifiedResponse(response.headers)
        return response


def _cache_headers_for_spa_path(path: str) -> dict[str, str]:
    normalized = path.lstrip("/")
    if normalized.startswith("expert-avatars/"):
        return {"Cache-Control": LONG_LIVED_STATIC_CACHE}
    if normalized.endswith(".html"):
        return {"Cache-Control": HTML_CACHE}
    return {}


def mount_static_spa(app: FastAPI) -> bool:
    """挂载 STATIC_DIR 指向的前端构建产物；成功返回 True。"""
    static_dir = os.getenv("STATIC_DIR")
    if not static_dir or not Path(static_dir).is_dir():
        return False

    static_root = Path(static_dir)
    app.mount(
        "/assets",
        CachedStaticFiles(directory=static_root / "assets", cache_control=LONG_LIVED_STATIC_CACHE),
        name="assets",
    )
    index_file = static_root / "index.html"

    @app.get("/")
    async def index():
        return FileResponse(index_file, headers={"Cache-Control": HTML_CACHE})

    @app.get("/{path:path}")
    async def spa_fallback(path: str):
        """前端路由回退：非 API、非 assets 的请求返回 index.html。"""
        if path.startswith("api"):
            raise HTTPException(404)
        file_path = static_root / path
        if file_path.is_file():
            return FileResponse(file_path, headers=_cache_headers_for_spa_path(path))
        return FileResponse(index_file, headers={"Cache-Control": HTML_CACHE})

    return True
