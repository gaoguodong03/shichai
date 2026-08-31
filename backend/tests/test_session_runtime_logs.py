import json

from app.api import group_chat_state as state
from app.agent.session_runtime_logs import (
    append_host_execution_log,
    append_llm_execution_logs,
    append_runtime_failure_log,
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
                    "content": "摘要",
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
        "content": "摘要",
        "json_data": {"items": [1]},
        "artifacts": [],
        "stdout": "raw stdout",
        "stderr": "",
    }
    assert "log_ids" not in rows[0]
    assert "kind" not in rows[0]["tool_call"]
    assert all(value is not None for value in rows[0].values())

    summary = message_execution_log_summaries("s1", message_id="msg-1")[0]
    assert summary["step_type"] == "tool_execution"


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
                "output": {"content": "摘要", "json_data": {}, "stdout": "", "stderr": ""},
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
        message={"content": "请生成工作区文档。", "target_agent_name": "文档合著专家"},
        status="succeeded",
    )

    rows = load_tool_execution_logs("s1")

    assert rows[0]["message_id"] == "host-1"
    assert rows[0]["source"] == "host"
    assert rows[0]["agent_name"] == "四九"
    assert rows[0]["skill"] == "group-host"
    assert rows[0]["tool_call"]["name"] == "host_scheduler"
    assert rows[0]["tool_call"]["provider"] == "host"
    assert rows[0]["tool_call"]["provider_tool"] == "schedule_message"
    assert rows[0]["tool_call"]["arguments"] == {
        "current_phase": "写作",
        "message": {"content": "请生成工作区文档。", "target_agent_name": "文档合著专家"},
    }
    assert rows[0]["output"]["content"] == "请生成工作区文档。"

    summary = message_execution_log_summaries("s1", message_id="host-1")[0]
    assert summary["source"] == "host"
    assert summary["tool_name"] == "host_scheduler"
    assert summary["output_summary"] == "请生成工作区文档。"
    assert "step_type" not in summary


