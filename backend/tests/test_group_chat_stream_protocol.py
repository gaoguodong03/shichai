from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.messages import AIMessage
from app.agent.session_contracts import GroupChatRequest


def _parse_sse_block(block: str) -> tuple[str, dict[str, Any]]:
    lines = block.strip().splitlines()
    event_type = lines[0].replace("event: ", "").strip()
    data = "\n".join(line[6:].strip() for line in lines if line.startswith("data: "))
    return event_type, json.loads(data)


def _expert_final_state_json(
    content: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
    execution_status: str = "succeeded",
    agent_turn: str = "respond",
    skill_session: str = "release",
) -> str:
    return json.dumps(
        {
            "execution_status": execution_status,
            "message": {
                "content": content,
                "attachments": [],
                "artifacts": artifacts or [],
            },
            "next_action": {
                "agent_turn": agent_turn,
                "skill_session": skill_session,
            },
        },
        ensure_ascii=False,
    )


async def _collect_stream_events(response) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    body_iter = response.body_iterator
    try:
        async for chunk in body_iter:
            text = chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
            for block in text.replace("\r", "").split("\n\n"):
                if block.strip():
                    events.append(_parse_sse_block(block))
    finally:
        close = getattr(body_iter, "aclose", None)
        if close:
            await close()
    return events


def test_collect_artifacts_keeps_only_strict_public_artifact_refs():
    from app.agent.group_chat_tool_result_content import collect_artifacts

    artifacts = collect_artifacts(
        [
            {
                "output": {
                    "artifacts": [
                    {"path": "reports/missing-type-and-name.md"},
                    {"type": "file", "path": "reports/missing-name.md"},
                    {"type": "legacy", "name": "旧类型", "path": "reports/legacy.md"},
                    {"type": "file", "name": "报告", "path": "reports/report.md", "data": {"inline": True}},
                    ]
                }
            }
        ]
    )

    assert artifacts == [{"type": "file", "name": "报告", "path": "reports/report.md"}]


@pytest.mark.asyncio
async def test_chat_stream_omits_legacy_start_event(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    async def _init_noop():
        return None

    monkeypatch.setattr(runtime, "ensure_mcp_and_skills_initialized", _init_noop)
    monkeypatch.setattr(runtime, "load_agent_instances", lambda: [])
    monkeypatch.setattr(runtime, "load_app_settings", lambda: {"default_llm": "", "system_prompt": "", "host": {}})
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda _agent, _settings: object())

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待用户",
            "message": {"content": "请先补充任务目标。"},
            "suggested_add_agent_names": [],
        }

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    session_id = "s-chat-stream-contract"
    state.save_session_definitions(
        {
            session_id: {
                "title": "流协议",
                "agent_names": [],
                "host": {"name": "四九"},
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )
    state.save_group_history(session_id, [])

    response = await runtime.group_chat_stream(
        session_id,
        GroupChatRequest(message="你好", message_id="msg-user-1"),
    )

    events = await _collect_stream_events(response)
    event_names = [event_name for event_name, _payload in events]
    assert "start" not in event_names
    assert set(event_names) <= {"route", "progress", "message", "end", "error"}
    assert events[0][0] == "message"
    assert "agent_running" not in {payload.get("phase") for _, payload in events}
    assert "message_ready" not in {payload.get("phase") for _, payload in events}


@pytest.mark.asyncio
async def test_chat_stream_registers_run_with_stable_user_id(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _init_noop():
        return None

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待用户",
            "message": {"content": "等待用户补充。"},
            "suggested_add_agent_names": [],
        }

    captured = {}

    async def _register_run(_session_id: str, *, user_id: str, task, **_kwargs):
        captured["user_id"] = user_id
        return "run-stable-user"

    monkeypatch.setattr(runtime, "ensure_mcp_and_skills_initialized", _init_noop)
    monkeypatch.setattr(runtime, "load_agent_instances", lambda: [])
    monkeypatch.setattr(runtime, "load_app_settings", lambda: {"default_llm": "", "system_prompt": "", "host": {}})
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda _agent, _settings: object())
    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "register_group_run", _register_run)

    session_id = "s-chat-stream-user-id"
    token = set_current_user_identity(user_id="user-stream-stable", username="stream@example.com")
    try:
        state.save_session_definitions(
            {
                session_id: {
                    "title": "稳定用户",
                    "agent_names": [],
                    "host": {"name": "四九"},
                    "created_at": "2026070900000000",
                    "updated_at": "2026070900000000",
                }
            }
        )
        state.save_group_history(session_id, [])
        response = await runtime.group_chat_stream(
            session_id,
            GroupChatRequest(message="你好", message_id="msg-user-id"),
        )
        await _collect_stream_events(response)
    finally:
        reset_current_user_identity(token)

    assert captured["user_id"] == "user-stream-stable"


