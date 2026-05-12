"""用户级设置文件路径。"""
from __future__ import annotations

from pathlib import Path

from app.core.user_context import get_current_user_context


def require_user_context():
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法读取用户级设置目录。")
    return user_ctx


def app_settings_path() -> Path:
    return (require_user_context().config_dir / "app_settings.json").resolve()


def api_secrets_path() -> Path:
    return (require_user_context().config_dir / "api_secrets.json").resolve()


def mcp_config_path() -> Path:
    return (require_user_context().config_dir / "mcp_servers.json").resolve()


def session_presets_path() -> Path:
    return (require_user_context().config_dir / "session_presets.json").resolve()


def sandbox_requirements_path() -> Path:
    return (require_user_context().config_dir / "sandbox" / "requirements.txt").resolve()


def skills_dir_path() -> Path:
    return require_user_context().skills_dir.resolve()
