"""用户沙箱 Python 依赖清单工具。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple


def requirement_key(line: str) -> str:
    item = (line or "").strip()
    if not item or item.startswith("#"):
        return ""
    if item.startswith(("-", "git+", "http://", "https://")):
        return item.lower()
    item = item.split("#", 1)[0].strip()
    item = item.split(";", 1)[0].strip()
    matched = re.match(r"^\s*([A-Za-z0-9_.-]+)", item)
    return (matched.group(1) if matched else item).lower().replace("_", "-")


def merge_requirements_lines(path: Path, incoming: List[str]) -> Tuple[List[str], str]:
    current = path.read_text(encoding="utf-8") if path.is_file() else ""
    existing_keys = {requirement_key(line) for line in current.splitlines()}
    existing_keys.discard("")
    added: List[str] = []
    for line in incoming:
        key = requirement_key(line)
        if not key or key in existing_keys:
            continue
        existing_keys.add(key)
        added.append(line.strip())
    if not added:
        return [], current
    prefix = current.rstrip("\n")
    merged = (prefix + "\n" if prefix else "") + "\n".join(added) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(merged, encoding="utf-8")
    return added, merged


def sandbox_requirements_error_detail(exc: Exception) -> str:
    msg = str(exc).strip() or exc.__class__.__name__
    return f"已保存 requirements.txt，但沙箱依赖安装验证失败：{msg}"
