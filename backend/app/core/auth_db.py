"""
SQLite 用户库（仅用于登录凭证）。

设计目标：
1. 轻量：不引入 SQLAlchemy，使用标准库 sqlite3。
2. 安全：密码以 PBKDF2-HMAC(SHA256)+salt 的形式存储。
3. 兼容：若数据库为空，自动从 config/auth_users.txt 进行一次性种子迁移。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AuthUserRecord:
    user_id: str
    username: str
    created_at: str


def _backend_root() -> Path:
    # backend/app/core/auth_db.py -> backend
    return Path(__file__).resolve().parents[2]


def get_auth_db_path() -> Path:
    # 按用户偏好放在 backend/config
    default_path = _backend_root() / "config" / "auth_users.sqlite"
    return Path(os.getenv("AUTH_DB_PATH", str(default_path))).resolve()


def get_auth_users_txt_path() -> Path:
    default_txt = _backend_root() / "config" / "auth_users.txt"
    env_path = os.getenv("AUTH_USERS_FILE", str(default_txt))
    p = Path(env_path)
    return p if p.is_absolute() else p.resolve()


def _get_sqlite_conn(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # autocommit 由显式 commit 控制，确保测试一致
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_auth_db() -> None:
    db_path = get_auth_db_path()
    with _get_sqlite_conn(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              user_id TEXT UNIQUE,
              username TEXT PRIMARY KEY,
              salt_b64 TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            """
        )
        _ensure_user_id_column(conn)
        conn.commit()


def _new_user_id() -> str:
    return f"user-{uuid.uuid4().hex}"