def test_append_runtime_failure_log_records_sanitized_failure_fact(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_runtime_failure_log(
        "s1",
        message_id="failed-1",
        agent_name="信息检索专家",
        skill="web-search",
        error_code="EXPERT_RUNTIME_FAILED",
        error_type="RuntimeError",
        phase="expert_turn",
        error_summary="Authorization: Bearer super-secret-token; api_key=sk-private-value; upstream timeout",
    )

    rows = load_tool_execution_logs("s1")

    assert len(rows) == 1
    assert rows[0]["message_id"] == "failed-1"
    assert rows[0]["source"] == "runtime"
    assert rows[0]["status"] == "failed"
    assert rows[0]["agent_name"] == "信息检索专家"
    assert rows[0]["skill"] == "web-search"
    assert rows[0]["tool_call"]["name"] == "group_chat_failure"
    assert rows[0]["tool_call"]["provider"] == "runtime"
    assert rows[0]["tool_call"]["provider_tool"] == "expert_turn"
    assert rows[0]["tool_call"]["arguments"] == {
        "error_code": "EXPERT_RUNTIME_FAILED",
        "error_type": "RuntimeError",
        "phase": "expert_turn",
    }
    serialized = json.dumps(rows[0], ensure_ascii=False)
    assert "upstream timeout" in serialized
    assert "super-secret-token" not in serialized
    assert "sk-private-value" not in serialized
    assert "traceback" not in serialized.lower()

    summary = message_execution_log_summaries("s1", message_id="failed-1")[0]
    assert summary["source"] == "runtime"
    assert summary["step_type"] == "execution_failure"
    assert summary["output_summary"].endswith("upstream timeout")


def test_append_llm_execution_logs_records_usage_and_canonical_fault(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_llm_execution_logs(
        "s1",
        message_id="msg-llm-1",
        agent_name="四九",
        skill="group-host",
        calls=[
            {
                "operation": "host_speaker_selection",
                "method": "ainvoke",
                "model": "qwen3-max",
                "provider_base_url": "https://example.test/v1?api_key=must-not-persist",
                "created_at": "2026062908104700",
                "status": "failed",
                "duration_ms": 321,
                "output_content": '{"next_speaker":"文档专家"}',
                "input_metrics": {"input_messages": 3, "prompt_chars": 2400, "tool_call_count": 0},
                "output_metrics": {"output_chars": 52, "tool_call_count": 0},
                "response_metadata": {
                    "finish_reason": "stop",
                    "token_usage": {
                        "input_tokens": 640,
                        "output_tokens": 80,
                        "total_tokens": 720,
                        "cached_tokens": 128,
                    },
                },
                "error_code": "LLM_RESPONSE_INVALID",
                "error_type": "StructuredOutputProtocolError",
                "error_summary": "返回的 JSON 缺少 target_agent_name",
            }
        ],
    )

    rows = load_tool_execution_logs("s1")
    assert len(rows) == 1
    assert rows[0]["source"] == "llm"
    assert rows[0]["tool_call"]["provider"] == "litellm"
    assert rows[0]["tool_call"]["provider_tool"] == "host_speaker_selection"
    assert rows[0]["tool_call"]["arguments"]["endpoint"] == "https://example.test/v1"
    assert "must-not-persist" not in json.dumps(rows[0], ensure_ascii=False)
    assert rows[0]["duration_ms"] == 321
    assert rows[0]["created_at"] == "2026062908104700"
    assert rows[0]["output"]["content"] == '{"next_speaker":"文档专家"}'

    summary = message_execution_log_summaries("s1", message_id="msg-llm-1")[0]
    assert summary["step_type"] == "model_decision"
    assert summary["model"] == "qwen3-max"
    assert summary["input_tokens"] == 640
    assert summary["output_tokens"] == 80
    assert summary["total_tokens"] == 720
    assert summary["cached_tokens"] == 128
    assert summary["output_summary"] == '{"next_speaker":"文档专家"}'
    assert summary["output_content"] == '{"next_speaker":"文档专家"}'
    assert summary["error_code"] == "LLM_RESPONSE_INVALID"
    assert summary["error_name"] == "大模型响应不正确"
    assert "JSON" in summary["error_summary"]
    assert "结构校验" in summary["error_description"]
    assert summary["error_action"]


def test_llm_output_content_is_not_truncated_and_legacy_summary_is_not_exposed(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})
    original_output = "原始模型输出" * 200

    append_llm_execution_logs(
        "s1",
        message_id="msg-raw-output",
        agent_name="专家",
        skill="writer",
        calls=[{"status": "succeeded", "output_content": original_output}],
    )
    append_llm_execution_logs(
        "s1",
        message_id="msg-legacy-output",
        agent_name="专家",
        skill="writer",
        calls=[{"status": "succeeded", "output_content": "模型响应已接收：92 字；finish_reason=stop"}],
    )

    raw_summary = message_execution_log_summaries("s1", message_id="msg-raw-output")[0]
    legacy_summary = message_execution_log_summaries("s1", message_id="msg-legacy-output")[0]

    assert raw_summary["output_content"] == original_output
    assert raw_summary["output_summary"].endswith("...")
    assert "output_content" not in legacy_summary


def test_execution_log_summaries_pretty_print_json_arguments_and_sort_by_call_time(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions({"s1": {"title": "会话", "updated_at": TS1}})

    append_tool_execution_logs(
        "s1",
        message_id="msg-ordered",
        agent_name="四九",
        skill="group-host",
        tool_results=[
            {
                "created_at": "2026062908104802",
                "tool_call": {
                    "id": "call-later",
                    "name": "write_workspace_file",
                    "kind": "workspace",
                    "arguments": {"path": "later.md"},
                },
                "execution_status": "succeeded",
                "output": {"content": "later"},
            },
            {
                "created_at": "2026062908104801",
                "tool_call": {
                    "id": "call-earlier",
                    "name": "host_payload",
                    "kind": "host",
                    "arguments": {
                        "current_phase": "写作",
                        "message": {"content": "请继续。", "target_agent_name": "文档专家"},
                        "note": "甲；乙;丙",
                    },
                },
                "execution_status": "succeeded",
                "output": {"content": "earlier"},
            },
        ],
    )

    rows = message_execution_log_summaries("s1", message_id="msg-ordered")

    assert [row["created_at"] for row in rows] == ["2026062908104801", "2026062908104802"]
    assert rows[0]["argument_summary"] == (
        'current_phase=写作\nmessage=\n{\n  "content": "请继续。",\n  "target_agent_name": "文档专家"\n}'
        '\nnote=甲；乙;丙'
    )


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
                    "content": "raw",
                    "json_data": {},
                    "artifacts": [{"type": "file", "name": "报告", "path": "reports/report.md"}],
                    "stdout": "",
                    "stderr": "",
                },
            }
        ],
    )

    rows = load_tool_execution_logs("s1")

    assert rows[0]["tool_call"]["provider"] == "report-writer"
    assert rows[0]["tool_call"]["provider_tool"] == "scripts/build.py"
    assert rows[0]["output"]["artifacts"] == [{"type": "file", "name": "报告", "path": "reports/report.md"}]


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
                "output": {"content": "done", "json_data": {}, "stdout": "", "stderr": ""},
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
                    "content": "raw",
                    "json_data": {},
                    "artifacts": [{"type": "file", "name": "内部记忆", "path": "memory/facts.md"}],
                    "stdout": "",
                    "stderr": "",
                },
            }
        ],
    )

    assert load_tool_execution_logs("s1") == []
