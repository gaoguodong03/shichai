"""Resolve 【文件引用】 tags into readable text blocks."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from app.api.files import get_workspace_root_path

_FILE_REF_RE = re.compile(r"【文件引用：([^】]+)】")


def _extract_path(ref_body: str) -> str:
    body = (ref_body or "").strip()
    if "｜" in body:
        return body.split("｜", 1)[1].strip()
    return body


def _safe_workspace_file_path(workspace_id: str, rel_path: str) -> Path:
    ws_root = get_workspace_root_path(workspace_id).resolve()
    cleaned = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not cleaned:
        raise ValueError("empty path")
    target = (ws_root / cleaned).resolve()
    if not str(target).startswith(str(ws_root)):
        raise ValueError("path out of workspace")
    return target


def resolve_file_refs_in_text(
    text: str,
    workspace_id: str,
    *,
    max_files: int = 8,
    max_chars_per_file: int = 6000,
    max_total_chars: int = 18000,
) -> str:
    raw = text or ""
    refs = _FILE_REF_RE.findall(raw)
    if not refs:
        return raw

    unique_paths: List[str] = []
    seen: set[str] = set()
    for body in refs:
        p = _extract_path(body)
        if not p or p in seen:
            continue
        seen.add(p)
        unique_paths.append(p)
        if len(unique_paths) >= max_files:
            break

    injected: List[Tuple[str, str]] = []
    total_chars = 0
    for p in unique_paths:
        if total_chars >= max_total_chars:
            break
        try:
            full = _safe_workspace_file_path(workspace_id, p)
            if not full.exists() or full.is_dir():
                injected.append((p, "[文件不存在或是目录]"))
                continue
            try:
                content = full.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                injected.append((p, "[非 UTF-8 文本，无法直接注入]"))
                continue
            content = content[:max_chars_per_file]
            if total_chars + len(content) > max_total_chars:
                content = content[: max(0, max_total_chars - total_chars)]
            total_chars += len(content)
            injected.append((p, content or "(空文件)"))
        except Exception as e:  # noqa: BLE001
            injected.append((p, f"[读取失败: {e}]"))

    if not injected:
        return raw

    parts = ["【文件内容已解析】"]
    for path, content in injected:
        parts.append(f"[文件: {path}]\n{content}")
    return f"{raw}\n\n" + "\n\n".join(parts)

