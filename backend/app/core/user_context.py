"""用户上下文与多租户路径管理。

单进程多用户：每个用户独占 `data/users/{username}/`（会话、工作区、配置、技能副本）。
测试可通过环境变量 `SHUTONG_USER_DATA_ROOT` 指向临时目录，避免污染仓库数据。

请求内通过 ContextVar 保存当前用户名；读写磁盘时统一从 UserContext 取路径。
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


_current_username: ContextVar[Optional[str]] = ContextVar("current_username", default=None)


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def users_data_root() -> Path:
    """用户数据根目录，默认 backend/data/users；测试可设 SHUTONG_USER_DATA_ROOT。"""
    default = str(_backend_dir() / "data" / "users")
    return Path(os.getenv("SHUTONG_USER_DATA_ROOT", default)).resolve()


@dataclass
class UserContext:
    """当前用户的资源根路径定义。

    base_dir:           SHUTONG_USER_DATA_ROOT/{username}
    sessions_dir:       会话与群聊存储
    agent_outputs_dir:  工作区与导出文件
    config_dir:         通用配置（app_settings、dha_instances 等）
    skills_dir:         用户技能目录
    """

    username: str
    base_dir: Path
    sessions_dir: Path
    agent_outputs_dir: Path
    config_dir: Path
    skills_dir: Path


_user_ctx_cache: Dict[str, UserContext] = {}


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
    return _current_username.set(username)


def reset_current_username(token: object) -> None:
    """恢复先前的用户名上下文。"""
    try:
        _current_username.reset(token)  # type: ignore[arg-type]
    except Exception:
        # 出错不应影响主流程
        pass


def get_current_username() -> Optional[str]:
    """获取当前请求内的用户名（可能为 None）。"""
    return _current_username.get()


def _build_user_context(username: str) -> UserContext:
    """构造并缓存某个用户的路径定义。"""
    username = (username or "").strip() or "free4inno"
    if username in _user_ctx_cache:
        return _user_ctx_cache[username]

    data_root = users_data_root() / username
    ctx = UserContext(
        username=username,
        base_dir=data_root,
        sessions_dir=data_root / "sessions",
        agent_outputs_dir=data_root / "agent-outputs",
        config_dir=data_root / "config",
        skills_dir=data_root / "skills",
    )

    # 尽量提前创建基础目录，但失败也不影响后续按需 mkdir
    try:
        ctx.sessions_dir.mkdir(parents=True, exist_ok=True)
        ctx.agent_outputs_dir.mkdir(parents=True, exist_ok=True)
        ctx.config_dir.mkdir(parents=True, exist_ok=True)
        ctx.skills_dir.mkdir(parents=True, exist_ok=True)
        ensure_default_sandbox_requirements(username)
    except Exception:
        pass

    _user_ctx_cache[username] = ctx
    return ctx


def get_current_user_context(default_fallback: bool = True) -> Optional[UserContext]:
    """获取当前请求的 UserContext。

    - 若当前没有设置用户名且 default_fallback=True，则回退为 'free4inno'；
    - 若 default_fallback=False，则在未设置用户名时返回 None。
    """
    username = get_current_username()
    if not username:
        if not default_fallback:
            return None
        username = "free4inno"
    return _build_user_context(username)


def get_user_context_for(username: str) -> UserContext:
    """显式获取某个用户名对应的 UserContext，不依赖请求上下文。"""
    return _build_user_context(username)


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
