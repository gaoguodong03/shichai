"""认证 API - SQLite 用户库 + 简单 JWT token

说明：本模块的登录/注册凭证校验由 `backend/app/core/auth_db.py` 负责，
密码以 hash 形式存储并对多用户隔离生效。
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone

from app.core.security import create_access_token
from app.core.auth_db import create_user, verify_user, user_exists
from app.core.users_store import ensure_user_profile

router = APIRouter(tags=["auth"])


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
async def login(body: LoginBody):
    """校验用户名密码，成功返回 access_token + 用户信息，失败返回 401"""
    name = body.username.strip()
    if not verify_user(username=name, password=body.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 确保有用户档案（users.json）
    created_at = datetime.now(timezone.utc).isoformat()
    profile = ensure_user_profile(name, created_at=created_at)

    token = create_access_token(name)
    return {
        "status": "ok",
        "data": {
            "username": name,
            "display_name": profile.display_name or name,
            "access_token": token,
            "token_type": "bearer",
        },
    }


@router.post("/auth/register")
async def register(body: RegisterBody):
    """创建新账户：写入用户文件，并初始化用户档案"""
    name = body.username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if user_exists(username=name):
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 写入 SQLite 用户表（密码以 PBKDF2 hash 形式存储）
    try:
        create_user(username=name, password=body.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="用户名已存在")

    created_at = datetime.now(timezone.utc).isoformat()
    profile = ensure_user_profile(name, created_at=created_at)

    token = create_access_token(name)
    return {
        "status": "ok",
        "data": {
            "username": name,
            "display_name": profile.display_name or name,
            "access_token": token,
            "token_type": "bearer",
        },
    }
