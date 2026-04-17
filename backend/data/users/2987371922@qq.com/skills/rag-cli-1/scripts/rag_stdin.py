"""run_skill_script CLI-only 参数辅助函数。"""
import sys
from typing import Any


def is_interactive_cli() -> bool:
    """本地终端直接运行时 stdin 为 TTY，可用 argparse 交互式补参。"""
    return sys.stdin.isatty()


def has_cli_argv() -> bool:
    """run_skill_script 传入 cli_args_json 时，参数会出现在 sys.argv[1:]。"""
    return len(sys.argv) > 1


def read_stdin_json_dict() -> dict[str, Any] | None:
    """CLI-only 模式下不再支持 stdin JSON，保留函数签名供旧代码导入。"""
    return None
