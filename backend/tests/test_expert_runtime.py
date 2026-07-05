"""Expert runtime entrypoint tests."""

import asyncio
from types import SimpleNamespace

from app.agent.expert_runtime import build_expert_turn_runtime, resolve_expert_skill


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


def test_resolve_expert_skill_uses_locked_skill_first():
    loader = FakeSkillsLoader({"sk1": "body 1", "sk2": "body 2"})
    meta = {"skill_session_owner_name": "专家A", "skill_session_skill": "sk2"}

    skill, content, debug = asyncio.run(
        resolve_expert_skill(
            agent_profile={
                "name": "专家A",
                "skills": [{"name": "Skill sk1", "directory_name": "sk1"}, {"name": "Skill sk2", "directory_name": "sk2"}],
            },
            agent_name="专家A",
            discussion_goal="goal",
            messages=[],
            session_item=meta,
            app_settings={},
            round_user_text="",
            skills_loader=loader,
            llm_resolver=lambda _agent_profile: FakeLlm(),
        )
    )

    assert skill == "sk2"
    assert content == "body 2"
    assert debug["strategy"] == "locked_skill_session"


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
    assert runtime.skill_route_debug["strategy"] == "single_loaded_skill"
    assert calls["tool_builder"] == ("专家A", "g1", "sk1")
    assert "专家系统提示" in runtime.skill_content
    assert "你的职责：写作专家" in runtime.skill_content
    assert "技能正文" in runtime.skill_content
    assert "Skill 会话状态" in runtime.skill_content
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
    assert runtime.skill_route_debug["blocking_error"] == "expert_skill_content_missing"
    assert called["tool"] is False