@pytest.mark.asyncio
async def test_host_handoff_message_precedes_expert_route(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-host-handoff": {
                "title": "主持人交接",
                "agent_names": ["文档合著专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-host-handoff", [])

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "写作",
            "message": {"content": "请先写文章大纲。", "target_agent_name": "文档合著专家"},
            "suggested_add_agent_names": [],
        }

    async def _expert_turn(**kwargs):
        kwargs["outcome"].succeed()
        yield runtime.serialize_sse_event(
            "route",
            {"type": "route", "run_id": kwargs["run_id"], "agent_name": kwargs["agent_name"], "skill": "document-coauthor"},
        )

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-host-handoff",
            request=GroupChatRequest(message="帮我写文章", message_id="msg-user-1"),
            run_id="run-1",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-host-handoff"],
            app_settings={},
            agent_map={"文档合著专家": {"name": "文档合著专家", "description": "写文章"}},
            agent_names=["文档合著专家"],
            messages=[],
            discussion_goal="帮我写文章",
            user_text="帮我写文章",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    assert parsed[0][0] == "message"
    assert parsed[0][1]["speaker"] == {"type": "host", "agent_name": "四九"}
    assert parsed[0][1]["message"] == {
        "content": "请先写文章大纲。",
        "target_agent_name": "文档合著专家",
    }
    assert parsed[1][0] == "route"
    assert parsed[1][1]["agent_name"] == "文档合著专家"


@pytest.mark.asyncio
async def test_closed_scene_hides_non_member_agents_from_host_catalog(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    session_id = "s-closed-scene"
    session_item = {
        "title": "封闭场景",
        "agent_names": ["资源管理专家"],
        "allow_agent_recruitment": False,
        "host": {"name": "四九"},
        "created_at": "2026071100000000",
        "updated_at": "2026071100000000",
    }
    state.save_session_definitions({session_id: session_item})
    state.save_group_history(session_id, [])
    captured_available = []

    async def _host_decision(*args, **_kwargs):
        captured_available.append(args[7])
        return {
            "current_phase": "等待用户",
            "message": {"content": "请补充资源操作。"},
            "suggested_add_agent_names": [],
        }

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id=session_id,
            request=GroupChatRequest(message="发布文件", message_id="msg-user-1"),
            run_id="run-closed-scene",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()[session_id],
            app_settings={},
            agent_map={
                "资源管理专家": {"name": "资源管理专家", "description": "管理资源"},
                "资源发布专家": {"name": "资源发布专家", "description": "发布资源"},
            },
            agent_names=["资源管理专家"],
            messages=[],
            discussion_goal="发布文件",
            user_text="发布文件",
        )
    ]

    assert events
    assert captured_available == [[]]


