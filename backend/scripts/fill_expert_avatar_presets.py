"""一次性：为所有用户配置里 avatar_url 为空的专家随机指定内置头像路径（/expert-avatars/expert-NN.png）。"""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRESETS = [f"/expert-avatars/expert-{i:02d}.png" for i in range(1, 12)]


def fill_file(path: Path) -> int:
    """返回本文件中被写入头像条目的数量。"""
    if not path.is_file():
        return 0
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, list):
        return 0
    n = 0
    for row in data:
        if not isinstance(row, dict):
            continue
        if str(row.get("avatar_url") or "").strip():
            continue
        row["avatar_url"] = random.choice(PRESETS)
        n += 1
    if n:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return n


def main() -> None:
    total_rows = 0
    users_dir = ROOT / "data" / "users"
    if users_dir.is_dir():
        for cfg in users_dir.glob("**/config/dha_instances.json"):
            total_rows += fill_file(cfg)
    # 仓库内示例/默认配置（若存在）
    for p in (ROOT / "config" / "dha_instances.json",):
        total_rows += fill_file(p)
    print(f"done: updated {total_rows} expert row(s) with preset avatars")


if __name__ == "__main__":
    main()
