"""Strict host-routing tests for the current runtime contract."""
from __future__ import annotations

import json
import logging

import pytest

from app.agent.group_host_decision import HOST_PROTOCOL_ERROR_MESSAGE, parse_strict_host_scheduler_output
from app.agent.group_chat_host_runtime import _host_decide_by_agent, _host_skill_directory
from app.agent.session_contracts import GroupChatRequest
from app.api import group_chat_state as state


class _RecruitmentResponse:
    def __init__(self, names: list[str]):
        self.content = json.dumps({"suggested_add_agent_names": names}, ensure_ascii=False)


class _RecruitmentClient:
    def __init__(self, names: list[str]):
        self._names = names

    async def ainvoke(self, _messages):
        return _RecruitmentResponse(self._names)


class _RecruitmentLlm:
    def __init__(self, names: list[str]):
        self._names = names

    def get_client(self):
        return _RecruitmentClient(self._names)


def test_strict_host_response_rejects_extra_fields():
    raw = '{"current_phase": "补充信息", "next_speaker": "专家甲", "next_action": "请补充要点", "extra_note": "继续"}'
    out = parse_strict_host_scheduler_output(raw, [{"name": "专家甲"}], host_mode="scene")
    assert out["message"] == {
        "content": HOST_PROTOCOL_ERROR_MESSAGE,
        "target_agent_name": "user",
    }
    assert "interrupt_reason" not in out


def test_strict_host_response_accepts_wait_message():
    raw = (
        '{"current_phase": "补充信息", '
        '"message": {"content": "请补充信息", "target_agent_name": "user"}}'
    )
    out = parse_strict_host_scheduler_output(raw, [], host_mode="recruitment")
    assert out["message"] == {"content": "请补充信息", "target_agent_name": "user"}


def test_group_chat_request_keeps_at_mention_as_plain_text():
    request = GroupChatRequest(
        message_id="msg-user-1",
        message="@文书专员 请先写提纲",
    )
    assert request.target_agent_name is None
    assert request.message == "@文书专员 请先写提纲"


def test_group_chat_request_accepts_structured_target_agent_name():
    request = GroupChatRequest(
        message_id="msg-user-1",
        message="请先写提纲",
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


def test_host_snapshot_with_empty_prompt_stays_empty():
    from app.agent.group_chat_runtime import _host_snapshot_to_agent

    host_agent = _host_snapshot_to_agent({"host": {"name": "四九", "system_prompt": ""}})

    assert host_agent["system_prompt"] == ""


@pytest.mark.asyncio
async def test_skill_session_does_not_route_owner_without_host_target(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.write_group_orchestration_state(
        "s-skill-session",
        {
            "skill_sessions": {"文书专员": {"skill": "writer-skill"}}
        },
    )

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待确认",
            "message": {"content": "请确认是否继续。", "target_agent_name": "user"},
            "suggested_add_agent_names": [],
        }

    captured = {}

    async def _fake_expert_turn(**kwargs):
        captured["agent_name"] = kwargs["agent_name"]
        captured["next_action"] = kwargs["next_action"]
        kwargs["outcome"].succeed()
        if False:
            yield ""

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "run_one_expert_turn", _fake_expert_turn)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-skill-session",
            request=GroupChatRequest(message="这里是补充材料", message_id="msg-user-1"),
            run_id="run-1",
            session_definitions={"s-skill-session": {"agent_names": ["文书专员"], "host": {"name": "四九"}}},
            session_item={"agent_names": ["文书专员"], "host": {"name": "四九"}},
            app_settings={},
            agent_map={"文书专员": {"name": "文书专员", "skills": [{"directory_name": "writer-skill"}]}},
            agent_names=["文书专员"],
            messages=[],
            discussion_goal="写文章",
            user_text="这里是补充材料",
        )
    ]

    assert any(
        '"message": {"content": "请确认是否继续。", "target_agent_name": "user"}' in event
        for event in events
    )
    assert any('"phase": "awaiting_user"' in event for event in events)
    assert captured == {}
    assert state.load_group_orchestration_state("s-skill-session")["skill_sessions"]["文书专员"]["skill"] == "writer-skill"


