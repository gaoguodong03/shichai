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
    from app.agent.group_chat_runtime import _collect_artifacts

    artifacts = _collect_artifacts(
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

    async def _register_run(_session_id: str, *, user_id: str, task):
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
    from app.agent import group_chat_runtime as runtime
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
    monkeypatch.setattr(runtime, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(runtime, "update_group_run", _record_update)
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
        async for item in runtime._run_one_expert_turn(
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
    from app.agent import group_chat_runtime as runtime
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
    monkeypatch.setattr(runtime, "build_expert_turn_runtime", _fake_build_runtime)
    monkeypatch.setattr(runtime, "update_group_run", _record_update)
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
        async for item in runtime._run_one_expert_turn(
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
