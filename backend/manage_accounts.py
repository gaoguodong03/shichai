#!/usr/bin/env python3
"""
命令行管理账户：新增 / 删除（与 HTTP /api/auth 使用同一套 SQLite + users.json）。

  python manage_accounts.py add --username 13800138000 --password 'your-password'
  python manage_accounts.py delete --username 13800138000 --yes
  python manage_accounts.py delete --username 13800138000 --remove-data --yes

环境变量与 app 一致：AUTH_DB_PATH、SHUTONG_USER_DATA_ROOT 等。
"""

from __future__ import annotations

import argparse
import getpass
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# 保证以「python manage_accounts.py」运行时能 import app
_BACKEND_ROOT = Path(__file__).resolve().parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.core.auth_db import create_user, delete_user, user_exists  # noqa: E402
from app.core.user_context import ensure_empty_session_presets, users_data_root  # noqa: E402
from app.core.users_store import ensure_user_profile, remove_user_profile  # noqa: E402

PHONE_REGEX = re.compile(r"^1[3-9]\d{9}$")
EMAIL_REGEX = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _is_valid_account(value: str) -> bool:
    return bool(PHONE_REGEX.match(value) or EMAIL_REGEX.match(value))


def cmd_add(args: argparse.Namespace) -> int:
    name = (args.username or "").strip()
    if not name:
        print("错误：--username 不能为空", file=sys.stderr)
        return 2
    if not _is_valid_account(name):
        print("错误：账号须为手机号或电子邮箱", file=sys.stderr)
        return 2
    password = args.password
    if not password:
        password = getpass.getpass("密码（至少 6 位）: ")
    if len(password) < 6:
        print("错误：密码至少 6 位", file=sys.stderr)
        return 2
    if user_exists(username=name):
        print(f"错误：用户已存在: {name}", file=sys.stderr)
        return 1
    try:
        create_user(username=name, password=password)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    created_at = datetime.now(timezone.utc).isoformat()
    ensure_user_profile(name, created_at=created_at)
    ensure_empty_session_presets(name)
    print(f"已新建账户: {name}")
    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    name = (args.username or "").strip()
    if not name:
        print("错误：--username 不能为空", file=sys.stderr)
        return 2
    if not args.yes:
        try:
            confirm = input(f"确认删除账户「{name}」? 输入 yes 继续: ")
        except EOFError:
            print("错误：非交互环境请使用 --yes", file=sys.stderr)
            return 2
        if confirm.strip().lower() != "yes":
            print("已取消")
            return 0

    removed_db = delete_user(username=name)
    removed_profile = remove_user_profile(name)

    data_dir = (users_data_root() / name).resolve()
    removed_data = False
    if args.remove_data and data_dir.exists():
        shutil.rmtree(data_dir)
        removed_data = True

    if not removed_db and not removed_profile and not removed_data:
        print(f"未找到账户: {name}", file=sys.stderr)
        return 1

    parts = []
    if removed_db:
        parts.append("登录凭证已删除")
    if removed_profile:
        parts.append("users.json 档案已删除")
    if args.remove_data:
        parts.append("用户数据目录已删除" if removed_data else "用户数据目录不存在，跳过")
    print("；".join(parts) + "。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="管理后台账户（SQLite + users.json）")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="新增账户")
    p_add.add_argument("--username", "-u", required=True, help="手机号或邮箱")
    p_add.add_argument("--password", "-p", default="", help="密码（至少 6 位）；省略则交互输入")
    p_add.set_defaults(func=cmd_add)

    p_del = sub.add_parser("delete", help="删除账户")
    p_del.add_argument("--username", "-u", required=True, help="要删除的账号")
    p_del.add_argument(
        "--yes", "-y", action="store_true", help="不询问确认（脚本/自动化用）"
    )
    p_del.add_argument(
        "--remove-data",
        action="store_true",
        help="同时删除 backend/data/users/<用户名> 下全部数据（不可恢复）",
    )
    p_del.set_defaults(func=cmd_delete)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
