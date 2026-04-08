"""memory/host_plan.md 清单与工具保护。"""
from __future__ import annotations

import os

os.environ.setdefault("QWEN_API_KEY", "test-key-for-unit-test")

from pathlib import Path

import pytest

from app.agent.host_plan import (
    HOST_PLAN_REL,
    ensure_host_plan_stub,
    is_host_plan_reserved_path,
    read_host_plan_for_prompt,
)


def test_is_host_plan_reserved_path():
    assert is_host_plan_reserved_path("memory/host_plan.md") is True
    assert is_host_plan_reserved_path("/memory/host_plan.md") is True
    assert is_host_plan_reserved_path("memory\\host_plan.md") is True
    assert is_host_plan_reserved_path("notes/x.md") is False


def test_ensure_and_read_host_plan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from app.agent import host_plan as hp

    def _root(sid: str) -> Path:
        p = tmp_path / "ws" / sid
        p.mkdir(parents=True, exist_ok=True)
        return p

    monkeypatch.setattr(hp, "get_workspace_root", lambda sid: _root(sid))
    monkeypatch.setattr(hp, "get_workspace_root_path", _root)

    ensure_host_plan_stub("group-test")
    p = _root("group-test") / "memory" / "host_plan.md"
    assert p.exists()
    text = read_host_plan_for_prompt("group-test")
    assert HOST_PLAN_REL.split("/")[-1] in text or "场景任务清单" in text


def test_write_workspace_file_rejects_host_plan():
    from app.tools import write_workspace_file as ww

    tool = ww.create_write_workspace_file_tool("group-x")
    out = tool.invoke({"path": "memory/host_plan.md", "content": "x"})
    assert "禁止" in str(out)
