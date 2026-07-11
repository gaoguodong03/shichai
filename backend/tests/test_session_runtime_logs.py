import json

from app.api import group_chat_state as state
from app.agent.session_runtime_logs import append_tool_execution_logs, load_tool_execution_logs


TS1 = "2026062908104800"


def test_append_tool_execution_logs_writes_session_level_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_tool_execution_logs(
        "s1",
        message_id="msg-1",
        agent_name="信息检索专家",
        skill="web-search",
        tool_results=[
            {
                "tool_call": {
                    "id": "call-1",
                    "name": "linkup-search",
                    "kind": "mcp",
                    "provider": "linkup",
                    "provider_tool": "search",
                    "arguments": {"query": "合同"},
                },
                "execution_status": "succeeded",
                "message": "工具执行成功",
                "output": {
                    "text": "摘要",
                    "json_data": {"items": [1]},
                    "stdout": "raw stdout",
                    "stderr": "",
                },
            }
        ],
    )

    log_path = tmp_path / "s1" / "execution_logs" / "tool-execution.jsonl"
    rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    assert len(rows) == 1
    assert rows[0]["message_id"] == "msg-1"
    assert rows[0]["source"] == "mcp"
    assert rows[0]["agent_name"] == "信息检索专家"
    assert rows[0]["skill"] == "web-search"
    assert rows[0]["tool_call"] == {
        "id": "call-1",
        "name": "linkup-search",
        "provider": "linkup",
        "provider_tool": "search",
        "arguments": {"query": "合同"},
    }
    assert rows[0]["output"] == {
        "text": "摘要",
        "json": {"items": [1]},
        "stdout": "raw stdout",
        "stderr": "",
    }
    assert rows[0]["artifacts"] == []
    assert "log_ids" not in rows[0]
    assert "kind" not in rows[0]["tool_call"]
    assert all(value is not None for value in rows[0].values())


def test_record_group_chat_tool_trace_writes_session_level_jsonl(tmp_path, monkeypatch):
    from app.agent import group_chat_tool_trace

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    group_chat_tool_trace.record_group_chat_tool_trace(
        "s1",
        message_id="msg-1",
        agent_name="信息检索专家",
        skill="web-search",
        tool_results=[
            {
                "tool_call": {
                    "id": "call-1",
                    "name": "linkup-search",
                    "kind": "mcp",
                    "provider": "linkup",
                    "provider_tool": "search",
                    "arguments": {"query": "合同"},
                },
                "execution_status": "succeeded",
                "message": "工具执行成功",
                "output": {"text": "摘要", "json_data": {}, "stdout": "", "stderr": ""},
            }
        ],
    )

    rows = load_tool_execution_logs("s1")

    assert rows[0]["message_id"] == "msg-1"
    assert rows[0]["source"] == "mcp"
    assert rows[0]["agent_name"] == "信息检索专家"


def test_append_tool_execution_logs_records_script_stdout_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_tool_execution_logs(
        "s1",
        message_id="msg-1",
        agent_name="文档专家",
        skill="report-writer",
        tool_results=[
            {
                "tool_call": {
                    "id": "call-1",
                    "name": "run_skill_script",
                    "kind": "script",
                    "provider": "report-writer",
                    "provider_tool": "scripts/build.py",
                    "arguments": {},
                },
                "execution_status": "succeeded",
                "message": "脚本完成",
                "output": {
                    "text": "raw",
                    "json_data": {
                        "execution_status": "succeeded",
                        "content": "已生成报告。",
                        "artifacts": [{"type": "file", "name": "报告", "path": "reports/report.md"}],
                        "next_action": {"agent_turn": "respond", "skill_session": "release"},
                    },
                    "stdout": "",
                    "stderr": "",
                },
            }
        ],
    )

    rows = load_tool_execution_logs("s1")

    assert rows[0]["tool_call"]["provider"] == "report-writer"
    assert rows[0]["tool_call"]["provider_tool"] == "scripts/build.py"
    assert rows[0]["artifacts"] == [{"type": "file", "name": "报告", "path": "reports/report.md"}]


def test_append_tool_execution_logs_skips_unknown_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_tool_execution_logs(
        "s1",
        message_id="msg-1",
        agent_name="专家",
        skill="skill-a",
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "legacy", "kind": "unknown", "arguments": {}},
                "execution_status": "succeeded",
                "message": "工具执行成功",
            }
        ],
    )

    assert load_tool_execution_logs("s1") == []
