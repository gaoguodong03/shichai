"""rag-cli-1 脚本公共 I/O 约定。

目标：
- 统一结构化输出（stdout 打印单行 JSON），便于上层稳定解析。
- 统一路径约定：相对路径一律相对当前工作目录（run_skill_script 在沙箱里会把 cwd 设到会话工作区）。
  允许绝对路径，但若明显是错误的 /workspace/<session_id> 这类路径，给出明确提示。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def emit_result(
    *,
    ok: bool,
    code: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    debug: Optional[Dict[str, Any]] = None,
    to_stderr: bool = False,
) -> None:
    payload: Dict[str, Any] = {"ok": bool(ok), "code": str(code), "message": str(message)}
    if isinstance(data, dict):
        payload["data"] = data
    if isinstance(debug, dict):
        payload["debug"] = debug
    stream = sys.stderr if to_stderr else sys.stdout
    stream.write(_json_dumps(payload).strip() + "\n")
    stream.flush()


def resolve_workspace_path(raw: str) -> Path:
    """将用户传入的路径解析为本地可用路径。

约定：
- 相对路径：相对当前工作目录（Path.cwd()）。
- 绝对路径：原样使用。

注意：
run_skill_script 在沙箱里通常会把 cwd 设置到类似 /workspace/sessions/<session_id>，
因此传入 "input/foo.txt" 会落在当前会话工作区内。
"""

    if raw is None:
        raise ValueError("path 不能为空")
    s = str(raw).strip()
    if not s:
        raise ValueError("path 不能为空")
    p = Path(s).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p)
    # 不强制 resolve(strict=True)；避免在不存在时抛出难读异常
    return p


def explain_common_path_mistakes(path: Path) -> str:
    """对常见误用路径给出建议字符串（用于错误消息）。"""
    s = str(path).replace("\\", "/")
    cwd = str(Path.cwd()).replace("\\", "/")
    if s.startswith("/workspace/") and not path.exists():
        # 常见：把 session_id 当成 /workspace/<id> 目录；实际会话目录通常是 /workspace/sessions/<id>
        return (
            "你传入了 /workspace/... 的绝对路径但该路径不存在。"
            "在沙箱中，脚本的当前工作目录通常已经是会话工作区（例如 /workspace/sessions/<session_id>）。"
            "请优先传入相对路径（相对当前工作目录），或使用 /workspace/sessions/<session_id>/...。"
            f"当前 cwd={cwd}"
        )
    if s.startswith("/Users/") or s.startswith("C:/") or s.startswith("C:\\"):
        return (
            "看起来你传入了宿主机路径。脚本在沙箱里运行时无法访问宿主机绝对路径；"
            "请先把文件放到会话工作区内，并传入相对路径。"
            f"当前 cwd={cwd}"
        )
    return f"当前 cwd={cwd}"


def env_snapshot() -> Dict[str, Any]:
    """最小调试信息：用于定位 cwd / workspace 约定。"""
    return {
        "cwd": str(Path.cwd()),
        "SKILL_WORKSPACE_ID": os.getenv("SKILL_WORKSPACE_ID", ""),
        "SKILL_WORKSPACE_ROOT": os.getenv("SKILL_WORKSPACE_ROOT", ""),
    }

