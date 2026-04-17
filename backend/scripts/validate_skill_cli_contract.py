#!/usr/bin/env python3
"""Validate skill script contract: CLI-only and script-path consistency."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
USERS_SKILLS_ROOT = ROOT / "data" / "users"

DOC_FORBIDDEN_PATTERNS = [
    re.compile(r"input_json\s*=", re.IGNORECASE),
    re.compile(r"`input_json`\s*[：:]", re.IGNORECASE),
    re.compile(r"input_json\s+为", re.IGNORECASE),
]
DOC_ALLOW_PHRASE = "不再支持 `input_json`"

SCRIPT_STDIN_PATTERN = re.compile(r"sys\.stdin\.read\(")


def iter_skill_dirs() -> list[Path]:
    out: list[Path] = []
    if not USERS_SKILLS_ROOT.exists():
        return out
    for user_dir in USERS_SKILLS_ROOT.iterdir():
        skills_dir = user_dir / "skills"
        if not skills_dir.is_dir():
            continue
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                out.append(skill_dir)
    return out


def check_skill_md(skill_dir: Path, errors: list[str]) -> None:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        return
    text = skill_md.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    for idx, line in enumerate(lines, start=1):
        if DOC_ALLOW_PHRASE in line:
            continue
        for pat in DOC_FORBIDDEN_PATTERNS:
            if pat.search(line):
                errors.append(f"{skill_md}:{idx}: 检测到旧 input_json 文档写法: {line.strip()}")
                break

    scripts_dir = skill_dir / "scripts"
    script_paths = set()
    if scripts_dir.is_dir():
        for p in scripts_dir.rglob("*"):
            if p.is_file():
                script_paths.add(p.name)

    # script_path=<name>.py
    for m in re.finditer(r"script_path\s*=\s*`?([A-Za-z0-9_.\\/-]+\.(?:py|sh|bash|ps1|cmd|bat))`?", text):
        raw = m.group(1).replace("\\", "/")
        basename = raw.split("/")[-1]
        if basename not in script_paths:
            errors.append(f"{skill_md}: script_path 引用不存在脚本: {raw}")

    # run_skill_script 场景中的 scripts/xxx.py 引用
    for line in lines:
        if "run_skill_script" not in line:
            continue
        for m in re.finditer(r"scripts/([A-Za-z0-9_.\\/-]+\.(?:py|sh|bash|ps1|cmd|bat))", line):
            raw = m.group(1).replace("\\", "/")
            basename = raw.split("/")[-1]
            if basename not in script_paths:
                errors.append(f"{skill_md}: run_skill_script 引用不存在脚本: {raw}")


def check_scripts(skill_dir: Path, errors: list[str]) -> None:
    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return
    for p in scripts_dir.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in {".py", ".sh", ".bash"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if SCRIPT_STDIN_PATTERN.search(text):
            errors.append(f"{p}: 检测到 stdin 读取逻辑（CLI-only 违规）")


def main() -> int:
    errors: list[str] = []
    for skill_dir in iter_skill_dirs():
        check_skill_md(skill_dir, errors)
        check_scripts(skill_dir, errors)

    if errors:
        print("Skill CLI contract validation failed:")
        for err in errors:
            print(f"- {err}")
        return 1

    print("Skill CLI contract validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
