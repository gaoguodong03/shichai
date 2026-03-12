"""认证 API - 文本文件账密 + 简单 JWT token"""
import os
from pathlib import Path
from typing import Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone

from app.core.security import create_access_token
from app.core.users_store import ensure_user_profile

router = APIRouter(tags=["auth"])

# 用户列表文件：每行格式为 username:password，默认 backend/config/auth_users.txt
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
AUTH_USERS_FILE = os.getenv("AUTH_USERS_FILE", str(_BACKEND_DIR / "config" / "auth_users.txt"))


def _load_users() -> Dict[str, str]:
    """读取用户文件，返回 username -> password 映射"""
    path = Path(AUTH_USERS_FILE)
    if path.is_absolute():
        p = path
    else:
        p = (_BACKEND_DIR / path).resolve()
    if not p.exists():
        return {}
    result = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            user, _, pwd = line.partition(":")
            result[user.strip()] = pwd.strip()
    return result


def _users_file_path() -> Path:
    path = Path(AUTH_USERS_FILE)
    return path if path.is_absolute() else (_BACKEND_DIR / path).resolve()


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
    users = _load_users()
    pwd = users.get(name)
    if pwd is None or pwd != body.password:
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
    pwd = body.password
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    users = _load_users()
    if name in users:
        raise HTTPException(status_code=400, detail="用户名已存在")
    path = _users_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}:{pwd}\n")

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
