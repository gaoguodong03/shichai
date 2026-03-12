"""用户上下文与多租户路径管理。

方案 A：单进程多用户隔离。
- 通过 HTTP 头部 `X-User-Name` 指定当前用户；
- 使用 ContextVar 在一次请求内保存当前用户名；
- 各模块在需要读写磁盘时，通过当前用户名派生出自己的根目录，形成「命名空间隔离」。

后续如果要演进到方案 B（每个用户一个进程），可以改为：
- 由进程启动参数/环境变量提供当前用户名；
- 同一套路径派生逻辑仍然可复用。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


_current_username: ContextVar[Optional[str]] = ContextVar("current_username", default=None)


@dataclass
class UserContext:
    """当前用户的资源根路径定义。

    base_dir:           data/users/{username}
    sessions_dir:       会话与群聊存储
    agent_outputs_dir:  工作区与导出文件
    config_dir:         通用配置目录（app_settings、dha_instances 等）
    skills_dir:         用户私有技能目录（可与全局 skills 叠加使用）
    """

    username: str
    base_dir: Path
    sessions_dir: Path
    agent_outputs_dir: Path
    config_dir: Path
    skills_dir: Path


_user_ctx_cache: Dict[str, UserContext] = {}


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

    # 以项目根目录为基准：backend/app/../.. -> 项目根
    backend_dir = Path(__file__).resolve().parents[2]

    # 兼容旧版单用户部署：
    # 对于 free4inno 用户，直接复用原来的全局目录结构，
    # 确保原有会话 / 工作区 / 配置 / skills 自动“映射”为该用户的数据。
    if username == "free4inno":
        data_root = backend_dir / "data"
        ctx = UserContext(
            username=username,
            base_dir=data_root,
            sessions_dir=data_root / "sessions",
            agent_outputs_dir=data_root / "agent-outputs",
            config_dir=backend_dir / "config",
            skills_dir=backend_dir / "skills",
        )
    else:
        # 新用户使用 data/users/{username} 目录树
        data_root = backend_dir / "data" / "users" / username
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

