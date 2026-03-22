#!/usr/bin/env python3
"""
将旧版「全局 data/sessions、data/agent-outputs」迁移到多用户目录 data/users/<用户名>/。

默认迁移到用户 free4inno（原默认账号）。请在 backend 目录执行：

  python scripts/migrate_legacy_user_layout.py
  python scripts/migrate_legacy_user_layout.py --dry-run

迁移内容：
- data/sessions/*           -> data/users/<用户>/sessions/
- data/agent-outputs/workspaces -> data/users/<用户>/agent-outputs/workspaces/
- config 下 JSON（dha_instances、app_settings、mcp_servers、session_presets）-> data/users/<用户>/config/
- skills/                    -> data/users/<用户>/skills/

另：若存在旧版按名的 data/agent-outputs/<用户名>/（非 workspaces），会合并到 data/users/<用户名>/agent-outputs/。

不删除、不移动 auth_users.sqlite / users.json / auth_users.txt（仍在 backend/config）。
迁移完成后请重启后端；确认无误后可自行备份并清空旧的 data/sessions 与 data/agent-outputs 空壳目录。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

CONFIG_JSON = (
    "dha_instances.json",
    "app_settings.json",
    "mcp_servers.json",
    "session_presets.json",
)


def _copytree_merge(src: Path, dst: Path, dry_run: bool) -> None:
    if not src.exists():
        return
    if dry_run:
        print(f"  [dry-run] merge {src} -> {dst}")
        return
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, dirs_exist_ok=True)


def migrate(*, username: str, dry_run: bool) -> None:
    backend = Path(__file__).resolve().parents[1]
    data = backend / "data"
    dest = data / "users" / username
    legacy_sessions = data / "sessions"
    legacy_ao = data / "agent-outputs"
    cfg_src = backend / "config"
    skills_src = backend / "skills"

    print(f"目标用户目录: {dest}")
    for sub in ("sessions", "agent-outputs", "config", "skills"):
        p = dest / sub
        if not dry_run:
            p.mkdir(parents=True, exist_ok=True)

    # 1) 全局 sessions
    if legacy_sessions.exists() and any(legacy_sessions.iterdir()):
        _copytree_merge(legacy_sessions, dest / "sessions", dry_run)

    # 2) 全局 agent-outputs/workspaces -> 该用户
    ws = legacy_ao / "workspaces"
    if ws.exists() and any(ws.iterdir()):
        _copytree_merge(ws, dest / "agent-outputs" / "workspaces", dry_run)

    # 3) 旧版 data/agent-outputs/<某用户名>/ 下的内容合并到对应 data/users/<名>/agent-outputs/
    if legacy_ao.exists():
        for child in legacy_ao.iterdir():
            if not child.is_dir() or child.name == "workspaces":
                continue
            u = child.name
            u_dest = data / "users" / u / "agent-outputs"
            if dry_run:
                print(f"  [dry-run] merge per-user legacy {child} -> {u_dest}")
            else:
                u_dest.mkdir(parents=True, exist_ok=True)
                shutil.copytree(child, u_dest, dirs_exist_ok=True)

    # 4) 配置 JSON
    for name in CONFIG_JSON:
        s, d = cfg_src / name, dest / "config" / name
        if not s.exists():
            continue
        if dry_run:
            print(f"  [dry-run] copy {s.name} -> {d}")
        else:
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(s, d)

    # 5) skills
    if skills_src.is_dir():
        _copytree_merge(skills_src, dest / "skills", dry_run)

    print("完成。" if not dry_run else "（dry-run，未写入磁盘）")


def main() -> int:
    ap = argparse.ArgumentParser(description="迁移旧版全局数据到 data/users/<用户>/")
    ap.add_argument("--user", default="free4inno", help="迁移到的用户名（默认 free4inno）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    migrate(username=args.user.strip() or "free4inno", dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
