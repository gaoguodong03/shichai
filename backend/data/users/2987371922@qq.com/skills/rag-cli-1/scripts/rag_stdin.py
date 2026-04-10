"""run_skill_script 可通过 stdin（JSON）或 CLI（cli_args_json）传参时的公共逻辑。"""
import json
import sys
from typing import Any


def is_interactive_cli() -> bool:
    """本地终端直接运行时 stdin 为 TTY，可用 argparse 交互式补参。"""
    return sys.stdin.isatty()


def has_cli_argv() -> bool:
    """run_skill_script 传入 cli_args_json 时，参数会出现在 sys.argv[1:]。"""
    return len(sys.argv) > 1


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
