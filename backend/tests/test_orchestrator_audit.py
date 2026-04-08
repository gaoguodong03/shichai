"""Tests for orchestrator audit formatting."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent import orchestrator_audit as oa


def test_format_one_scheduler_decision():
    line = oa._format_one_audit_line(
        "scheduler_decision",
        {
            "decision": {
                "next_speaker": "agent-a",
                "task_done": False,
                "reason": "需要下一步",
                "next_prompt": "请完成某事",
            }
        },
    )
    assert "agent-a" in line
    assert "task_done=False" in line
    assert "调度" in line


def test_format_audit_for_host_prompt_tail(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir(parents=True)
    p = mem / "orchestrator_audit.jsonl"
    rec = {
        "ts": "2026-01-01T00:00:00+00:00",
        "event_type": "turn_started",
        "turn_id": "t1",
        "payload": {"speaker": "agent-x"},
    }
    p.write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")

    monkeypatch.setattr(oa, "_audit_file", lambda _sid: p)

    out = oa.format_audit_for_host_prompt("any-session")
    assert "agent-x" in out
    assert "发言开始" in out


def test_format_audit_empty_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    mem = tmp_path / "memory"
    mem.mkdir(parents=True)
    p = mem / "orchestrator_audit.jsonl"
    p.write_text("", encoding="utf-8")
    monkeypatch.setattr(oa, "_audit_file", lambda _sid: p)
    assert oa.format_audit_for_host_prompt("x") == ""
