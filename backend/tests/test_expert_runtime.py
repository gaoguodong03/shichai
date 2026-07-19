"""Expert runtime entrypoint tests."""

import asyncio
from types import SimpleNamespace

from app.agent.messages import AIMessage
from app.agent.expert_runtime import build_expert_turn_runtime, resolve_expert_skill
from app.agent.group_chat_expert_resolution import _last_user_message_text


class FakeSkillsLoader:
    def __init__(self, contents):
        self._contents = dict(contents)
        self.skills = {
            sid: SimpleNamespace(name=f"Skill {sid}", description=f"desc {sid}", metadata={})
            for sid in self._contents
        }

    def get_skill_full_content(self, directory_name):
        return self._contents.get(directory_name)


class FakeLlm:
    pass


class CapturingLlm:
    def __init__(self, content):
        self.content = content
        self.messages = None

    def get_client(self):
        return self

    async def ainvoke(self, messages):
        self.messages = messages
        return AIMessage(content=self.content)


class SequencedCapturingLlm:
    def __init__(self, *contents):
        self.contents = list(contents)
        self.calls = []

    def get_client(self):
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.contents.pop(0))


def test_resolve_expert_skill_uses_locked_skill_first():
    loader = FakeSkillsLoader({"sk1": "body 1", "sk2": "body 2"})
    orchestration_state = {
        "skill_sessions": {"专家A": {"skill": "sk2"}}
    }

    skill, content, debug = asyncio.run(
        resolve_expert_skill(
            agent_profile={
                "name": "专家A",
                "skills": [{"name": "Skill sk1", "directory_name": "sk1"}, {"name": "Skill sk2", "directory_name": "sk2"}],
            },
            agent_name="专家A",
            discussion_goal="goal",
            messages=[],
            session_item={"scenario_prompt": "场景共享任务契约"},
            orchestration_state=orchestration_state,
            app_settings={},
            round_user_text="",
            skills_loader=loader,
            llm_resolver=lambda _agent_profile: FakeLlm(),
        )
    )

    assert skill == "sk2"
    assert content == "body 2"
    assert debug["strategy"] == "locked_skill_session"


def test_resolve_expert_skill_uses_expert_profile_in_multi_skill_prompt():
    loader = FakeSkillsLoader({"writer": "写作正文", "research": "检索正文"})
    llm = CapturingLlm('{"selected_skill":"research"}')

    skill, content, debug = asyncio.run(
        resolve_expert_skill(
            agent_profile={
                "name": "专家A",
                "description": "负责资料检索和事实核验",
                "system_prompt": "你必须优先核验来源可靠性。",
                "skills": [
                    {"name": "写作", "directory_name": "writer"},
                    {"name": "检索", "directory_name": "research"},
                ],
            },
            agent_name="专家A",
            discussion_goal="整理竞品资料",
            messages=[],
            session_item={"scenario_prompt": "场景共享任务契约"},
            orchestration_state={},
            app_settings={
                "default_llm": "qwen3-max",
                "system_prompt": "项目统一提示词",
            },
            round_user_text="先查资料",
            skills_loader=loader,
            llm_resolver=lambda _agent_profile: llm,
        )
    )

    assert skill == "research"
    assert content == "检索正文"
    assert debug["strategy"] == "expert_llm_pick"
    assert debug["selected_skill"] == "research"
    assert llm.messages is not None
    assert "项目统一提示词" in llm.messages[0].content
    assert llm.messages[0].content.count("项目统一提示词") == 1
    assert "场景共享任务契约" in llm.messages[0].content
    assert llm.messages[0].content.count("场景共享任务契约") == 1
    assert "负责资料检索和事实核验" in llm.messages[0].content
    assert "你必须优先核验来源可靠性。" in llm.messages[0].content
    assert llm.messages[0].content.index("项目统一提示词") < llm.messages[0].content.index("专家名称")
    assert llm.messages[0].content.index("项目统一提示词") < llm.messages[0].content.index("场景共享任务契约")
    assert llm.messages[0].content.index("场景共享任务契约") < llm.messages[0].content.index("专家名称")


