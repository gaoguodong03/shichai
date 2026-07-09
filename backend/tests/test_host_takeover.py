"""Strict host-routing tests for the current runtime contract."""
from __future__ import annotations

import pytest

from app.agent.group_host_decision import HOST_PROTOCOL_ERROR_MESSAGE, parse_strict_host_scheduler_output
from app.agent.group_chat_host_runtime import _host_decide_by_agent
from app.agent.session_contracts import GroupChatRequest


def test_strict_host_response_rejects_extra_fields():
    raw = '```json\n{"current_phase": "补充信息", "next_speaker": "专家甲", "next_action": "请补充要点", "extra_note": "继续"}\n```'
    out = parse_strict_host_scheduler_output(raw, [{"name": "专家甲"}], host_mode="scene")
    assert out["next_speaker"] == "user"
    assert out["next_action"] == HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == "protocol_error"


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


@pytest.mark.asyncio
async def test_host_decide_uses_platform_scheduler_prompt(monkeypatch):
    calls = {}
    session_item = {"scheduler_state": {"current_phase": "阶段1"}}

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
    )

    assert out["next_speaker"] == "写作专家"
    assert out["next_action"] == "请写大纲"
    system_prompt = calls["messages"][0].content
    user_prompt = calls["messages"][1].content
    assert "主持人系统提示" in system_prompt
    assert "网文专用主持 Skill 正文" in system_prompt
    assert "只允许输出上述字段" in user_prompt
    assert '"next_action"' in user_prompt
    assert session_item["scheduler_state"] == {
        "current_phase": "阶段2",
        "next_speaker": "写作专家",
        "next_action": "请写大纲",
    }
