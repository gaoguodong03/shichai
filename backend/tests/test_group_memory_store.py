"""群聊记忆文件存储与派发上下文测试。"""
import json
from pathlib import Path

from app.agent.group_memory_store import (
    append_llm_roundtrip,
    upsert_facts,
    build_dispatch_context,
)


def test_upsert_facts_dedup_and_cap(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    upsert_facts(session_id, ["事实A", "事实B"], max_facts=3, workspace_root=ws)
    facts = upsert_facts(session_id, ["事实B", "事实C", "事实D"], max_facts=3, workspace_root=ws)

    assert facts == ["事实B", "事实C", "事实D"]
    facts_file = ws / "memory" / "facts.md"
    content = facts_file.read_text(encoding="utf-8")
    assert "- 事实A" not in content
    assert "- 事实D" in content


def test_build_dispatch_context_uses_only_facts(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    upsert_facts(session_id, ["用户希望输出周报", "需包含图表"], workspace_root=ws)
    old_logs = ws / "memory" / "logs"
    old_logs.mkdir(parents=True, exist_ok=True)
    (old_logs / "old.md").write_text("这条旧日志不应进入下一轮提示词", encoding="utf-8")
    old_messages = ws / "memory" / "messages"
    old_messages.mkdir(parents=True, exist_ok=True)
    (old_messages / "old.md").write_text("旧完整发言也不应被引用", encoding="utf-8")

    ctx = build_dispatch_context(
        session_id=session_id,
        workspace_root=ws,
        target_agent_id="agent-data",
        goal="数据 周报",
        k=1,
    )

    assert ctx["has_memory"] is True
    assert ctx["facts"] == ["用户希望输出周报", "需包含图表"]
    assert ctx["logs"] == []
    assert ctx["refs"] == []
    assert "关键事实" in ctx["rendered"]
    assert "相关历史摘录" not in ctx["rendered"]
    assert "旧日志不应进入下一轮提示词" not in ctx["rendered"]
    assert "旧完整发言也不应被引用" not in ctx["rendered"]


def test_build_dispatch_context_without_facts_has_no_memory(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    ctx = build_dispatch_context(
        session_id=session_id,
        workspace_root=ws,
        target_agent_id="agent-data",
        goal="数据 周报",
        k=1,
    )

    assert ctx == {"facts": [], "logs": [], "refs": [], "rendered": "", "has_memory": False}


def test_append_llm_roundtrip_writes_jsonl_without_truncation(tmp_path: Path):
    session_id = "group-test"
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    long_text = "输入" * 8000

    append_llm_roundtrip(
        session_id=session_id,
        workspace_root=ws,
        phase="host_decide",
        input_messages=[{"role": "system", "content": long_text}],
        output={"content": "输出1"},
        agent_id="agent-host",
        skill_id="group-host-general",
        llm_provider_id="qwen",
        model="qwen3",
        run_id="run-1",
        client_message_id="client-1",
        tool_specs=[{"name": "tool-a", "description": "工具A"}],
    )
    append_llm_roundtrip(
        session_id=session_id,
        workspace_root=ws,
        phase="expert_turn",
        input_messages=[{"role": "user", "content": "继续"}],
        output={"content": "输出2"},
    )

    trace_file = ws / "memory" / "llm_roundtrips.jsonl"
    rows = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["schema_version"] == 1
    assert rows[0]["session_id"] == session_id
    assert rows[0]["phase"] == "host_decide"
    assert rows[0]["agent_id"] == "agent-host"
    assert rows[0]["input_messages"][0]["content"] == long_text
    assert rows[0]["output"] == {"content": "输出1"}
    assert rows[0]["tool_specs"] == [{"name": "tool-a", "description": "工具A"}]
    assert rows[1]["phase"] == "expert_turn"
