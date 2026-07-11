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
                "artifacts": [
                    {"path": "reports/missing-type-and-name.md"},
                    {"type": "file", "path": "reports/missing-name.md"},
                    {"type": "legacy", "name": "旧类型", "path": "reports/legacy.md"},
                    {"type": "file", "name": "报告", "path": "reports/report.md", "data": {"inline": True}},
                ]
            }
        ]
    )

    assert artifacts == [{"type": "file", "name": "报告", "path": "reports/report.md"}]


def test_build_expert_skill_result_marks_failed_before_blocked_and_collects_artifacts():
    from app.agent.group_chat_tool_result_content import build_expert_skill_result

    result = build_expert_skill_result(
        content="",
        tool_results=[
            {
                "execution_status": "blocked",
                "message": "需要补充链接",
                "tool_call": {"name": "collect_inputs"},
            },
            {
                "execution_status": "failed",
                "message": "脚本失败",
                "tool_call": {"name": "run_skill_script"},
                "artifacts": [{"type": "file", "name": "日志", "path": "reports/failure.md"}],
            },
        ],
    )

    assert result["execution_status"] == "failed"
    assert result["content"].startswith("当前步骤失败：run_skill_script")
    assert result["artifacts"] == [{"type": "file", "name": "日志", "path": "reports/failure.md"}]


def test_build_expert_skill_result_uses_empty_model_content_placeholder():
    from app.agent.group_chat_tool_result_content import build_expert_skill_result

    result = build_expert_skill_result(content="", tool_results=[])

    assert result["execution_status"] == "succeeded"
    assert result["content"] == "模型没有返回可展示的文字内容。"


def test_build_expert_skill_result_rejects_tool_summary_as_success():
    from app.agent.group_chat_tool_result_content import build_expert_skill_result

    result = build_expert_skill_result(
        content="工具已执行完成。以下是本轮工具返回摘要：\n\n```text\n目录 . 下：（空）\n```",
        tool_results=[
            {
                "execution_status": "succeeded",
                "tool_call": {"name": "list_workspace_directory"},
                "output": {"text": "目录 . 下：（空）"},
            }
        ],
    )

    assert result["execution_status"] == "failed"
    assert result["content"] == "模型没有返回可展示的专家回复；本轮只有工具执行摘要。请重新执行本轮专家步骤。"
    assert result["next_action"] == {
        "handoff": "user",
        "resume": "same_skill",
        "reason": "protocol_error",
        "instruction": "模型没有返回可展示的专家回复；请重新执行本轮专家步骤。",
    }


def test_build_expert_skill_result_turns_successful_artifacts_into_minimal_delivery():
    from app.agent.group_chat_tool_result_content import build_expert_skill_result

    result = build_expert_skill_result(
        content="工具已执行完成。以下是本轮工具返回摘要：\n\n```text\n已写入当前 Chat 工作区文件：drafts/shenteng.md\n```",
        tool_results=[
            {
                "execution_status": "succeeded",
                "tool_call": {"name": "write_workspace_file"},
                "output": {"text": "已写入当前 Chat 工作区文件：drafts/shenteng.md"},
                "artifacts": [{"type": "file", "name": "沈腾演艺生涯", "path": "drafts/shenteng.md"}],
            }
        ],
    )

    assert result["execution_status"] == "succeeded"
    assert result["content"] == "已生成工作区产物：\n- 沈腾演艺生涯：drafts/shenteng.md"
    assert result["artifacts"] == [{"type": "file", "name": "沈腾演艺生涯", "path": "drafts/shenteng.md"}]
    assert result["next_action"] == {
        "handoff": "host",
        "resume": "none",
        "reason": "stage_completed",
        "instruction": "已生成工作区产物：\n- 沈腾演艺生涯：drafts/shenteng.md",
    }