@pytest.mark.asyncio
async def test_expert_turn_returns_to_host_before_awaiting_user(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-expert-back-host": {
                "title": "专家后回主持人",
                "agent_names": ["文档合著专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-expert-back-host", [])
    decisions = [
        {
            "current_phase": "写作",
            "message": {"content": "请先写文章大纲。", "target_agent_name": "文档合著专家"},
            "suggested_add_agent_names": [],
        },
        {
            "current_phase": "等待确认",
            "message": {"content": "大纲已完成，请确认是否继续写正文。"},
            "suggested_add_agent_names": [],
        },
    ]

    async def _host_decision(*_args, **_kwargs):
        return decisions.pop(0)

    async def _expert_turn(**kwargs):
        kwargs["outcome"].succeed()
        expert_msg = {
            "message_id": "msg-expert-1",
            "speaker": {"type": "expert", "agent_name": kwargs["agent_name"], "skill": "document-coauthor"},
            "message": {"content": "大纲已完成。"},
            "created_at": "2026071100000100",
            "skill_result": {
                "execution_status": "succeeded",
            },
        }
        kwargs["messages"].append(expert_msg)
        yield runtime.serialize_sse_event("message", expert_msg)

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-expert-back-host",
            request=GroupChatRequest(message="帮我写文章", message_id="msg-user-1"),
            run_id="run-1",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-expert-back-host"],
            app_settings={},
            agent_map={"文档合著专家": {"name": "文档合著专家", "description": "写文章"}},
            agent_names=["文档合著专家"],
            messages=[],
            discussion_goal="帮我写文章",
            user_text="帮我写文章",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    message_contents = [
        payload["message"]["content"]
        for event_type, payload in parsed
        if event_type == "message"
    ]
    assert message_contents == [
        "请先写文章大纲。",
        "大纲已完成。",
        "大纲已完成，请确认是否继续写正文。",
    ]
    assert parsed[-1][0] == "end"
    assert parsed[-1][1]["phase"] == "awaiting_user"
    assert decisions == []


@pytest.mark.asyncio
async def test_successful_tool_action_cannot_be_immediately_reassigned_to_same_expert(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-tool-repeat-guard": {
                "title": "工具防重复",
                "agent_names": ["资源管理专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-tool-repeat-guard", [])
    decisions = [
        {
            "current_phase": "上传资源",
            "message": {"content": "请上传文件。", "target_agent_name": "资源管理专家"},
            "suggested_add_agent_names": [],
        },
        {
            "current_phase": "上传资源",
            "message": {"content": "请再次上传文件。", "target_agent_name": "资源管理专家"},
            "suggested_add_agent_names": [],
        },
    ]
    expert_calls = 0

    async def _host_decision(*_args, **_kwargs):
        return decisions.pop(0)

    async def _expert_turn(**kwargs):
        nonlocal expert_calls
        expert_calls += 1
        kwargs["outcome"].tool_results.append(
            {
                "tool_call": {
                    "id": "call-upload-1",
                    "name": "http_api_tool_upload",
                    "kind": "api",
                    "arguments": {"workspace_file": {"path": "test.txt"}},
                },
                "execution_status": "succeeded",
                "output": {"content": "ok"},
            }
        )
        kwargs["outcome"].succeed()
        expert_msg = {
            "message_id": "msg-expert-upload",
            "speaker": {
                "type": "expert",
                "agent_name": kwargs["agent_name"],
                "skill": "resource-manager",
            },
            "message": {"content": "文件已上传。"},
            "created_at": "2026071100000100",
            "skill_result": {"execution_status": "succeeded"},
        }
        kwargs["messages"].append(expert_msg)
        yield runtime.serialize_sse_event("message", expert_msg)

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-tool-repeat-guard",
            request=GroupChatRequest(message="上传这个文件", message_id="msg-user-1"),
            run_id="run-1",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-tool-repeat-guard"],
            app_settings={},
            agent_map={"资源管理专家": {"name": "资源管理专家", "description": "管理资源"}},
            agent_names=["资源管理专家"],
            messages=[],
            discussion_goal="上传这个文件",
            user_text="上传这个文件",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    assert expert_calls == 1
    assert decisions == []
    assert [
        payload["message"]["content"]
        for event_type, payload in parsed
        if event_type == "message"
    ] == ["请上传文件。", "文件已上传。"]
    assert parsed[-1][0] == "end"
    assert parsed[-1][1]["phase"] == "awaiting_user"


@pytest.mark.asyncio
async def test_agent_turn_continue_schedules_same_expert_without_host_decision(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-agent-turn-continue": {
                "title": "专家继续",
                "agent_names": ["文档合著专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-agent-turn-continue", [])
    host_calls = 0
    expert_calls: list[str] = []

    async def _host_decision(*_args, **_kwargs):
        nonlocal host_calls
        host_calls += 1
        if host_calls > 1:
            return {
                "current_phase": "等待确认",
                "message": {"content": "请确认是否继续。"},
                "suggested_add_agent_names": [],
            }
        return {
            "current_phase": "写作",
            "message": {"content": "请先写文章大纲。", "target_agent_name": "文档合著专家"},
            "suggested_add_agent_names": [],
        }

    async def _expert_turn(**kwargs):
        expert_calls.append(kwargs["agent_name"])
        outcome = kwargs["outcome"]
        outcome.succeed()
        if len(expert_calls) == 1:
            outcome.agent_turn = "continue"
            outcome.skill_session = "keep"
        else:
            outcome.agent_turn = "respond"
            outcome.skill_session = "release"
            expert_msg = {
                "message_id": "msg-expert-final",
                "speaker": {"type": "expert", "agent_name": kwargs["agent_name"], "skill": "document-coauthor"},
                "message": {"content": "最终完成。"},
                "created_at": "2026071100000100",
                "skill_result": {
                    "execution_status": "succeeded",
                },
            }
            kwargs["messages"].append(expert_msg)
            yield runtime.serialize_sse_event("message", expert_msg)

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-agent-turn-continue",
            request=GroupChatRequest(message="帮我写文章", message_id="msg-user-1"),
            run_id="run-continue",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-agent-turn-continue"],
            app_settings={},
            agent_map={"文档合著专家": {"name": "文档合著专家", "description": "写文章"}},
            agent_names=["文档合著专家"],
            messages=[],
            discussion_goal="帮我写文章",
            user_text="帮我写文章",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    assert host_calls == 2
    assert expert_calls == ["文档合著专家", "文档合著专家"]
    assert [payload["message"]["content"] for event, payload in parsed if event == "message"] == [
        "请先写文章大纲。",
        "最终完成。",
        "请确认是否继续。",
    ]


@pytest.mark.asyncio
async def test_expert_failure_stops_before_host_is_scheduled_again(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.agent.group_chat_expert_turn import ExpertTurnOutcome
    from app.agent.session_runtime_logs import load_tool_execution_logs
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-expert-failed": {
                "title": "专家失败终止",
                "agent_names": ["信息检索专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-expert-failed", [])
    state.write_group_orchestration_state(
        "s-expert-failed",
        {
            "host_scheduler": {
                "current_phase": "检索",
                "message": {"content": "请搜索资料。", "target_agent_name": "信息检索专家"},
            },
            "skill_sessions": {"信息检索专家": {"skill": "web-search"}},
        },
    )
    host_calls = 0

    async def _host_decision(*_args, **_kwargs):
        nonlocal host_calls
        host_calls += 1
        return {
            "current_phase": "检索",
            "message": {"content": "请搜索资料。", "target_agent_name": "信息检索专家"},
            "suggested_add_agent_names": [],
        }

    async def _expert_turn(**kwargs):
        outcome = kwargs["outcome"]
        assert isinstance(outcome, ExpertTurnOutcome)
        outcome.tool_results.append(
            {
                "execution_status": "succeeded",
                "tool_call": {
                    "id": "tc-search",
                    "name": "web_search_exa",
                    "kind": "mcp",
                    "provider": "Exa",
                    "arguments": {"query": "沈腾"},
                },
                "output": {"content": "检索摘要"},
            }
        )
        outcome.fail(code="EXPERT_FINAL_STATE_INVALID", message="专家没有产出合格的最终状态。")
        yield runtime.serialize_sse_event(
            "error",
            {
                "type": "error",
                "run_id": kwargs["run_id"],
                "code": outcome.error_code,
                "message": outcome.error_message,
            },
        )

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-expert-failed",
            request=GroupChatRequest(message="搜索沈腾", message_id="msg-user-failed"),
            run_id="run-failed",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-expert-failed"],
            app_settings={},
            agent_map={
                "信息检索专家": {
                    "name": "信息检索专家",
                    "description": "搜索资料",
                    "skill_directory": "web-search",
                }
            },
            agent_names=["信息检索专家"],
            messages=[],
            discussion_goal="搜索沈腾",
            user_text="搜索沈腾",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    assert host_calls == 0
    assert [event for event, _payload in parsed].count("error") == 1
    assert [event for event, _payload in parsed][-3:] == ["error", "message", "end"]
    failed_message = parsed[-2][1]
    assert failed_message["speaker"] == {
        "type": "expert",
        "agent_name": "信息检索专家",
        "skill": "web-search",
    }
    assert "EXPERT_FINAL_STATE_INVALID" in failed_message["message"]["content"]
    assert failed_message["skill_result"] == {
        "execution_status": "failed",
    }
    assert parsed[-1][0] == "end"
    assert parsed[-1][1]["phase"] == "failed"
    assert state.load_group_history("s-expert-failed")[-1] == failed_message
    assert state.load_group_orchestration_state("s-expert-failed") == {}
    failure_logs = [row for row in load_tool_execution_logs("s-expert-failed") if row["source"] == "runtime"]
    assert len(failure_logs) == 1
    assert failure_logs[0]["message_id"] == failed_message["message_id"]
    assert failure_logs[0]["tool_call"]["arguments"]["error_code"] == "EXPERT_FINAL_STATE_INVALID"
    tool_logs = [row for row in load_tool_execution_logs("s-expert-failed") if row["source"] == "mcp"]
    assert len(tool_logs) == 1
    assert tool_logs[0]["message_id"] == failed_message["message_id"]
    assert tool_logs[0]["tool_call"]["name"] == "web_search_exa"


@pytest.mark.asyncio
async def test_structured_finalizer_error_uses_stable_expert_error_code(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.agent.structured_output_contracts import StructuredOutputProtocolError
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-finalizer-invalid": {
                "title": "最终态协议失败",
                "agent_names": ["信息检索专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-finalizer-invalid", [])

    async def _expert_turn(**_kwargs):
        raise StructuredOutputProtocolError("finalizer schema invalid", schema_name="ExpertFinalStatePayload")
        if False:
            yield ""

    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-finalizer-invalid",
            request=GroupChatRequest(
                message="直接回复",
                message_id="msg-user-finalizer-invalid",
                target_agent_name="信息检索专家",
            ),
            run_id="run-finalizer-invalid",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-finalizer-invalid"],
            app_settings={},
            agent_map={
                "信息检索专家": {
                    "name": "信息检索专家",
                    "description": "搜索资料",
                    "skill_directory": "web-search",
                }
            },
            agent_names=["信息检索专家"],
            messages=[],
            discussion_goal="直接回复",
            user_text="直接回复",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    error_payloads = [payload for event, payload in parsed if event == "error"]
    assert error_payloads == [
        {
            "type": "error",
            "run_id": "run-finalizer-invalid",
            "code": "EXPERT_FINAL_STATE_INVALID",
            "message": "finalizer schema invalid",
        }
    ]
    assert [event for event, _payload in parsed][-3:] == ["error", "message", "end"]
    assert parsed[-2][1]["speaker"]["agent_name"] == "信息检索专家"
    assert parsed[-2][1]["skill_result"]["execution_status"] == "failed"
    assert "EXPERT_FINAL_STATE_INVALID" in parsed[-2][1]["message"]["content"]
    assert parsed[-1][0] == "end"
    assert parsed[-1][1]["phase"] == "failed"


@pytest.mark.asyncio
async def test_expert_runtime_exception_persists_expert_failure_and_sanitizes_sse(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.agent.session_runtime_logs import load_tool_execution_logs
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    session_id = "s-expert-runtime-exception"
    state.save_session_definitions(
        {
            session_id: {
                "title": "专家运行异常",
                "agent_names": ["信息检索专家"],
                "host": {"name": "四九"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history(session_id, [])

    async def _expert_turn(**_kwargs):
        raise RuntimeError("api_key=secret-value; expert connection reset")
        if False:
            yield ""

    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id=session_id,
            request=GroupChatRequest(
                message="直接搜索",
                message_id="msg-user-expert-runtime",
                target_agent_name="信息检索专家",
            ),
            run_id="run-expert-runtime",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()[session_id],
            app_settings={},
            agent_map={
                "信息检索专家": {
                    "name": "信息检索专家",
                    "description": "搜索资料",
                    "skill_directory": "web-search",
                }
            },
            agent_names=["信息检索专家"],
            messages=[],
            discussion_goal="直接搜索",
            user_text="直接搜索",
        )
    ]

    parsed = [_parse_sse_block(item) for item in events]
    assert [event for event, _payload in parsed] == ["error", "message", "end"]
    assert parsed[0][1]["code"] == "EXPERT_TURN_RUNTIME_FAILED"
    assert "expert connection reset" in parsed[0][1]["message"]
    assert "secret-value" not in json.dumps(parsed, ensure_ascii=False)
    failed_message = parsed[1][1]
    assert failed_message["speaker"] == {
        "type": "expert",
        "agent_name": "信息检索专家",
        "skill": "web-search",
    }
    failure_log = [row for row in load_tool_execution_logs(session_id) if row["source"] == "runtime"][0]
    assert failure_log["message_id"] == failed_message["message_id"]
    assert failure_log["tool_call"]["arguments"] == {
        "error_code": "EXPERT_TURN_RUNTIME_FAILED",
        "error_type": "RuntimeError",
        "phase": "expert_turn",
    }


@pytest.mark.asyncio
async def test_chat_stream_persists_host_failure_message_for_outer_runtime_exception(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.agent.session_runtime_logs import load_tool_execution_logs
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _init_noop():
        return None

    async def _raise_runtime_error(**_kwargs):
        raise RuntimeError("Authorization: Bearer hidden-token; upstream disconnected")
        if False:
            yield ""

    monkeypatch.setattr(runtime, "ensure_mcp_and_skills_initialized", _init_noop)
    monkeypatch.setattr(runtime, "load_agent_instances", lambda: [])
    monkeypatch.setattr(runtime, "load_app_settings", lambda: {"default_llm": "", "system_prompt": "", "host": {}})
    monkeypatch.setattr(runtime, "_run_contract_events", _raise_runtime_error)
    session_id = "s-outer-runtime-failed"
    state.save_session_definitions(
        {
            session_id: {
                "title": "外层异常",
                "agent_names": [],
                "host": {"name": "四九", "skill_directory": "group-host"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history(session_id, [])

    response = await runtime.group_chat_stream(
        session_id,
        GroupChatRequest(message="开始执行", message_id="msg-user-outer-failed"),
    )
    parsed = await _collect_stream_events(response)

    assert [event for event, _payload in parsed][-3:] == ["error", "message", "end"]
    failed_message = parsed[-2][1]
    assert failed_message["speaker"] == {
        "type": "host",
        "agent_name": "四九",
        "skill": "group-host",
    }
    assert failed_message["skill_result"]["execution_status"] == "failed"
    assert "GROUP_CHAT_RUNTIME_FAILED" in failed_message["message"]["content"]
    assert state.load_group_history(session_id)[-1] == failed_message
    failure_log = [row for row in load_tool_execution_logs(session_id) if row["source"] == "runtime"][0]
    serialized = json.dumps(failure_log, ensure_ascii=False)
    assert "upstream disconnected" in serialized
    assert "hidden-token" not in serialized
    assert "hidden-token" not in json.dumps(parsed, ensure_ascii=False)
    assert parsed[-1][1]["phase"] == "failed"


@pytest.mark.asyncio
async def test_chat_stream_keeps_missing_agent_references_in_session(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _init_noop():
        return None

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待用户",
            "message": {"content": "缺失专家引用应保留，等待用户手动修复。"},
            "suggested_add_agent_names": [],
        }

    monkeypatch.setattr(runtime, "ensure_mcp_and_skills_initialized", _init_noop)
    monkeypatch.setattr(runtime, "load_agent_instances", lambda: [{"name": "存在专家"}])
    monkeypatch.setattr(runtime, "load_app_settings", lambda: {"default_llm": "", "system_prompt": "", "host": {}})
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda _agent, _settings: object())
    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    session_id = "s-missing-agent-ref"
    state.save_session_definitions(
        {
            session_id: {
                "title": "缺失引用",
                "agent_names": ["存在专家", "已删除专家"],
                "host": {"name": "四九"},
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )
    state.save_group_history(session_id, [])

    response = await runtime.group_chat_stream(
        session_id,
        GroupChatRequest(message="继续", message_id="msg-user-1"),
    )
    await _collect_stream_events(response)

    saved = state.load_session_definitions()[session_id]
    assert saved["agent_names"] == ["存在专家", "已删除专家"]


@pytest.mark.asyncio
async def test_session_events_stream_emits_snapshot_event_name_and_runtime_payload(monkeypatch, tmp_path):
    from app.agent import group_session_service
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    session_id = "s-events-contract"
    state.save_session_definitions(
        {
            session_id: {
                "title": "事件协议",
                "agent_names": [],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    response = await group_session_service.group_session_events_stream(session_id)
    body_iter = response.body_iterator
    try:
        first_chunk = await anext(body_iter)
    finally:
        close = getattr(body_iter, "aclose", None)
        if close:
            await close()

    event_type, payload = _parse_sse_block(first_chunk)
    assert event_type == "snapshot"
    assert payload["session_id"] == session_id
    assert payload["runtime"] == {"running": False}
    assert "server_time" in payload
    assert "updated_at" in payload
    assert "type" not in payload
    assert "runtime_state" not in payload


@pytest.mark.asyncio
async def test_session_events_stream_keepalive_payload_contains_only_server_time(monkeypatch, tmp_path):
    from app.agent import group_session_service
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(group_session_service, "_SSE_AGENT_KEEPALIVE_INTERVAL_SEC", 0.001)
    session_id = "s-events-keepalive-contract"
    state.save_session_definitions(
        {
            session_id: {
                "title": "保活事件协议",
                "agent_names": [],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    response = await group_session_service.group_session_events_stream(session_id)
    body_iter = response.body_iterator
    try:
        await anext(body_iter)
        event_type, payload = _parse_sse_block(await anext(body_iter))
    finally:
        close = getattr(body_iter, "aclose", None)
        if close:
            await close()

    assert event_type == "keepalive"
    assert set(payload) == {"server_time"}


@pytest.mark.asyncio
async def test_session_events_stream_message_payload_matches_history_contract(monkeypatch, tmp_path):
    from app.agent import group_session_service
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    session_id = "s-events-message-contract"
    state.save_session_definitions(
        {
            session_id: {
                "title": "消息事件协议",
                "agent_names": [],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )
    message = {
        "message_id": "msg-events-1",
        "speaker": {"type": "expert", "agent_name": "问答专家"},
        "message": {"content": "后台完成的回复"},
        "created_at": "2026070900010000",
    }

    response = await group_session_service.group_session_events_stream(session_id)
    body_iter = response.body_iterator
    try:
        await anext(body_iter)
        await state.publish_group_session_event(session_id, "message", message)
        event_type, payload = _parse_sse_block(await anext(body_iter))
    finally:
        close = getattr(body_iter, "aclose", None)
        if close:
            await close()

    assert event_type == "message"
    assert payload == message


@pytest.mark.asyncio
async def test_session_events_message_publisher_rejects_legacy_message_fields(monkeypatch, tmp_path):
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    legacy_message = {
        "message_id": "msg-legacy",
        "speaker": {"type": "expert", "agent_name": "问答专家"},
        "message": {"content": "旧字段不应进入事件"},
        "created_at": "2026070900010000",
        "role": "assistant",
    }

    with pytest.raises(ValueError):
        await state.publish_group_session_event("s-events-message-contract", "message", legacy_message)


@pytest.mark.asyncio
async def test_session_events_publisher_rejects_chat_stream_event_names(monkeypatch, tmp_path):
    from app.api import group_chat_state as state

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    for event_type in ["route", "progress", "end", "session_update", "tool_start", "tool_result"]:
        with pytest.raises(ValueError):
            await state.publish_group_session_event("s-events-name-contract", event_type, {"run_id": "run-legacy"})


@pytest.mark.asyncio
async def test_delete_group_session_publishes_deleted_session_event(monkeypatch, tmp_path):
    from app.agent import group_session_service
    from app.api import group_chat_state as state
    from app.session_state import paths as session_paths

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    async def _cancel_noop(*_args, **_kwargs):
        return False

    monkeypatch.setattr(group_session_service, "_cancel_group_session_run", _cancel_noop)
    monkeypatch.setattr(group_session_service, "get_current_user", lambda: SimpleNamespace(ctx=SimpleNamespace()))
    monkeypatch.setattr(
        session_paths.SessionLayoutPaths,
        "from_user_ctx",
        staticmethod(lambda _ctx, sid: SimpleNamespace(session_root=tmp_path / sid)),
    )

    class FakeSandboxService:
        async def dispose_session(self, *_args, **_kwargs):
            return None

    monkeypatch.setattr(
        "app.agent.sandbox_workspace_access.get_shared_sandbox_service",
        lambda: FakeSandboxService(),
    )
    published: list[tuple[str, str, dict[str, Any]]] = []

    def _record_event(session_id: str, event_type: str, payload: dict[str, Any] | None = None):
        published.append((session_id, event_type, payload or {}))

    monkeypatch.setattr(group_session_service, "_schedule_group_session_event", _record_event, raising=False)
    state.save_session_definitions(
        {
            "s-delete-events-contract": {
                "title": "删除事件协议",
                "agent_names": [],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    await group_session_service.delete_group_session("s-delete-events-contract")

    assert published == [("s-delete-events-contract", "deleted", {})]


@pytest.mark.asyncio
async def test_expert_turn_uses_contract_phase_names(monkeypatch, tmp_path):
    from app.agent import group_chat_expert_turn as expert_turn
    from app.api import group_chat_state as state

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {"type": "agent_step", "message": AIMessage(content=_expert_final_state_json("专家回答"))}

    runtime_kwargs: dict[str, Any] = {}

    async def _fake_build_runtime(**kwargs):
        runtime_kwargs.update(kwargs)
        return SimpleNamespace(
            blocked=False,
            skill="skill-qa",
            skill_route_diagnostics={},
            agent=FakeAgent(),
            tools=[],
        )

    updates: list[dict[str, Any]] = []

    async def _record_update(_session_id: str, _run_id: str, **kwargs: Any):
        updates.append(kwargs)

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(expert_turn, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(expert_turn, "update_group_run", _record_update)
    state.save_session_definitions(
        {
            "s-expert-phase": {
                "title": "专家阶段",
                "agent_names": ["问答专家"],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    events = [
        _parse_sse_block(item)
        async for item in expert_turn.run_one_expert_turn(
            group_session_id="s-expert-phase",
            run_id="run-1",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-expert-phase"],
            app_settings={"system_prompt": "项目统一提示词"},
            agent_map={"问答专家": {"name": "问答专家", "skills": [{"directory_name": "skill-qa"}]}},
            agent_name="问答专家",
            messages=[],
            discussion_goal="回答问题",
            user_text="你好",
            next_action="请回答",
        )
    ]

    progress_phases = {payload.get("phase") for event, payload in events if event == "progress"}
    update_phases = {item.get("phase") for item in updates}
    assert "agent_running" not in progress_phases | update_phases
    assert "message_ready" not in update_phases
    assert "executing" in progress_phases
    assert "finalizing" in update_phases
    assert runtime_kwargs["extra_system_prompt"] == "项目统一提示词"
    message_payloads = [payload for event, payload in events if event == "message"]
    assert message_payloads[-1]["message"] == {"content": "专家回答"}
    assert message_payloads[-1]["skill_result"] == {
        "execution_status": "succeeded",
    }


@pytest.mark.asyncio
async def test_expert_turn_uses_expert_final_state_as_only_message_source(monkeypatch, tmp_path):
    from app.agent import group_chat_expert_turn as expert_turn
    from app.api import group_chat_state as state

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {"type": "agent_step", "message": AIMessage(content="工具已执行完成。以下是本轮工具返回摘要：\n\nTitle: 沈腾")}
            yield {"type": "agent_step", "message": AIMessage(content=_expert_final_state_json(
                "我已经完成资料整理，并保存到工作区。",
                artifacts=[{"type": "markdown", "name": "资料摘要", "path": "research/summary.md"}],
            ))}

    async def _fake_build_runtime(**_kwargs):
        return SimpleNamespace(
            blocked=False,
            skill="skill-qa",
            skill_route_diagnostics={},
            agent=FakeAgent(),
            tools=[],
        )

    async def _record_update(_session_id: str, _run_id: str, **_kwargs: Any):
        return None

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(expert_turn, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(expert_turn, "update_group_run", _record_update)
    state.save_session_definitions(
        {
            "s-expert-final-content": {
                "title": "专家展示正文",
                "agent_names": ["问答专家"],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    events = [
        _parse_sse_block(item)
        async for item in expert_turn.run_one_expert_turn(
            group_session_id="s-expert-final-content",
            run_id="run-final-content",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-expert-final-content"],
            app_settings={},
            agent_map={"问答专家": {"name": "问答专家", "skills": [{"directory_name": "skill-qa"}]}},
            agent_name="问答专家",
            messages=[],
            discussion_goal="回答问题",
            user_text="你好",
            next_action="请回答",
        )
    ]

    message_payloads = [payload for event, payload in events if event == "message"]
    assert message_payloads[-1]["message"] == {
        "content": "我已经完成资料整理，并保存到工作区。",
        "artifacts": [{"type": "markdown", "name": "资料摘要", "path": "research/summary.md"}],
    }
    assert "工具已执行完成" not in message_payloads[-1]["message"]["content"]
    assert message_payloads[-1]["skill_result"] == {
        "execution_status": "succeeded",
    }


@pytest.mark.asyncio
async def test_expert_turn_rejects_missing_expert_final_state(monkeypatch, tmp_path):
    from app.agent import group_chat_expert_turn as expert_turn
    from app.api import group_chat_state as state

    platform_tool_summary = "工具已执行完成。以下是本轮工具返回摘要：\n\n```text\nTitle: 沈腾\nURL: https://example.test\n```"

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {
                "type": "tool_step",
                "tool_results": [
                    {
                        "execution_status": "succeeded",
                        "tool_call": {
                            "id": "tc-search",
                            "name": "web_search_exa",
                            "kind": "mcp",
                            "arguments": {"query": "沈腾"},
                        },
                        "output": {"content": "检索摘要"},
                    }
                ],
            }
            yield {"type": "agent_step", "message": AIMessage(content=platform_tool_summary)}

    async def _fake_build_runtime(**_kwargs):
        return SimpleNamespace(
            blocked=False,
            skill="skill-web-research",
            skill_route_diagnostics={},
            agent=FakeAgent(),
            tools=[],
        )

    async def _record_update(_session_id: str, _run_id: str, **_kwargs: Any):
        return None

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(expert_turn, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(expert_turn, "update_group_run", _record_update)
    state.save_session_definitions(
        {
            "s-expert-tool-summary": {
                "title": "专家工具摘要过滤",
                "agent_names": ["信息检索专家"],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    outcome = expert_turn.ExpertTurnOutcome()
    events = [
        _parse_sse_block(item)
        async for item in expert_turn.run_one_expert_turn(
            group_session_id="s-expert-tool-summary",
            run_id="run-tool-summary",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-expert-tool-summary"],
            app_settings={},
            agent_map={"信息检索专家": {"name": "信息检索专家", "skills": [{"directory_name": "skill-web-research"}]}},
            agent_name="信息检索专家",
            messages=[],
            discussion_goal="搜集资料",
            user_text="我要写沈腾",
            next_action="请搜集资料",
            outcome=outcome,
        )
    ]

    assert [event for event, _payload in events if event == "message"] == []
    error_payloads = [payload for event, payload in events if event == "error"]
    assert error_payloads[-1]["code"] == "EXPERT_FINAL_STATE_INVALID"
    assert [item["tool_call"]["name"] for item in outcome.tool_results] == ["web_search_exa"]


@pytest.mark.asyncio
async def test_expert_turn_continue_persists_and_emits_message(monkeypatch, tmp_path):
    from app.agent import group_chat_expert_turn as expert_turn
    from app.api import group_chat_state as state

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {
                "type": "agent_step",
                "message": AIMessage(
                    content=_expert_final_state_json(
                        "本轮先报告已完成的结果。",
                        agent_turn="continue",
                        skill_session="keep",
                    )
                ),
            }

    async def _fake_build_runtime(**_kwargs):
        return SimpleNamespace(
            blocked=False,
            skill="skill-qa",
            skill_route_diagnostics={},
            agent=FakeAgent(),
            tools=[],
        )

    async def _record_update(_session_id: str, _run_id: str, **_kwargs: Any):
        return None

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(expert_turn, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(expert_turn, "update_group_run", _record_update)
    state.save_session_definitions(
        {
            "s-expert-continue": {
                "title": "专家继续",
                "agent_names": ["问答专家"],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )
    messages: list[dict[str, Any]] = []
    outcome = expert_turn.ExpertTurnOutcome()

    events = [
        _parse_sse_block(item)
        async for item in expert_turn.run_one_expert_turn(
            group_session_id="s-expert-continue",
            run_id="run-continue",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-expert-continue"],
            app_settings={},
            agent_map={"问答专家": {"name": "问答专家", "skills": [{"directory_name": "skill-qa"}]}},
            agent_name="问答专家",
            messages=messages,
            discussion_goal="回答问题",
            user_text="你好",
            next_action="请回答",
            outcome=outcome,
        )
    ]

    assert [payload["message"]["content"] for event, payload in events if event == "message"] == [
        "本轮先报告已完成的结果。"
    ]
    assert messages[-1]["message"]["content"] == "本轮先报告已完成的结果。"
    assert state.load_group_history("s-expert-continue")[-1]["message"]["content"] == "本轮先报告已完成的结果。"
    assert outcome.status == "succeeded"
    assert outcome.agent_turn == "continue"
    assert outcome.skill_session == "keep"
    assert state.load_group_orchestration_state("s-expert-continue")["skill_sessions"] == {
        "问答专家": {"skill": "skill-qa"}
    }


@pytest.mark.asyncio
async def test_expert_turn_persists_skill_session_cleanup_from_runtime_build(monkeypatch, tmp_path):
    from app.agent import group_chat_expert_turn as expert_turn
    from app.api import group_chat_state as state

    async def _fake_build_runtime(**kwargs):
        kwargs["orchestration_state"].pop("skill_sessions", None)
        return SimpleNamespace(
            blocked=True,
            skill="",
            skill_route_diagnostics={"blocking_error": "expert_skill_content_missing"},
            agent=None,
            tools=[],
        )

    async def _record_update(_session_id: str, _run_id: str, **_kwargs: Any):
        return None

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(expert_turn, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(expert_turn, "update_group_run", _record_update)
    state.save_session_definitions(
        {
            "s-stale-skill-session": {
                "title": "失效 Skill Session",
                "agent_names": ["问答专家"],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )
    state.write_group_orchestration_state(
        "s-stale-skill-session",
        {"skill_sessions": {"问答专家": {"skill": "removed-skill"}}},
    )

    events = [
        _parse_sse_block(item)
        async for item in expert_turn.run_one_expert_turn(
            group_session_id="s-stale-skill-session",
            run_id="run-stale-skill-session",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-stale-skill-session"],
            app_settings={},
            agent_map={"问答专家": {"name": "问答专家", "skills": [{"directory_name": "skill-qa"}]}},
            agent_name="问答专家",
            messages=[],
            discussion_goal="回答问题",
            user_text="你好",
            next_action="请回答",
        )
    ]

    assert [event for event, _payload in events if event == "error"] == ["error"]
    assert state.load_group_orchestration_state("s-stale-skill-session") == {}


@pytest.mark.asyncio
async def test_keepalive_progress_keeps_current_runtime_phase_after_tool_call(monkeypatch, tmp_path):
    from app.agent import group_chat_expert_turn as expert_turn
    from app.api import group_chat_state as state

    class FakeAgent:
        async def astream(self, *_args, **_kwargs):
            yield {
                "type": "agent_step",
                "message": AIMessage(
                    content="需要调用工具",
                    tool_calls=[{"id": "tool-1", "name": "read_workspace_file", "args": {"path": "input.md"}}],
                ),
            }
            yield {"type": "keepalive"}
            yield {"type": "agent_step", "message": AIMessage(content=_expert_final_state_json("工具后回答"))}

    async def _fake_build_runtime(**_kwargs):
        return SimpleNamespace(
            blocked=False,
            skill="skill-qa",
            skill_route_diagnostics={},
            agent=FakeAgent(),
            tools=[],
        )

    updates: list[dict[str, Any]] = []

    async def _record_update(_session_id: str, _run_id: str, **kwargs: Any):
        updates.append(kwargs)

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    monkeypatch.setattr(expert_turn, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(expert_turn, "update_group_run", _record_update)
    state.save_session_definitions(
        {
            "s-tool-keepalive-phase": {
                "title": "工具阶段",
                "agent_names": ["问答专家"],
                "created_at": "2026070900000000",
                "updated_at": "2026070900000000",
            }
        }
    )

    events = [
        _parse_sse_block(item)
        async for item in expert_turn.run_one_expert_turn(
            group_session_id="s-tool-keepalive-phase",
            run_id="run-tool",
            session_definitions=state.load_session_definitions(),
            session_item=state.load_session_definitions()["s-tool-keepalive-phase"],
            app_settings={},
            agent_map={"问答专家": {"name": "问答专家", "skills": [{"directory_name": "skill-qa"}]}},
            agent_name="问答专家",
            messages=[],
            discussion_goal="回答问题",
            user_text="你好",
            next_action="请回答",
        )
    ]

    progress_phases = [payload.get("phase") for event, payload in events if event == "progress"]
    assert [item.get("phase") for item in updates if item.get("phase")] == [
        "agent_routed",
        "executing",
        "tool_running",
        "finalizing",
    ]
    assert progress_phases == ["executing", "tool_running", "tool_running"]