def _existing_resource_user_id_for_username(username: str) -> Optional[str]:
    target = (username or "").strip()
    if not target:
        return None
    try:
        from app.core.user_context import users_data_root

        root = users_data_root()
        if not root.exists():
            return None
        candidates: list[Path] = []
        for child in root.iterdir():
            if not child.is_dir():
                continue
            profile_path = child / "profile.json"
            if not profile_path.exists():
                continue
            try:
                data = json.loads(profile_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if str(data.get("username") or "").strip() == target:
                candidates.append(child)

        exact_dir = root / target
        if exact_dir.is_dir() and exact_dir not in candidates:
            candidates.append(exact_dir)

        if not candidates:
            return None

        candidates.sort(
            key=lambda p: (
                0 if p.name.startswith("user-") else 1,
                -int(p.stat().st_mtime_ns),
                p.name,
            )
        )
        return candidates[0].name
    except Exception:
        return None


def _user_id_available(conn: sqlite3.Connection, *, user_id: str, username: str) -> bool:
    row = conn.execute("SELECT username FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return True
    return str(row["username"] or "") == username


def _choose_user_id(conn: sqlite3.Connection, username: str) -> str:
    name = (username or "").strip()
    existing = _existing_resource_user_id_for_username(name)
    if existing and _user_id_available(conn, user_id=existing, username=name):
        return existing
    return _new_user_id()


def _ensure_user_id_column(conn: sqlite3.Connection) -> None:
    cols = {str(row["name"]) for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "user_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN user_id TEXT")
    rows = conn.execute("SELECT username, user_id FROM users").fetchall()
    for row in rows:
        if not str(row["user_id"] or "").strip():
            username = str(row["username"])
            conn.execute(
                "UPDATE users SET user_id = ? WHERE username = ?",
                (_choose_user_id(conn, username), username),
            )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_user_id ON users(user_id)")


def _load_users_from_txt() -> dict[str, str]:
    path = get_auth_users_txt_path()
    if not path.exists():
        return {}

    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            user, _, pwd = line.partition(":")
            result[user.strip()] = pwd.strip()
    return result


def _is_db_empty() -> bool:
    db_path = get_auth_db_path()
    if not db_path.exists():
        return True
    with _get_sqlite_conn(db_path) as conn:
        cur = conn.execute("SELECT COUNT(1) AS c FROM users")
        row = cur.fetchone()
        return int(row["c"] or 0) == 0


def seed_from_auth_users_txt_if_needed() -> None:
    """
    若 users 表为空，则从 auth_users.txt 导入并写入密码 hash。
    仅在初次启动/首次运行时生效。
    """
    init_auth_db()
    if not _is_db_empty():
        return
    users = _load_users_from_txt()
    if not users:
        return

    now = datetime.now(timezone.utc).isoformat()
    with _get_sqlite_conn(get_auth_db_path()) as conn:
        for username, password in users.items():
            create_user(username=username, password=password, created_at=now, conn=conn)
        conn.commit()


def _pbkdf2_hmac_sha256(password: str, salt: bytes, iterations: int = 200_000) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def hash_password(password: str, *, salt: Optional[bytes] = None) -> tuple[str, str]:
    """
    返回 (salt_b64, password_hash_hex)
    """
    if salt is None:
        salt = os.urandom(16)
    salt_b64 = base64.b64encode(salt).decode("ascii")
    pw_hash = _pbkdf2_hmac_sha256(password=password, salt=salt)
    # 以 hex 存储便于调试；真正安全性由比较与 PBKDF2 决定
    return salt_b64, pw_hash.hex()


def create_user(*, username: str, password: str, created_at: str = "", conn: Optional[sqlite3.Connection] = None) -> None:
    # 仅负责创建/插入；种子迁移由外层入口（verify/user_exists/seed）触发一次。
    init_auth_db()
    if not username or not username.strip():
        raise ValueError("username is required")
    if conn is None:
        conn = _get_sqlite_conn(get_auth_db_path())
        close_after = True
    else:
        close_after = False

    try:
        salt_b64, pw_hash_hex = hash_password(password)
        created_at = created_at or datetime.now(timezone.utc).isoformat()
        name = username.strip()
        user_id = _choose_user_id(conn, name)

        # 使用 INSERT OR IGNORE + 检查是否存在，避免竞态导致的覆盖
        cur = conn.execute("SELECT 1 FROM users WHERE username = ?", (name,))
        if cur.fetchone() is not None:
            raise ValueError("username already exists")

        conn.execute(
            """
            INSERT INTO users (user_id, username, salt_b64, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, name, salt_b64, pw_hash_hex, created_at),
        )
        conn.commit()
    finally:
        if close_after:
            conn.close()


def get_user_by_username(username: str) -> Optional[AuthUserRecord]:
    """按登录名返回认证用户记录。"""
    target = (username or "").strip()
    if not target:
        return None
    init_auth_db()
    with _get_sqlite_conn(get_auth_db_path()) as conn:
        cur = conn.execute(
            "SELECT user_id, username, created_at FROM users WHERE username = ?",
            (target,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return AuthUserRecord(
            user_id=str(row["user_id"] or ""),
            username=str(row["username"] or ""),
            created_at=str(row["created_at"] or ""),
        )


def verify_user(*, username: str, password: str) -> bool:
    seed_from_auth_users_txt_if_needed()
    db_path = get_auth_db_path()
    if not db_path.exists():
        return False

    with _get_sqlite_conn(db_path) as conn:
        cur = conn.execute(
            "SELECT salt_b64, password_hash FROM users WHERE username = ?",
            (username.strip(),),
        )
        row = cur.fetchone()
        if row is None:
            return False

        salt_b64 = str(row["salt_b64"])
        password_hash = str(row["password_hash"])

        salt = base64.b64decode(salt_b64.encode("ascii"))
        candidate_hash = _pbkdf2_hmac_sha256(password=password, salt=salt).hex()
        return hmac.compare_digest(candidate_hash, password_hash)


def user_exists(username: str) -> bool:
    seed_from_auth_users_txt_if_needed()
    db_path = get_auth_db_path()
    if not db_path.exists():
        return False
    with _get_sqlite_conn(db_path) as conn:
        cur = conn.execute("SELECT 1 FROM users WHERE username = ?", (username.strip(),))
        return cur.fetchone() is not None


def update_password(*, username: str, new_password: str) -> None:
    """更新用户密码（仅写入新 salt/hash，不做旧密码校验）。"""
    init_auth_db()
    target = (username or "").strip()
    if not target:
        raise ValueError("username is required")
    salt_b64, pw_hash_hex = hash_password(new_password)
    with _get_sqlite_conn(get_auth_db_path()) as conn:
        cur = conn.execute("SELECT 1 FROM users WHERE username = ?", (target,))
        if cur.fetchone() is None:
            raise ValueError("username not found")
        conn.execute(
            "UPDATE users SET salt_b64 = ?, password_hash = ? WHERE username = ?",
            (salt_b64, pw_hash_hex, target),
        )
        conn.commit()


def delete_user(*, username: str) -> bool:
    """从 SQLite 用户表删除账号。返回是否实际删除了行。"""
    init_auth_db()
    target = (username or "").strip()
    if not target:
        raise ValueError("username is required")
    with _get_sqlite_conn(get_auth_db_path()) as conn:
        cur = conn.execute("DELETE FROM users WHERE username = ?", (target,))
        conn.commit()
        return cur.rowcount > 0


def rename_user(*, old_username: str, new_username: str) -> None:
    """重命名账号（更改 users 主键 username）。"""
    init_auth_db()
    old_name = (old_username or "").strip()
    new_name = (new_username or "").strip()
    if not old_name or not new_name:
        raise ValueError("username is required")
    if old_name == new_name:
        return
    with _get_sqlite_conn(get_auth_db_path()) as conn:
        cur_old = conn.execute("SELECT 1 FROM users WHERE username = ?", (old_name,))
        if cur_old.fetchone() is None:
            raise ValueError("old username not found")
        cur_new = conn.execute("SELECT 1 FROM users WHERE username = ?", (new_name,))
        if cur_new.fetchone() is not None:
            raise ValueError("new username already exists")
        conn.execute("UPDATE users SET username = ? WHERE username = ?", (new_name, old_name))
        conn.commit()
