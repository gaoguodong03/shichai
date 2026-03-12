"""HTTP 层用户解析与 FastAPI 依赖。

当前版本采用简单的 Header 方案：
- 前端在每个请求上添加 `X-User-Name: <username>`；
- 若缺失，则回退到默认用户 `free4inno`（兼容现有单用户逻辑）；
- 只负责「身份标识」，不做严格安全认证（密码校验仍由 /auth/login 完成）。

这样可以在不大改前端的情况下，实现方案 A 的会话与资源命名空间隔离。
后续若要引入 JWT，只需在此处替换解析逻辑，其他模块继续通过 user_context 取路径即可。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException

from app.core.user_context import (
    UserContext,
    get_current_user_context,
    set_current_username,
    reset_current_username,
)


@dataclass
class CurrentUser:
    """对外暴露的当前用户信息（给路由使用）。"""

    username: str
    ctx: UserContext


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _get_auth_secret() -> bytes:
    """获取用于签名的密钥（简单版），生产环境请通过环境变量设置。"""
    secret = os.getenv("AUTH_SECRET", "dev-secret-change-me")
    return secret.encode("utf-8")


def create_access_token(username: str, expires_minutes: int = 60 * 24) -> str:
    """创建一个简单的 HMAC-SHA256 JWT 兼容 token，不依赖外部库。"""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload = {"sub": username, "iat": now, "exp": now + expires_minutes * 60}
    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    sig = hmac.new(_get_auth_secret(), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> str:
    """验证并解析 token，返回用户名；失败抛出 HTTPException 401。"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("invalid token format")
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
        expected_sig = hmac.new(_get_auth_secret(), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            raise ValueError("invalid signature")
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
        exp = int(payload.get("exp", 0))
        if exp and int(time.time()) > exp:
            raise ValueError("token expired")
        username = str(payload.get("sub") or "").strip()
        if not username:
            raise ValueError("empty subject")
        return username
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"无效或已过期的访问令牌: {e}")


async def user_context_dependency(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    x_user_name: Optional[str] = Header(default=None, alias="X-User-Name"),
):
    """全局依赖：为每个请求设置当前用户名与 UserContext。

    优先从 Authorization: Bearer <token> 中解析用户名；
    若未提供 token，则仅在开发/兼容场景下使用 X-User-Name 或回退到 free4inno。
    """
    username: Optional[str] = None

    # 1. 优先使用 Bearer token（推荐）
    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            username = decode_access_token(token)
        else:
            raise HTTPException(status_code=401, detail="Authorization 头格式错误，应为 Bearer <token>")

    # 2. 无 token 时，退回到 header / 默认用户（便于本地调试与兼容老前端）
    if not username:
        username = (x_user_name or "").strip() or "free4inno"

    token_ctx = set_current_username(username)
    try:
        ctx = get_current_user_context(default_fallback=True)
        if ctx is None:
            raise HTTPException(status_code=401, detail="未能解析当前用户上下文")
        yield CurrentUser(username=username, ctx=ctx)
    finally:
        reset_current_username(token_ctx)


def get_current_user() -> CurrentUser:
    """给非路由代码使用的辅助函数，通过 ContextVar 获取当前用户。

    注意：必须运行在已经经过 `user_context_dependency` 的请求上下文内，否则会回退到默认用户。
    """
    ctx = get_current_user_context(default_fallback=True)
    if ctx is None:
        raise RuntimeError("当前没有可用的 UserContext，请确保在请求上下文内调用。")
    return CurrentUser(username=ctx.username, ctx=ctx)

