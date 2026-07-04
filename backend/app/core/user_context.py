"""用户上下文与多租户路径管理。

单进程多用户：每个用户独占 `data/users/{user_id}/`（资源、设置、会话）。
测试可通过环境变量 `SHUTONG_USER_DATA_ROOT` 指向临时目录，避免污染仓库数据。

请求内通过 ContextVar 保存当前用户身份；读写磁盘时统一从 UserContext 取路径。
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from app.core.atomic_json import atomic_write_json


_current_username: ContextVar[Optional[str]] = ContextVar("current_username", default=None)
_current_user_id: ContextVar[Optional[str]] = ContextVar("current_user_id", default=None)


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def users_data_root() -> Path:
    """用户数据根目录，默认 backend/data/users；测试可设 SHUTONG_USER_DATA_ROOT。"""
    default = str(_backend_dir() / "data" / "users")
    return Path(os.getenv("SHUTONG_USER_DATA_ROOT", default)).resolve()


@dataclass
class UserContext:
    """当前用户的资源根路径定义。

    base_dir:      SHUTONG_USER_DATA_ROOT/{user_id}
    resources_dir: 用户可管理、可导入导出的资源中心目录
    settings_dir:  用户偏好、密钥与 sandbox 设置
    sessions_dir:  会话历史、运行状态与 workspace
    """

    user_id: str
    username: str
    base_dir: Path
    profile_path: Path
    resources_dir: Path
    scenarios_dir: Path
    agents_dir: Path
    tools_dir: Path
    models_dir: Path
    settings_dir: Path
    sessions_dir: Path
    agent_outputs_dir: Path
    skills_dir: Path


_user_ctx_cache: Dict[Tuple[str, str], UserContext] = {}


def set_current_username(username: str) -> object:
    """在当前请求上下文中设置用户名，返回 token 以便恢复。"""
    username = (username or "").strip() or "free4inno"
    token = set_current_user_identity(user_id=username, username=username)
    return token


def set_current_user_identity(*, user_id: str, username: str = "") -> object:
    """在当前请求上下文中设置用户身份，返回 token 以便恢复。"""
    uid = (user_id or "").strip() or "free4inno"
    name = (username or "").strip() or uid
    token_username = _current_username.set(name)
    token_user_id = _current_user_id.set(uid)
    return token_username, token_user_id


def reset_current_username(token: object) -> None:
    """恢复先前的用户名上下文。"""
    reset_current_user_identity(token)


def reset_current_user_identity(token: object) -> None:
    """恢复先前的用户身份上下文。"""
    try:
        token_username, token_user_id = token  # type: ignore[misc]
        _current_user_id.reset(token_user_id)  # type: ignore[arg-type]
        _current_username.reset(token_username)  # type: ignore[arg-type]
    except Exception:
        # 出错不应影响主流程
        pass


def get_current_username() -> Optional[str]:
    """获取当前请求内的用户名（可能为 None）。"""
    return _current_username.get()


def get_current_user_id() -> Optional[str]:
    """获取当前请求内的 user_id（可能为 None）。"""
    return _current_user_id.get()


def build_user_context(*, user_id: str, username: str = "") -> UserContext:
    """构造某个用户的标准路径定义。"""
    uid = (user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    name = (username or "").strip() or uid
    data_root = (users_data_root() / uid).resolve()
    resources_dir = data_root / "resources"
    settings_dir = data_root / "settings"
    return UserContext(
        user_id=uid,
        username=name,
        base_dir=data_root,
        profile_path=data_root / "profile.json",
        resources_dir=resources_dir,
        scenarios_dir=resources_dir / "scenarios",
        agents_dir=resources_dir / "agents",
        skills_dir=resources_dir / "skills",
        tools_dir=resources_dir / "tools",
        models_dir=resources_dir / "models",
        settings_dir=settings_dir,
        sessions_dir=data_root / "sessions",
        agent_outputs_dir=data_root / "sessions",
    )


def _build_user_context(user_id: str, username: str = "") -> UserContext:
    """构造并缓存某个用户的路径定义。"""
    uid = (user_id or "").strip() or "free4inno"
    name = (username or "").strip() or uid
    key = (uid, name)
    if key in _user_ctx_cache:
        return _user_ctx_cache[key]

    ctx = build_user_context(user_id=uid, username=name)

    # 尽量提前新建基础目录，但失败也不影响后续按需 mkdir
    try:
        ensure_user_resource_layout(user_id=uid, username=name)
        ctx.sessions_dir.mkdir(parents=True, exist_ok=True)
        ctx.settings_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    _user_ctx_cache[key] = ctx
    return ctx


def get_current_user_context(default_fallback: bool = True) -> Optional[UserContext]:
    """获取当前请求的 UserContext。

    - 若当前没有设置用户名且 default_fallback=True，则回退为 'free4inno'；
    - 若 default_fallback=False，则在未设置用户名时返回 None。
    """
    username = get_current_username()
    user_id = get_current_user_id()
    if not user_id:
        if not default_fallback:
            return None
        user_id = "free4inno"
        username = username or "free4inno"
    return _build_user_context(user_id, username or user_id)


def get_user_context_for(username: str) -> UserContext:
    """显式获取某个用户的 UserContext，不依赖请求上下文。

    兼容旧调用点传入登录名的情况：若 SQLite 认证库中存在该账号，
    使用其稳定 user_id 作为物理目录名，避免重新新建 username 目录。
    """
    ident = (username or "").strip()
    if not ident:
        return _build_user_context("", "")
    try:
        from app.core.auth_db import get_user_by_username

        user_record = get_user_by_username(ident)
        if user_record is not None and user_record.user_id:
            return _build_user_context(user_record.user_id, user_record.username or ident)
    except Exception:
        pass
    return _build_user_context(ident, ident)


def ensure_user_resource_layout(*, user_id: str, username: str = "") -> UserContext:
    """初始化用户资源根目录，不覆盖已有 profile。"""
    ctx = build_user_context(user_id=user_id, username=username)
    for path in (
        ctx.scenarios_dir,
        ctx.agents_dir,
        ctx.skills_dir,
        ctx.tools_dir,
        ctx.models_dir,
        ctx.sessions_dir,
        ctx.settings_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    if not ctx.profile_path.exists():
        write_user_profile(user_id=ctx.user_id, username=ctx.username)
    return ctx


def write_user_profile(*, user_id: str, username: str) -> UserContext:
    """写入用户资源根下的 profile.json。"""
    ctx = build_user_context(user_id=user_id, username=username)
    ctx.profile_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "user_id": ctx.user_id,
        "username": ctx.username,
    }
    atomic_write_json(ctx.profile_path, payload)
    return ctx


def ensure_empty_session_presets(username: str) -> None:
    """场景以 resources/scenarios 为唯一来源；新账号不再生成 presets 聚合文件。"""
    return
