"""Strict host-routing tests for the current runtime contract."""
from __future__ import annotations

import pytest

from app.agent.group_host_decision import HOST_PROTOCOL_ERROR_MESSAGE, parse_strict_host_scheduler_output
from app.agent.group_chat_host_runtime import _host_decide_by_agent, _host_skill_directory
from app.agent.session_contracts import GroupChatRequest
from app.api import group_chat_state as state


def test_strict_host_response_rejects_extra_fields():
    raw = '```json\n{"current_phase": "补充信息", "next_speaker": "专家甲", "next_action": "请补充要点", "extra_note": "继续"}\n```'
    out = parse_strict_host_scheduler_output(raw, [{"name": "专家甲"}], host_mode="scene")
    assert out["next_speaker"] == "user"
    assert out["next_action"] == HOST_PROTOCOL_ERROR_MESSAGE
    assert "interrupt_reason" not in out


def test_strict_host_response_accepts_next_action_only():
    raw = '```json\n{"current_phase": "补充信息", "next_speaker": "user", "next_action": "请补充信息"}\n```'
    out = parse_strict_host_scheduler_output(raw, [], host_mode="recruitment")
    assert out["next_speaker"] == "user"
    assert out["next_action"] == "请补充信息"


def test_group_chat_request_keeps_at_mention_as_plain_text():
    request = GroupChatRequest(
        message="@文书专员 请先写提纲",
        client_message_id="client-1",
    )
    assert request.target_agent_name is None
    assert request.message == "@文书专员 请先写提纲"


def test_group_chat_request_accepts_structured_target_agent_name():
    request = GroupChatRequest(
        message="请先写提纲",
        client_message_id="client-1",
        target_agent_name="文书专员",
    )
    assert request.target_agent_name == "文书专员"


def test_host_skill_directory_ignores_legacy_skills_list():
    assert _host_skill_directory({"name": "四九", "skills": [{"directory_name": "group-host-webnovel"}]}) == ""
    assert _host_skill_directory({"name": "四九", "skill_directory": "group-host-webnovel"}) == "group-host-webnovel"


def test_host_snapshot_runtime_shape_does_not_emit_legacy_skills_list():
    from app.agent.group_chat_runtime import _host_snapshot_to_agent

    host_agent = _host_snapshot_to_agent(
        {
            "host": {
                "name": "四九",
                "llm_name": "qwen",
                "system_prompt": "主持人规则",
                "skill_directory": "group-host-webnovel",
            }
        }
    )

    assert host_agent == {
        "name": "四九",
        "description": "群聊主持人",
        "llm_name": "qwen",
        "system_prompt": "主持人规则",
        "skill_directory": "group-host-webnovel",
    }


@pytest.mark.asyncio
async def test_continuation_runs_owner_then_returns_to_host(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.write_group_orchestration_state(
        "s-continuation",
        {
            "continuation": {
                "owner_agent_name": "文书专员",
                "skill_policy": "keep",
                "skill": "writer-skill",
                "next_action": "继续根据用户补充写正文。",
            }
        },
    )

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待确认",
            "next_speaker": "user",
            "next_action": "请确认是否继续。",
            "suggested_add_agent_names": [],
        }

    captured = {}

    async def _fake_expert_turn(**kwargs):
        captured["agent_name"] = kwargs["agent_name"]
        captured["next_action"] = kwargs["next_action"]
        if False:
            yield ""

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "run_one_expert_turn", _fake_expert_turn)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-continuation",
            request=GroupChatRequest(message="这里是补充材料", client_message_id="client-1"),
            run_id="run-1",
            session_definitions={"s-continuation": {"agent_names": ["文书专员"], "host": {"name": "四九"}}},
            session_item={"agent_names": ["文书专员"], "host": {"name": "四九"}},
            app_settings={},
            agent_map={"文书专员": {"name": "文书专员", "skills": [{"directory_name": "writer-skill"}]}},
            agent_names=["文书专员"],
            messages=[],
            discussion_goal="写文章",
            user_text="这里是补充材料",
        )
    ]

    assert captured == {"agent_name": "文书专员", "next_action": "继续根据用户补充写正文。"}
    assert any('"message": {"content": "请确认是否继续。"}' in event for event in events)
    assert any('"phase": "awaiting_user"' in event for event in events)