@pytest.mark.asyncio
async def test_host_takeover_text_does_not_execute_skill_session_route(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)
    state.write_group_orchestration_state(
        "s-host-takeover-text",
        {
            "skill_sessions": {"文书专员": {"skill": "writer-skill"}},
        },
    )

    expert_calls = 0

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "等待确认",
            "message": {"content": "请确认是否继续旧 Skill。", "target_agent_name": "user"},
            "suggested_add_agent_names": [],
        }

    async def _expert_turn(**kwargs):
        nonlocal expert_calls
        expert_calls += 1
        kwargs["outcome"].succeed()
        yield 'event: end\ndata: {"type":"end","run_id":"run-1","phase":"awaiting_user","waiting_for_user":true}\n\n'

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "run_one_expert_turn", _expert_turn)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-host-takeover-text",
            request=GroupChatRequest(message="请主持人接管，重新安排", message_id="msg-user-1"),
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

    assert expert_calls == 0
    assert any(
        '"message": {"content": "请确认是否继续旧 Skill。", "target_agent_name": "user"}' in event
        for event in events
    )
    assert state.load_group_orchestration_state("s-host-takeover-text")["skill_sessions"]["文书专员"]["skill"] == "writer-skill"


@pytest.mark.asyncio
async def test_existing_member_suppresses_unsolicited_recruitment(monkeypatch, tmp_path):
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "执行中",
            "message": {"content": "请补充材料。", "target_agent_name": "user"},
            "suggested_add_agent_names": ["检索专家"],
        }

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: object())

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-recruit-suppressed",
            request=GroupChatRequest(message="继续写正文", message_id="msg-user-1"),
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
    from app.agent import group_chat_host_runtime as host_runtime
    from app.agent import group_chat_runtime as runtime

    monkeypatch.setattr(state, "GROUP_SESSIONS_ROOT", tmp_path)

    async def _host_decision(*_args, **_kwargs):
        return {
            "current_phase": "招募",
            "message": {"content": "建议先邀请检索专家。", "target_agent_name": "user"},
            "suggested_add_agent_names": ["检索专家"],
        }

    monkeypatch.setattr(runtime, "_host_decide_by_agent", _host_decision)
    monkeypatch.setattr(host_runtime, "_llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: _RecruitmentLlm(["检索专家"]))

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-recruit-zero-member",
            request=GroupChatRequest(message="帮我写文章", message_id="msg-user-1"),
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
    from app.agent import group_chat_host_runtime as host_runtime
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
    monkeypatch.setattr(host_runtime, "_llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "_get_llm_for_agent", lambda *_args, **_kwargs: _RecruitmentLlm(["写作专家"]))

    events = [
        item
        async for item in runtime._run_contract_events(
            group_session_id="s-zero-host-only",
            request=GroupChatRequest(message="帮我写文章", message_id="msg-user-1"),
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
    calls = []
    session_item = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, skill_id):
            assert skill_id == "group-host-webnovel"
            return "网文专用主持 Skill 正文"

    class FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class FakeClient:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                return FakeResponse(
                    '{"current_phase":"阶段2","target_agent_name":"写作专家",'
                    '"selected_action":"调度写作专家完成大纲。",'
                    '"suggested_add_agent_names":[]}'
                )
            return FakeResponse('{"content":"请写大纲","attachments":[],"artifacts":[]}')

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
        extra_system_prompt="项目统一提示词\n\n场景共享任务契约",
        group_session_id="group-1",
        app_settings={},
        session_item=session_item,
        host_scheduler_state={"current_phase": "阶段1"},
    )

    assert out["message"] == {"content": "请写大纲", "target_agent_name": "写作专家"}
    assert len(calls) == 2
    system_prompt = calls[0][0].content
    message_system_prompt = calls[1][0].content
    selection_prompt = calls[0][1].content
    message_prompt = calls[1][1].content
    assert "主持人系统提示" in system_prompt
    assert "网文专用主持 Skill 正文" in system_prompt
    assert system_prompt.count("项目统一提示词") == 1
    assert system_prompt.count("场景共享任务契约") == 1
    assert system_prompt.index("项目统一提示词") < system_prompt.index("主持人系统提示")
    assert system_prompt.index("项目统一提示词") < system_prompt.index("场景共享任务契约")
    assert system_prompt.index("场景共享任务契约") < system_prompt.index("主持人系统提示")
    assert system_prompt.index("主持人系统提示") < system_prompt.index("网文专用主持 Skill 正文")
    assert system_prompt.index("网文专用主持 Skill 正文") < system_prompt.index("平台内部协议")
    assert "本次只执行主持人发言人选择与命中动作锁定阶段" in system_prompt
    assert "本次只执行主持人交接内容生成阶段" in message_system_prompt
    assert "书童四九平台主持人" not in system_prompt
    assert "只允许输出上述字段" not in selection_prompt
    assert "允许的 target_agent_name 值" in selection_prompt
    assert '["user", "end", "写作专家"]' in selection_prompt
    assert "下一位发言者和四列表命中动作已经固定" in message_prompt
    assert "写作专家" in message_prompt
    assert "调度写作专家完成大纲" in message_prompt
    assert "同时可供下一位发言者直接承接" in message_prompt
    assert '"next_action"' not in selection_prompt
    assert "scheduler_state" not in session_item


@pytest.mark.asyncio
async def test_host_decide_uses_structured_last_expert_turn_for_returning_expert(monkeypatch):
    calls = []

    class FakeSkillsLoader:
        def get_skill_full_content(self, skill_id):
            return ""

    class FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class FakeClient:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                return FakeResponse(
                    '{"current_phase":"阶段2","target_agent_name":"写作专家",'
                    '"selected_action":"调度写作专家继续下一阶段写作。",'
                    '"suggested_add_agent_names":[]}'
                )
            return FakeResponse('{"content":"继续写作","attachments":[],"artifacts":[]}')

    class FakeLlm:
        def get_client(self):
            return FakeClient()

    monkeypatch.setattr("app.agent.group_chat_host_runtime._request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr("app.agent.group_chat_host_runtime._llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)

    await _host_decide_by_agent(
        llm=FakeLlm(),
        host_agent={"name": "四九"},
        agent_profiles=[{"name": "写作专家", "description": "写作"}],
        discussion_goal="写网文",
        recent_messages="写作专家：第一阶段已完成。",
        last_speaker_agent_name="写作专家",
        extra_system_prompt="",
        group_session_id="group-return-expert",
        app_settings={},
        user_message="原始用户请求不应重复出现",
        host_scheduler_state={"current_phase": "阶段1"},
        last_expert_turn={
            "agent_name": "写作专家",
            "skill": "writer",
            "execution_status": "succeeded",
            "agent_turn": "respond",
            "skill_session": "release",
        },
        has_new_user_input=False,
    )

    assert len(calls) == 2
    selection_prompt = calls[0][1].content
    message_prompt = calls[1][1].content
    for prompt in (selection_prompt, message_prompt):
        assert "最近专家执行事实" in prompt
        assert "写作专家" in prompt
        assert "writer" in prompt
        assert "succeeded" in prompt
        assert "release" in prompt
        assert "本轮无新的用户输入" in prompt
        assert "原始用户请求不应重复出现" not in prompt
        assert "上一条主持任务" in prompt
        assert "不是一条新的用户任务" in prompt
        assert "不得单独据此再次调度相同动作" in prompt


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
                    '安排如下：\n```json\n{"current_phase":"阶段1",'
                    '"target_agent_name":"写作专家","suggested_add_agent_names":[]}\n```'
                )
            if len(calls) == 2:
                return FakeResponse(
                    '{"current_phase":"阶段1","target_agent_name":"写作专家",'
                    '"selected_action":"调度写作专家完成大纲。",'
                    '"suggested_add_agent_names":[]}'
                )
            return FakeResponse('{"content":"请写大纲","attachments":[],"artifacts":[]}')

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

    assert len(calls) == 3
    assert out["message"] == {"content": "请写大纲", "target_agent_name": "写作专家"}
    retry_prompt = calls[1][1].content
    assert "主持人发言人选择输出未通过平台 JSON 协议校验" in retry_prompt
    assert "suggested_add_agent_names" in retry_prompt
    assert "主持人长期提示词" in retry_prompt


@pytest.mark.asyncio
async def test_host_decide_logs_protocol_evidence_and_fallback_context(monkeypatch, caplog):
    class FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class FakeClient:
        def __init__(self):
            self.responses = iter(
                [
                    FakeResponse("first invalid host output"),
                    FakeResponse(
                        '{"current_phase":"阶段1","target_agent_name":"不存在的专家",'
                        '"selected_action":"调度不存在的专家处理任务。",'
                        '"suggested_add_agent_names":[]}'
                    ),
                ]
            )

        async def ainvoke(self, _messages):
            return next(self.responses)

    class FakeLlm:
        def get_client(self):
            return FakeClient()

    monkeypatch.setattr("app.agent.group_chat_host_runtime._request_skills_loader", lambda: None)
    monkeypatch.setattr("app.agent.group_chat_host_runtime._llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.WARNING):
        out = await _host_decide_by_agent(
            llm=FakeLlm(),
            host_agent={"name": "四九"},
            agent_profiles=[{"name": "写作专家", "description": "写作"}],
            discussion_goal="写文章",
            recent_messages="用户：写文章",
            last_speaker_agent_name=None,
            extra_system_prompt="",
            group_session_id="group-log-test",
            app_settings={},
            host_scheduler_state={"current_phase": "阶段1"},
            host_mode="scene",
        )

    assert out["message"] == {
        "content": HOST_PROTOCOL_ERROR_MESSAGE,
        "target_agent_name": "user",
    }
    messages = [record.getMessage() for record in caplog.records]
    initial = next(message for message in messages if "attempt=initial" in message)
    retry = next(message for message in messages if "attempt=retry" in message)
    fallback = next(message for message in messages if "host_scheduler_protocol_fallback" in message)
    assert "first invalid host output" in initial
    assert '"group_session_id":"group-log-test"' in retry
    assert '"allowed_agent_names":["写作专家"]' in retry
    assert "不存在的专家" in retry
    assert "session=group-log-test" in fallback
    assert "host=四九" in fallback
    assert "current_phase=阶段1" in fallback


@pytest.mark.asyncio
async def test_host_decide_separates_speaker_selection_from_message_generation(monkeypatch, caplog):
    calls = []

    class FakeResponse:
        def __init__(self, content: str):
            self.content = content

    class FakeClient:
        async def ainvoke(self, messages):
            calls.append(messages)
            if len(calls) == 1:
                return FakeResponse(
                    '{"current_phase":"文档合著","target_agent_name":"user",'
                    '"selected_action":"询问用户补充目标篇幅与侧重维度。",'
                    '"suggested_add_agent_names":[]}'
                )
            return FakeResponse(
                '{"content":"请文档合著专家等待用户补充目标篇幅与侧重维度。","attachments":[],"artifacts":[]}'
            )

    class FakeLlm:
        def get_client(self):
            return FakeClient()

    monkeypatch.setattr("app.agent.group_chat_host_runtime._request_skills_loader", lambda: None)
    monkeypatch.setattr("app.agent.group_chat_host_runtime._llm_credential_notice_for_agent", lambda *_args, **_kwargs: None)

    with caplog.at_level(logging.INFO):
        out = await _host_decide_by_agent(
            llm=FakeLlm(),
            host_agent={"name": "五九"},
            agent_profiles=[{"name": "文档合著专家", "description": "写作"}],
            discussion_goal="写沈腾演艺生涯介绍",
            recent_messages="文档合著专家：请用户补充目标篇幅。",
            last_speaker_agent_name="文档合著专家",
            extra_system_prompt="",
            group_session_id="group-two-stage",
            app_settings={},
            host_scheduler_state={"current_phase": "文档合著"},
        )

    assert len(calls) == 2
    assert "HostSpeakerSelectionPayload" in str(calls[0][-1].content)
    assert "HostMessagePayload" in str(calls[1][-1].content)
    assert out == {
        "current_phase": "文档合著",
        "message": {
            "content": "请文档合著专家等待用户补充目标篇幅与侧重维度。",
            "target_agent_name": "user",
        },
        "suggested_add_agent_names": None,
    }
    logs = [record.getMessage() for record in caplog.records]
    assert any(
        "host_speaker_selection session=group-two-stage" in message
        and "target_agent_name=user" in message
        for message in logs
    )
    assert any(
        "host_message_generation_complete session=group-two-stage" in message
        and "fixed_target_agent_name=user" in message
        for message in logs
    )
