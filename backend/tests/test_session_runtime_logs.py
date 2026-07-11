import json

from app.api import group_chat_state as state
from app.agent.session_runtime_logs import (
    append_host_execution_log,
    append_tool_execution_logs,
    load_tool_execution_logs,
    message_execution_log_summaries,
)


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


def test_append_host_execution_log_records_scheduler_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_host_execution_log(
        "s1",
        message_id="host-1",
        host_name="四九",
        skill="group-host",
        current_phase="写作",
        next_speaker="文档合著专家",
        next_action="请生成工作区文档。",
        content="下面由 文档合著专家 发言。",
        status="succeeded",
    )

    rows = load_tool_execution_logs("s1")

    assert rows[0]["message_id"] == "host-1"
    assert rows[0]["source"] == "host"
    assert rows[0]["agent_name"] == "四九"
    assert rows[0]["skill"] == "group-host"
    assert rows[0]["tool_call"]["name"] == "host_scheduler"
    assert rows[0]["tool_call"]["provider"] == "host"
    assert rows[0]["tool_call"]["provider_tool"] == "select_next_speaker"
    assert rows[0]["tool_call"]["arguments"] == {
        "current_phase": "写作",
        "next_speaker": "文档合著专家",
        "next_action": "请生成工作区文档。",
    }
    assert rows[0]["output"]["text"] == "下面由 文档合著专家 发言。"

    summary = message_execution_log_summaries("s1", message_id="host-1")[0]
    assert summary["source"] == "host"
    assert summary["tool_name"] == "host_scheduler"
    assert summary["output_summary"] == "下面由 文档合著专家 发言。"


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
                        "schema_version": "expert_final_state.v2",
                        "execution_status": "succeeded",
                        "artifacts": [{"type": "file", "name": "报告", "path": "reports/report.md"}],
                        "next_action": {
                            "handoff": "host",
                            "resume": "none",
                            "reason": "stage_completed",
                            "instruction": "已生成报告。",
                        },
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


def test_append_tool_execution_logs_rejects_invalid_tool_status(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_tool_execution_logs(
        "s1",
        message_id="msg-1",
        agent_name="专家",
        skill="skill-a",
        tool_results=[
            {
                "tool_call": {
                    "id": "call-1",
                    "name": "write_workspace_file",
                    "kind": "workspace",
                    "arguments": {"path": "report.md"},
                },
                "execution_status": "ok",
                "message": "旧状态字段不应进入日志",
                "output": {"text": "done", "json_data": {}, "stdout": "", "stderr": ""},
            }
        ],
    )

    assert load_tool_execution_logs("s1") == []


def test_append_tool_execution_logs_rejects_internal_artifact_paths(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_tool_execution_logs(
        "s1",
        message_id="msg-1",
        agent_name="专家",
        skill="skill-a",
        tool_results=[
            {
                "tool_call": {
                    "id": "call-1",
                    "name": "run_skill_script",
                    "kind": "script",
                    "provider": "skill-a",
                    "provider_tool": "scripts/build.py",
                    "arguments": {},
                },
                "execution_status": "succeeded",
                "message": "脚本完成",
                "output": {
                    "text": "raw",
                    "json_data": {
                        "schema_version": "expert_final_state.v2",
                        "execution_status": "succeeded",
                        "artifacts": [{"type": "file", "name": "内部记忆", "path": "memory/facts.md"}],
                        "next_action": {
                            "handoff": "host",
                            "resume": "none",
                            "reason": "stage_completed",
                            "instruction": "错误产物路径。",
                        },
                    },
                    "stdout": "",
                    "stderr": "",
                },
            }
        ],
    )

    assert load_tool_execution_logs("s1") == []
