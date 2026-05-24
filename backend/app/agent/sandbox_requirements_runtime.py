"""Small helpers for sandbox requirements install/verification runtime."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.sandbox_requirements import requirement_key

PLAYWRIGHT_REQUIREMENT_KEYS = {"playwright", "patchright"}


def requirements_imply_playwright(req_path: Path) -> bool:
    try:
        content = req_path.read_text(encoding="utf-8") if req_path.is_file() else ""
    except Exception:
        return False
    return any(requirement_key(line) in PLAYWRIGHT_REQUIREMENT_KEYS for line in content.splitlines())


def requirements_package_summary(content: str, *, limit: int = 24) -> Dict[str, Any]:
    keys: List[str] = []
    for line in (content or "").splitlines():
        key = requirement_key(line)
        if key and key not in keys:
            keys.append(key)
    return {
        "count": len(keys),
        "preview": keys[:limit],
        "has_playwright": "playwright" in keys,
        "has_patchright": "patchright" in keys,
        "truncated": len(keys) > limit,
    }


def command_exit_code(result: Any) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    for key in ("exit_code", "returncode", "return_code", "code"):
        value = result.get(key)
        if isinstance(value, int):
            return value
    ok = result.get("ok")
    if ok is False:
        return 1
    return None


def command_output(result: Any) -> tuple[str, str]:
    if not isinstance(result, dict):
        return "", ""
    return str(result.get("stdout") or ""), str(result.get("stderr") or "")


def tail(text: str, limit: int = 4000) -> str:
    value = str(text or "")
    return value[-limit:] if len(value) > limit else value


def requirements_b64(content: str) -> str:
    normalized = (content or "").strip()
    if not normalized:
        return ""
    return base64.b64encode(normalized.encode("utf-8")).decode("ascii")
