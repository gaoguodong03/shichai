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