@pytest.mark.asyncio
async def test_host_takeover_text_does_not_clear_short_term_route_state(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.write_group_orchestration_state(
        "s-host-takeover-text",
        {
            "continuation": {
                "owner_agent_name": "文书专员",
                "skill_policy": "keep",
                "skill": "writer-skill",
                "next_action": "继续旧 Skill",
            },
        },
    )

    expert_calls = 0

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待确认",
            "next_speaker": "user",
            "next_action": "请确认是否继续旧 Skill。",
            "suggested_add_agent_names": [],
        }

    async def _expert_turn(**kwargs):
        nonlocal expert_calls
        expert_calls += 1
        assert kwargs["agent_name"] == "文书专员"
        assert kwargs["next_action"] == "继续旧 Skill"
        yield 'event: end\ndata: {"type":"end","run_id":"run-1","phase":"awaiting_user","waiting_for_user":true}\n\n'

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-host-takeover-text",
            request=GroupChatRequest(message="请主持人接管，重新安排", client_message_id="client-1"),
            run_id="run-1",
            session_definitions={"s-host-takeover-text": {"agent_names": ["文书专员"], "host": {"name": "四九"}}},
            session_item={"agent_names": ["文书专员"], "host": {"name": "四九"}},
            app_settings={},
            agent_map={"文书专员": {"name": "文书专员", "skills": [{"directory_name": "writer-skill"}]}},
            agent_names=["文书专员"],
            messages=[],
            discussion_goal="写文章",
            user_text="请主持人接管，重新安排",
        )
    ]

    assert expert_calls == 1
    assert any('"message": {"content": "请确认是否继续旧 Skill。"}' in event for event in events)


@pytest.mark.asyncio
async def test_existing_member_suppresses_unsolicited_recruitment(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "执行中",
            "next_speaker": "user",
            "next_action": "请补充材料。",
            "suggested_add_agent_names": ["检索专家"],
        }

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-recruit-suppressed",
            request=GroupChatRequest(message="继续写正文", client_message_id="client-1"),
            run_id="run-1",
            session_definitions={"s-recruit-suppressed": {"agent_names": ["文书专员"], "host": {"name": "四九"}}},
            session_item={"agent_names": ["文书专员"], "host": {"name": "四九"}},
            app_settings={},
            agent_map={
                "文书专员": {"name": "文书专员"},
                "检索专家": {"name": "检索专家"},
            },
            agent_names=["文书专员"],
            messages=[],
            discussion_goal="写文章",
            user_text="继续写正文",
        )
    ]

    end_events = [event for event in events if event.startswith("event: end")]
    assert end_events
    assert '"phase": "awaiting_user"' in end_events[-1]
    assert "suggested_add_agent_names" not in end_events[-1]


@pytest.mark.asyncio
async def test_zero_member_session_keeps_host_recruitment_suggestions(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "招募",
            "next_speaker": "user",
            "next_action": "建议先邀请检索专家。",
            "suggested_add_agent_names": ["检索专家"],
        }

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-recruit-zero-member",
            request=GroupChatRequest(message="帮我写文章", client_message_id="client-1"),
            run_id="run-1",
            session_definitions={"s-recruit-zero-member": {"agent_names": [], "host": {"name": "四九"}}},
            session_item={"agent_names": [], "host": {"name": "四九"}},
            app_settings={},
            agent_map={"检索专家": {"name": "检索专家"}},
            agent_names=[],
            messages=[],
            discussion_goal="写文章",
            user_text="帮我写文章",
        )
    ]

    end_events = [event for event in events if event.startswith("event: end")]
    assert end_events
    assert '"phase": "recruiting"' in end_events[-1]
    assert '"suggested_add_agent_names": ["检索专家"]' in end_events[-1]