def test_build_expert_skill_result_prefers_script_payload_over_tool_summary():
    from app.agent.group_chat_tool_result_content import build_expert_skill_result

    payload = {
        "schema_version": "expert_final_state.v2",
        "execution_status": "succeeded",
        "artifacts": [{"type": "file", "name": "文章", "path": "drafts/shenteng.md"}],
        "next_action": {
            "handoff": "host",
            "resume": "none",
            "reason": "stage_completed",
            "instruction": "文章已完整起草并保存到工作区。",
        },
    }

    result = build_expert_skill_result(
        content="工具已执行完成。以下是本轮工具返回摘要：\n\n```text\n脚本执行成功\n```",
        tool_results=[
            {
                "execution_status": "succeeded",
                "tool_call": {"id": "call-1", "name": "run_skill_script_doc", "kind": "script"},
                "output": {"stdout": json.dumps(payload, ensure_ascii=False)},
            }
        ],
    )

    assert result["execution_status"] == "succeeded"
    assert result["content"] == "文章已完整起草并保存到工作区。"
    assert result["artifacts"] == [{"type": "file", "name": "文章", "path": "drafts/shenteng.md"}]
    assert result["next_action"] == payload["next_action"]


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
            "next_speaker": "user",
            "next_action": "请先补充任务目标。",
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
        GroupChatRequest(message="你好", client_message_id="client-1"),
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
            "next_speaker": "user",
            "next_action": "等待用户补充。",
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

    token = set_current_user_identity(user_id="user-stream-stable", username="stream@example.com")
    try:
        response = await runtime.group_chat_stream(
            session_id,
            GroupChatRequest(message="你好", client_message_id="client-user-id"),
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
            "next_speaker": "文档合著专家",
            "next_action": "请先写文章大纲。",
            "suggested_add_agent_names": [],
        }

    async def _expert_turn(**kwargs):
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
            request=GroupChatRequest(message="帮我写文章", client_message_id="client-1"),
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
    assert parsed[0][1]["message"]["content"] == "下面由 文档合著专家 发言。"
    assert parsed[1][0] == "route"
    assert parsed[1][1]["agent_name"] == "文档合著专家"


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
            "next_speaker": "文档合著专家",
            "next_action": "请先写文章大纲。",
            "suggested_add_agent_names": [],
        },
        {
            "current_phase": "等待确认",
            "next_speaker": "user",
            "next_action": "大纲已完成，请确认是否继续写正文。",
            "suggested_add_agent_names": [],
        },
    ]

    async def _host_decision(*_args, **_kwargs):
        return decisions.pop(0)

    async def _expert_turn(**kwargs):
        expert_msg = {
            "message_id": "msg-expert-1",
            "speaker": {"type": "expert", "agent_name": kwargs["agent_name"], "skill": "document-coauthor"},
            "message": {"content": "大纲已完成。"},
            "created_at": "2026071100000100",
            "skill_result": {
                "execution_status": "succeeded",
                "content": "大纲已完成。",
                "artifacts": [],
                "next_action": {
                    "handoff": "host",
                    "resume": "none",
                    "reason": "stage_completed",
                    "instruction": "大纲已完成。",
                },
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
            request=GroupChatRequest(message="帮我写文章", client_message_id="client-1"),
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
        "下面由 文档合著专家 发言。",
        "大纲已完成。",
        "大纲已完成，请确认是否继续写正文。",
    ]
    assert parsed[-1][0] == "end"
    assert parsed[-1][1]["phase"] == "awaiting_user"
    assert decisions == []


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
            "next_speaker": "user",
            "next_action": "缺失专家引用应保留，等待用户手动修复。",
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
        GroupChatRequest(message="继续", client_message_id="client-1"),
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
            yield {"type": "agent_step", "message": AIMessage(content="专家回答")}

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
            app_settings={},
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
    message_payloads = [payload for event, payload in events if event == "message"]
    assert message_payloads[-1]["message"] == {"content": "专家回答"}


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
            yield {"type": "agent_step", "message": AIMessage(content="工具后回答")}

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
