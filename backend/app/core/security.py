"""HTTP 层用户解析与 FastAPI 依赖。

默认：**必须**携带有效 `Authorization: Bearer <token>`（由 /api/auth/login|register 签发），
否则返回 401，避免未登录请求落到共享默认用户。

本地调试可设置环境变量 `ALLOW_ANONYMOUS_API=1`：无 token 时回退 `X-User-Name` 或 `free4inno`
（不安全，勿用于生产）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException

from app.core.user_context import (
    UserContext,
    get_current_user_context,
    reset_current_user_identity,
    set_current_user_identity,
)

logger = logging.getLogger(__name__)


@dataclass
class CurrentUser:
    """对外暴露的当前用户信息（给路由使用）。"""

    user_id: str
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


def _allow_anonymous_api() -> bool:
    return os.getenv("ALLOW_ANONYMOUS_API", "").strip().lower() in ("1", "true", "yes", "on")


def _prewarm_on_user_request_enabled() -> bool:
    return False


def _default_access_token_expire_minutes() -> int:
    """默认 30 天；可通过环境变量 ACCESS_TOKEN_EXPIRE_MINUTES 覆盖（单位：分钟）。"""
    raw = os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return 60 * 24 * 30


def create_access_token(username: str, expires_minutes: int | None = None) -> str:
    """新建一个简单的 HMAC-SHA256 JWT 兼容 token，不依赖外部库。"""
    if expires_minutes is None:
        expires_minutes = _default_access_token_expire_minutes()
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
    """为受保护路由设置当前用户名与 UserContext：默认仅接受有效 Bearer token。"""
    username: Optional[str] = None

    if authorization:
        parts = authorization.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
            if not token.strip():
                raise HTTPException(status_code=401, detail="访问令牌不能为空")
            username = decode_access_token(token)
        else:
            raise HTTPException(status_code=401, detail="Authorization 头格式错误，应为 Bearer <token>")
    elif _allow_anonymous_api():
        username = (x_user_name or "").strip() or "free4inno"
    else:
        raise HTTPException(
            status_code=401,
            detail="需要登录：请提供 Authorization: Bearer <token>（本地调试可设 ALLOW_ANONYMOUS_API=1）",
        )

    user_id = username
    try:
        from app.core.auth_db import get_user_by_username

        user_record = get_user_by_username(username)
        if user_record is not None and user_record.user_id:
            user_id = user_record.user_id
    except Exception:
        logger.warning("auth_user_id_resolve_failed username=%s", username, exc_info=True)

    token_ctx = set_current_user_identity(user_id=user_id, username=username)
    try:
        ctx = get_current_user_context(default_fallback=True)
        if ctx is None:
            raise HTTPException(status_code=401, detail="未能解析当前用户上下文")
        yield CurrentUser(user_id=user_id, username=username, ctx=ctx)
    finally:
        reset_current_user_identity(token_ctx)


def get_current_user() -> CurrentUser:
    """给非路由代码使用的辅助函数，通过 ContextVar 获取当前用户。

    注意：必须运行在已经经过 `user_context_dependency` 的请求上下文内，否则会回退到默认用户。
    """
    ctx = get_current_user_context(default_fallback=True)
    if ctx is None:
        raise RuntimeError("当前没有可用的 UserContext，请确保在请求上下文内调用。")
    return CurrentUser(user_id=ctx.user_id, username=ctx.username, ctx=ctx)
