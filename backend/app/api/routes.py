"""API 路由注册入口。"""
from fastapi import FastAPI

from app.api import (
    auth,
    agents,
    files,
    group_chat,
    sandbox_settings,
    sessions,
    settings_app,
    settings_env_vars,
    settings_mcp,
    settings_presets,
    settings_skills,
)


def register_api_routes(app: FastAPI) -> None:
    """注册所有业务 API 路由。"""
    app.include_router(settings_skills.router, prefix="/api")
    app.include_router(settings_app.router, prefix="/api")
    app.include_router(settings_env_vars.router, prefix="/api")
    app.include_router(settings_mcp.router, prefix="/api")
    app.include_router(settings_presets.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    app.include_router(auth.router, prefix="/api")
    app.include_router(agents.router, prefix="/api")
    app.include_router(group_chat.router, prefix="/api")
    app.include_router(sessions.router, prefix="/api")
    app.include_router(sandbox_settings.router, prefix="/api")
