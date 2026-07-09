"""认证 API - SQLite 用户库 + 简单 JWT token

说明：本模块的登录/注册凭证校验由 `backend/app/core/auth_db.py` 负责，
密码以 hash 形式存储并对多用户隔离生效。
"""

import re

from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone

from app.api.request_models import StrictRequestModel
from app.core.security import create_access_token, CurrentUser, user_context_dependency
from app.core.auth_db import create_user, get_user_by_username, verify_user, user_exists, update_password, rename_user
from app.core.users_store import ensure_user_profile, rename_user_profile
from app.core.user_context import ensure_empty_session_presets, ensure_user_resource_layout, write_user_profile

router = APIRouter(tags=["auth"])
PHONE_REGEX = re.compile(r"^1[3-9]\d{9}$")
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_valid_account(value: str) -> bool:
    return bool(PHONE_REGEX.match(value) or EMAIL_REGEX.match(value))


class LoginBody(StrictRequestModel):
    username: str
    password: str


class RegisterBody(StrictRequestModel):
    username: str
    password: str


class ChangeAccountBody(StrictRequestModel):
    new_username: str
    current_password: str


class ChangePasswordBody(StrictRequestModel):
    current_password: str
    new_password: str


@router.post("/auth/login")
async def login(body: LoginBody):
    """校验用户名密码，成功返回 access_token + 用户信息，失败返回 401"""
    name = body.username.strip()
    if not _is_valid_account(name):
        raise HTTPException(status_code=400, detail="账号格式不正确，请输入手机号或电子邮箱")
    if not verify_user(username=name, password=body.password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 确保有用户档案（users.json）
    created_at = datetime.now(timezone.utc).isoformat()
    profile = ensure_user_profile(name, created_at=created_at)
    user_record = get_user_by_username(name)
    user_id = user_record.user_id if user_record is not None else ""
    if user_id:
        ensure_user_resource_layout(user_id=user_id, username=name)

    token = create_access_token(name)
    return {
        "status": "ok",
        "data": {
            "username": name,
            "user_id": user_id,
            "display_name": profile.display_name or name,
            "access_token": token,
            "token_type": "bearer",
        },
    }


@router.put("/auth/account")
@router.post("/auth/account")
async def change_account(body: ChangeAccountBody, current_user: CurrentUser = Depends(user_context_dependency)):
    old_name = (current_user.username or "").strip()
    new_name = (body.new_username or "").strip()
    current_password = body.current_password or ""
    if not old_name:
        raise HTTPException(status_code=401, detail="未登录")
    if not new_name:
        raise HTTPException(status_code=400, detail="新账号不能为空")
    if not _is_valid_account(new_name):
        raise HTTPException(status_code=400, detail="账号格式不正确，请输入手机号或电子邮箱")
    if old_name == new_name:
        raise HTTPException(status_code=400, detail="新账号与当前账号相同")
    if not verify_user(username=old_name, password=current_password):
        raise HTTPException(status_code=400, detail="当前密码错误")
    if user_exists(username=new_name):
        raise HTTPException(status_code=400, detail="账号已存在")

    try:
        user_id = current_user.user_id
        rename_user(old_username=old_name, new_username=new_name)
        profile = rename_user_profile(old_name, new_name)
        if user_id:
            write_user_profile(user_id=user_id, username=new_name)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"修改账号失败: {e}")

    token = create_access_token(new_name)
    return {
        "status": "ok",
        "data": {
            "user_id": current_user.user_id,
            "username": new_name,
            "display_name": profile.display_name or new_name,
            "access_token": token,
            "token_type": "bearer",
        },
    }


@router.put("/auth/password")
@router.post("/auth/password")
async def change_password(body: ChangePasswordBody, current_user: CurrentUser = Depends(user_context_dependency)):
    username = (current_user.username or "").strip()
    current_password = body.current_password or ""
    new_password = body.new_password or ""
    if not username:
        raise HTTPException(status_code=401, detail="未登录")
    if len(new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码至少 6 位")
    if not verify_user(username=username, password=current_password):
        raise HTTPException(status_code=400, detail="当前密码错误")
    if current_password == new_password:
        raise HTTPException(status_code=400, detail="新密码不能与当前密码相同")

    try:
        update_password(username=username, new_password=new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"修改密码失败: {e}")

    token = create_access_token(username)
    return {
        "status": "ok",
        "data": {
            "user_id": current_user.user_id,
            "username": username,
            "access_token": token,
            "token_type": "bearer",
        },
    }


@router.post("/auth/register")
async def register(body: RegisterBody):
    """新建新账户：写入用户文件，并初始化用户档案"""
    name = body.username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if not _is_valid_account(name):
        raise HTTPException(status_code=400, detail="账号格式不正确，请输入手机号或电子邮箱")
    if user_exists(username=name):
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 写入 SQLite 用户表（密码以 PBKDF2 hash 形式存储）
    try:
        create_user(username=name, password=body.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="用户名已存在")

    created_at = datetime.now(timezone.utc).isoformat()
    profile = ensure_user_profile(name, created_at=created_at)
    user_record = get_user_by_username(name)
    user_id = user_record.user_id if user_record is not None else ""
    if user_id:
        ensure_user_resource_layout(user_id=user_id, username=name)
        ensure_empty_session_presets(user_id)

    token = create_access_token(name)
    return {
        "status": "ok",
        "data": {
            "username": name,
            "user_id": user_id,
            "display_name": profile.display_name or name,
            "access_token": token,
            "token_type": "bearer",
        },
    }
