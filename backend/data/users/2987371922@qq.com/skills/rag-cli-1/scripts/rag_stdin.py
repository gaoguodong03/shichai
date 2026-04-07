"""run_skill_script 通过 stdin 传入 JSON 对象时的公共解析逻辑。"""
import json
import sys
from typing import Any


def read_stdin_json_dict() -> dict[str, Any] | None:
    if sys.stdin.isatty():
        return None
    raw = (sys.stdin.read() or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
