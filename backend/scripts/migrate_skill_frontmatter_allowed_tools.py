#!/usr/bin/env python3
"""
批量迁移 SKILL.md frontmatter：
- 删除: mcp_server_ids / write_mode / enabled / source / url
- 统一补齐: allowed-tools
    - mcp: 兼容从旧 mcp_server_ids 迁移
    - python: 若缺失则补空字符串（仅说明用途）

默认 dry-run，不改文件；加 --apply 才落盘。
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

ALLOWED_TOOLS_KEY = "allowed-tools"
REMOVE_KEYS = ("mcp_server_ids", "write_mode", "enabled", "source", "url")


def parse_skill_markdown(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        fm = yaml.safe_load(parts[1]) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    body = parts[2].lstrip("\n")
    return fm, body


def dump_skill_markdown(frontmatter: Dict[str, Any], body: str) -> str:
    return "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False) + "---\n" + body


def normalized_allowed_tools(fm: Dict[str, Any]) -> Dict[str, Any]:
    at_raw = fm.get(ALLOWED_TOOLS_KEY)
    at = at_raw if isinstance(at_raw, dict) else {}

    # mcp: allowed-tools.mcp 优先；否则从 legacy mcp_server_ids 迁移
    if "mcp" in at:
        mcp_raw = at.get("mcp")
        mcp = [str(x).strip() for x in (mcp_raw or []) if str(x).strip()] if isinstance(mcp_raw, list) else []
    else:
        legacy = fm.get("mcp_server_ids")
        mcp = [str(x).strip() for x in (legacy or []) if str(x).strip()] if isinstance(legacy, list) else []
    mcp = list(dict.fromkeys(mcp))

    # python: 仅说明
    py_raw = at.get("python", "")
    py = py_raw if isinstance(py_raw, str) else ("" if py_raw is None else str(py_raw))

    return {"mcp": mcp, "python": py}


def migrate_frontmatter(fm: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    out = dict(fm)
    out[ALLOWED_TOOLS_KEY] = normalized_allowed_tools(out)
    for k in REMOVE_KEYS:
        out.pop(k, None)
    return out, out != fm


def iter_skill_files(skills_root: Path) -> List[Path]:
    files: List[Path] = []
    if not skills_root.exists():
        return files
    for d in sorted(skills_root.iterdir()):
        if d.is_dir():
            f = d / "SKILL.md"
            if f.is_file():
                files.append(f)
    return files


def process_skills(skills_root: Path, apply: bool) -> Tuple[int, int]:
    files = iter_skill_files(skills_root)
    changed = 0
    total = 0
    for fp in files:
        total += 1
        raw = fp.read_text(encoding="utf-8")
        fm, body = parse_skill_markdown(raw)
        new_fm, changed_flag = migrate_frontmatter(fm)
        if not changed_flag:
            continue
        changed += 1
        print(f"[MIGRATE] {fp}")
        if apply:
            fp.write_text(dump_skill_markdown(new_fm, body), encoding="utf-8")
    return total, changed


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch migrate skill frontmatter to allowed-tools.")
    parser.add_argument("--skills-root", required=True, help="Skills directory, e.g. backend/data/users/<user>/skills")
    parser.add_argument("--apply", action="store_true", help="Write changes to files (default dry-run).")
    args = parser.parse_args()

    root = Path(args.skills_root).resolve()
    total, changed = process_skills(root, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] scanned={total}, to_change={changed}, root={root}")


if __name__ == "__main__":
    main()
