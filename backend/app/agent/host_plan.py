"""用户可编辑的场景任务清单 memory/host_plan.md（与 orchestrator_audit.jsonl 自动审计分离）。"""
from __future__ import annotations

from pathlib import Path

from app.api.files import get_workspace_root, get_workspace_root_path

# 工作区内相对路径（POSIX）
HOST_PLAN_REL = "memory/host_plan.md"

HOST_PLAN_TEMPLATE = """# 场景任务清单（用户可编辑）

> 与 `memory/orchestrator_audit.jsonl`（自动调度审计）分离：请在此用 Markdown 维护勾选任务；主持人会参考本文件与讨论目标判断进度。**智能体工具不会修改本文件**，请在侧边栏工作区中编辑。

- [ ] 示例：明确讨论主题与交付物
- [ ] 示例：完成资料收集
- [ ] 示例：产出终稿

"""


def _host_plan_path(session_id: str) -> Path:
    root = get_workspace_root_path(session_id)
    return (root / "memory" / "host_plan.md").resolve()


def is_host_plan_reserved_path(rel: str) -> bool:
    """是否为受保护的用户清单路径（禁止通过智能体写入/编辑/删除/改名）。"""
    n = str(rel or "").strip().replace("\\", "/").lstrip("/").lower()
    return n == HOST_PLAN_REL.lower()


def ensure_host_plan_stub(session_id: str) -> None:
    """若不存在则创建 memory 目录与 host_plan.md 模板。"""
    ws = get_workspace_root(session_id)
    target = ws / "memory" / "host_plan.md"
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(HOST_PLAN_TEMPLATE, encoding="utf-8")


def read_host_plan_for_prompt(session_id: str, *, max_chars: int = 12000) -> str:
    """读取清单供主持人调度上下文使用；首次访问会生成模板文件。"""
    ensure_host_plan_stub(session_id)
    p = _host_plan_path(session_id)
    if not p.exists():
        return ""
    try:
        raw = p.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(raw) > max_chars:
        return "...[host_plan.md 已截断]\n" + raw[-max_chars:]
    return raw