def test_resolve_expert_skill_retries_protocol_output_before_blocking():
    loader = FakeSkillsLoader({"writer": "写作正文", "research": "检索正文"})
    llm = SequencedCapturingLlm(
        '我选择：{"selected_skill":"research"}',
        '{"selected_skill":"research"}',
    )

    skill, content, debug = asyncio.run(
        resolve_expert_skill(
            agent_profile={
                "name": "专家A",
                "description": "负责资料检索和事实核验",
                "skills": [
                    {"name": "写作", "directory_name": "writer"},
                    {"name": "检索", "directory_name": "research"},
                ],
            },
            agent_name="专家A",
            discussion_goal="整理竞品资料",
            messages=[],
            session_item={},
            orchestration_state={},
            app_settings={},
            round_user_text="先查资料",
            skills_loader=loader,
            llm_resolver=lambda _agent_profile: llm,
        )
    )

    assert skill == "research"
    assert content == "检索正文"
    assert debug["strategy"] == "expert_llm_pick"
    assert len(llm.calls) == 2
    assert "专家 Skill 选择输出未通过平台 JSON 协议校验" in llm.calls[1][1].content


def test_build_expert_turn_runtime_creates_agent_entry_bundle():
    loader = FakeSkillsLoader({"sk1": "技能正文"})
    calls = {}

    async def fake_tool_builder(agent_profile, workspace_id, resolved_skill):
        calls["tool_builder"] = (agent_profile["name"], workspace_id, resolved_skill)
        return [SimpleNamespace(name="read_workspace_file", description="读文件")]

    def fake_agent_factory(
        llm,
        tools,
        skill_content,
        extra_system_prompt="",
        expert_self_awareness="",
        synthesize_after_read_file_paths=(),
    ):
        calls["agent_factory"] = {
            "llm": llm,
            "tools": tools,
            "skill_content": skill_content,
            "extra_system_prompt": extra_system_prompt,
            "expert_self_awareness": expert_self_awareness,
            "synthesize_after_read_file_paths": synthesize_after_read_file_paths,
        }
        return SimpleNamespace(kind="agent")

    runtime = asyncio.run(
        build_expert_turn_runtime(
            agent_profile={
                "name": "专家A",
                "description": "写作专家",
                "system_prompt": "专家系统提示",
                "skills": [{"name": "Skill sk1", "directory_name": "sk1"}],
            },
            agent_name="专家A",
            group_session_id="g1",
            discussion_goal="goal",
            messages=[],
            session_item={},
            app_settings={},
            round_user_text="",
            extra_system_prompt="",
            skills_loader=loader,
            llm_resolver=lambda _agent_profile: FakeLlm(),
            tool_builder=fake_tool_builder,
            agent_factory=fake_agent_factory,
        )
    )

    assert runtime.blocked is False
    assert runtime.skill == "sk1"
    assert runtime.skill_route_diagnostics["strategy"] == "single_loaded_skill"
    assert calls["tool_builder"] == ("专家A", "g1", "sk1")
    assert "专家系统提示" in runtime.skill_content
    assert "你的职责：写作专家" in runtime.skill_content
    assert "技能正文" in runtime.skill_content
    assert "Skill 会话状态" not in runtime.skill_content
    assert calls["agent_factory"]["tools"] == runtime.tools
    assert calls["agent_factory"]["synthesize_after_read_file_paths"] == ()


def test_build_expert_turn_runtime_blocks_when_skill_content_missing():
    loader = FakeSkillsLoader({})
    called = {"tool": False}

    async def fake_tool_builder(*_args, **_kwargs):
        called["tool"] = True
        return []

    runtime = asyncio.run(
        build_expert_turn_runtime(
            agent_profile={"name": "专家A", "skills": [{"name": "Missing", "directory_name": "missing"}]},
            agent_name="专家A",
            group_session_id="g1",
            discussion_goal="goal",
            messages=[],
            session_item={},
            app_settings={},
            round_user_text="",
            extra_system_prompt="",
            skills_loader=loader,
            llm_resolver=lambda _agent_profile: FakeLlm(),
            tool_builder=fake_tool_builder,
            agent_factory=lambda *_args, **_kwargs: SimpleNamespace(kind="agent"),
        )
    )

    assert runtime.blocked is True
    assert runtime.skill_route_diagnostics["blocking_error"] == "expert_skill_content_missing"
    assert called["tool"] is False


def test_last_user_message_text_ignores_legacy_top_level_content():
    assert (
        _last_user_message_text(
            [
                {
                    "speaker": {"type": "user"},
                    "message": {"content": "标准用户正文"},
                    "content": "旧顶层用户正文",
                }
            ]
        )
        == "标准用户正文"
    )
    assert _last_user_message_text([{"speaker": {"type": "user"}, "content": "旧顶层用户正文"}]) == ""
