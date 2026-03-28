"""简单的 JSON 用户信息存储。

仅存放用户 profile / 元信息，不存放密码（密码仍由 auth_users.txt 管理）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional


_USERS_FILE = Path(__file__).resolve().parents[2] / "config" / "users.json"


@dataclass
class UserProfile:
    username: str
    display_name: str = ""
    created_at: str = ""


def _load_all() -> Dict[str, UserProfile]:
    if not _USERS_FILE.exists():
        return {}
    try:
        raw = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
        result: Dict[str, UserProfile] = {}
        if isinstance(raw, dict):
            for name, data in raw.items():
                if not isinstance(data, dict):
                    continue
                result[name] = UserProfile(
                    username=name,
                    display_name=str(data.get("display_name") or name),
                    created_at=str(data.get("created_at") or ""),
                )
        return result
    except Exception:
        return {}


def _save_all(users: Dict[str, UserProfile]) -> None:
    _USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {name: asdict(profile) for name, profile in users.items()}
    _USERS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_user_profile(username: str) -> Optional[UserProfile]:
    users = _load_all()
    return users.get(username)


def ensure_user_profile(username: str, created_at: str = "") -> UserProfile:
    """若不存在则创建一个最小用户档案。"""
    username = (username or "").strip()
    if not username:
        raise ValueError("username is required")
    users = _load_all()
    if username in users:
        return users[username]
    profile = UserProfile(username=username, display_name=username, created_at=created_at)
    users[username] = profile
    _save_all(users)
    return profile


def remove_user_profile(username: str) -> bool:
    """从 users.json 移除用户档案。返回是否曾存在并已删除。"""
    name = (username or "").strip()
    if not name:
        raise ValueError("username is required")
    users = _load_all()
    if name not in users:
        return False
    del users[name]
    _save_all(users)
    return True


def rename_user_profile(old_username: str, new_username: str) -> UserProfile:
    """重命名 users.json 中的用户键，保留 display_name/created_at。"""
    old_name = (old_username or "").strip()
    new_name = (new_username or "").strip()
    if not old_name or not new_name:
        raise ValueError("username is required")
    users = _load_all()
    if new_name in users:
        raise ValueError("new username already exists")
    old_profile = users.pop(old_name, None)
    if old_profile is None:
        profile = UserProfile(username=new_name, display_name=new_name, created_at="")
    else:
        profile = UserProfile(
            username=new_name,
            display_name=new_name,
            created_at=old_profile.created_at,
        )
    users[new_name] = profile
    _save_all(users)
    return profile