@pytest.mark.asyncio
async def test_zero_member_session_uses_host_only_recommendation_branch(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.save_session_definitions(
        {
            "s-zero-host-only": {
                "title": "0 专家",
                "agent_names": [],
                "host": {"name": "自定义主持"},
                "created_at": "2026071100000000",
                "updated_at": "2026071100000000",
            }
        }
    )
    state.save_group_history("s-zero-host-only", [])

    async def _scheduler_must_not_run(*_args, **_kwargs):
        raise AssertionError("zero-member sessions must use the host-only recommendation branch")

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _scheduler_must_not_run)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-zero-host-only",
            request=GroupChatRequest(message="帮我写文章", client_message_id="client-1"),
            run_id="run-1",
            session_definitions={"s-zero-host-only": {"agent_names": [], "host": {"name": "自定义主持"}}},
            session_item={"agent_names": [], "host": {"name": "自定义主持"}},
            app_settings={},
            agent_map={
                "写作专家": {"name": "写作专家", "description": "写作 文案 文章"},
                "检索专家": {"name": "检索专家", "description": "资料检索"},
            },
            agent_names=[],
            messages=[],
            discussion_goal="帮我写文章",
            user_text="帮我写文章",
        )
    ]

    message_events = [event for event in events if event.startswith("event: message")]
    end_events = [event for event in events if event.startswith("event: end")]
    assert message_events
    assert '"speaker": {"type": "host", "agent_name": "自定义主持"}' in message_events[-1]
    assert end_events
    assert '"phase": "recruiting"' in end_events[-1]
    assert '"suggested_add_agent_names": ["写作专家"]' in end_events[-1]


@pytest.mark.asyncio
async def test_host_decide_uses_platform_scheduler_prompt(monkeypatch):
    calls = {}
    session_item = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, skill_id):
            assert skill_id == "group-host-webnovel"
            return "网文专用主持 Skill 正文"

    class FakeResponse:
        content = '```json\n{"current_phase": "阶段2", "next_speaker": "写作专家", "next_action": "请写大纲"}\n```'

    class FakeClient:
        async def ainvoke(self, messages):
            calls["messages"] = messages
            return FakeResponse()

    class FakeLlm:
        def get_client(self):
            return FakeClient()

    monkeypatch.setattr("app.agent.group_chat_host_runtime._request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr("app.agent.group_chat_host_runtime._llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)

    out = await _host_decide_by_agent(
        llm=FakeLlm(),
        host_agent={
            "name": "五九",
            "description": "群聊主持人",
            "skill_directory": "group-host-webnovel",
            "system_prompt": "主持人系统提示",
        },
        agent_profiles=[{"name": "写作专家", "description": "写作"}],
        discussion_goal="写网文",
        recent_messages="用户：写一个故事",
        last_speaker_agent_name=None,
        extra_system_prompt="",
        group_session_id="group-1",
        app_settings={},
        session_item=session_item,
        host_scheduler_state={"current_phase": "阶段1"},
    )

    assert out["next_speaker"] == "写作专家"
    assert out["next_action"] == "请写大纲"
    system_prompt = calls["messages"][0].content
    user_prompt = calls["messages"][1].content
    assert "主持人系统提示" in system_prompt
    assert "网文专用主持 Skill 正文" in system_prompt
    assert "只允许输出上述字段" in user_prompt
    assert '"next_action"' in user_prompt
    assert "scheduler_state" not in session_item


@pytest.mark.asyncio
async def test_host_decide_retries_once_on_protocol_output(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class FakeClient:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                return FakeResponse(
                    '安排如下：\n```json\n{"current_phase":"阶段1","next_speaker":"写作专家","next_action":"请写大纲"}\n```'
                )
            return FakeResponse('{"current_phase":"阶段1","next_speaker":"写作专家","next_action":"请写大纲"}')

    class FakeLlm:
        def get_client(self):
            return FakeClient()

    monkeypatch.setattr("app.agent.group_chat_host_runtime._request_skills_loader", lambda: None)
    monkeypatch.setattr("app.agent.group_chat_host_runtime._llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)

    out = await _host_decide_by_agent(
        llm=FakeLlm(),
        host_agent={"name": "四九"},
        agent_profiles=[{"name": "写作专家", "description": "写作"}],
        discussion_goal="写文章",
        recent_messages="用户：写文章",
        last_speaker_agent_name="写作专家",
        extra_system_prompt="",
        group_session_id="group-1",
        app_settings={},
        host_scheduler_state={"current_phase": "阶段1"},
    )

    assert len(calls) == 2
    assert out["next_speaker"] == "写作专家"
    assert out["next_action"] == "请写大纲"
    retry_prompt = calls[1][1].content
    assert "主持人调度输出未通过平台 JSON 协议校验" in retry_prompt
    assert '"suggested_add_agent_names"' in retry_prompt
