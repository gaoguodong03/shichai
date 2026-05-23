"""用户上下文与多租户路径管理。

单进程多用户：每个用户独占 `data/users/{user_id}/`（资源、会话、工作区、密钥）。
测试可通过环境变量 `SHUTONG_USER_DATA_ROOT` 指向临时目录，避免污染仓库数据。

请求内通过 ContextVar 保存当前用户身份；读写磁盘时统一从 UserContext 取路径。
"""

from __future__ import annotations

import json
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple


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
    sessions_dir:  会话历史、运行状态与 workspace
    vault_dir:     密钥存储目录
    config_dir:    过渡期配置目录，后续资源迁移阶段逐步收敛
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
    vault_dir: Path
    sessions_dir: Path
    agent_outputs_dir: Path
    config_dir: Path
    skills_dir: Path


_user_ctx_cache: Dict[Tuple[str, str], UserContext] = {}


DEFAULT_SANDBOX_REQUIREMENTS = """pendulum==3.2.0
python-pptx==1.0.2
httpx
typing_extensions
pandas
openpyxl
xlrd
"""


def ensure_default_sandbox_requirements(username: str) -> None:
    """Ensure each user has a sandbox requirements.txt file without overwriting edits."""
    name = (username or "").strip()
    if not name:
        return
    base = users_data_root() / name
    path = (base / "config" / "sandbox" / "requirements.txt").resolve()
    try:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(DEFAULT_SANDBOX_REQUIREMENTS, encoding="utf-8")
    except Exception:
        pass


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
        vault_dir=data_root / "vault",
        sessions_dir=data_root / "sessions",
        agent_outputs_dir=data_root / "sessions",
        config_dir=data_root / "config",
    )


def _build_user_context(user_id: str, username: str = "") -> UserContext:
    """构造并缓存某个用户的路径定义。"""
    uid = (user_id or "").strip() or "free4inno"
    name = (username or "").strip() or uid
    key = (uid, name)
    if key in _user_ctx_cache:
        return _user_ctx_cache[key]

    ctx = build_user_context(user_id=uid, username=name)

    # 尽量提前创建基础目录，但失败也不影响后续按需 mkdir
    try:
        ensure_user_resource_layout(user_id=uid, username=name)
        ctx.sessions_dir.mkdir(parents=True, exist_ok=True)
        ctx.config_dir.mkdir(parents=True, exist_ok=True)
        ensure_default_sandbox_requirements(uid)
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
    """显式获取某个 user_id 对应的 UserContext，不依赖请求上下文。"""
    return _build_user_context(username, username)


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
        ctx.vault_dir,
        ctx.config_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    if not ctx.profile_path.exists():
        payload = {
            "user_id": ctx.user_id,
            "username": ctx.username,
        }
        ctx.profile_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return ctx


def ensure_empty_session_presets(username: str) -> None:
    """新账号不预置会话快捷场景；已有本地数据时不覆盖。"""
    name = (username or "").strip()
    if not name:
        return
    ctx = get_user_context_for(name)
    path = (ctx.config_dir / "session_presets.json").resolve()
    try:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="utf-8")
    except Exception:
        pass
