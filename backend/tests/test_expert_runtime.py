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

    def get_skill_full_content(self, skill_id):
        return self._contents.get(skill_id)


class FakeLlm:
    pass


def test_resolve_expert_skill_uses_locked_skill_first():
    loader = FakeSkillsLoader({"sk1": "body 1", "sk2": "body 2"})
    meta = {"skill_session_owner_id": "agent-a", "skill_session_skill_id": "sk2"}

    skill_id, content, debug = asyncio.run(
        resolve_expert_skill(
            dha={"agent_id": "agent-a", "skill_ids": ["sk1", "sk2"]},
            agent_id="agent-a",
            discussion_goal="goal",
            messages=[],
            meta_item=meta,
            app_settings={},
            round_user_text="",
            skills_loader=loader,
            llm_resolver=lambda _dha: FakeLlm(),
        )
    )

    assert skill_id == "sk2"
    assert content == "body 2"
    assert debug["strategy"] == "locked_skill_session"


def test_build_expert_turn_runtime_creates_agent_entry_bundle():
    loader = FakeSkillsLoader({"sk1": "技能正文"})
    calls = {}

    async def fake_tool_builder(dha, workspace_id, resolved_skill_id):
        calls["tool_builder"] = (dha["agent_id"], workspace_id, resolved_skill_id)
        return [SimpleNamespace(name="read_file", description="读文件")]

    def fake_agent_factory(llm, tools, skill_content, extra_system_prompt="", expert_self_awareness=""):
        calls["agent_factory"] = {
            "llm": llm,
            "tools": tools,
            "skill_content": skill_content,
            "extra_system_prompt": extra_system_prompt,
            "expert_self_awareness": expert_self_awareness,
        }
        return SimpleNamespace(kind="agent")

    runtime = asyncio.run(
        build_expert_turn_runtime(
            dha={
                "agent_id": "agent-a",
                "name": "专家A",
                "role": "写作专家",
                "system_prompt": "专家系统提示",
                "skill_ids": ["sk1"],
            },
            agent_id="agent-a",
            group_session_id="g1",
            discussion_goal="goal",
            messages=[],
            meta_item={},
            app_settings={},
            round_user_text="",
            extra_system_prompt="",
            skills_loader=loader,
            llm_resolver=lambda _dha: FakeLlm(),
            tool_builder=fake_tool_builder,
            agent_factory=fake_agent_factory,
        )
    )

    assert runtime.blocked is False
    assert runtime.skill_id == "sk1"
    assert runtime.skill_route_debug["strategy"] == "single_loaded_skill"
    assert calls["tool_builder"] == ("agent-a", "g1", "sk1")
    assert "专家系统提示" in runtime.skill_content
    assert "你的角色：写作专家" in runtime.skill_content
    assert "技能正文" in runtime.skill_content
    assert "Skill 会话状态" in runtime.skill_content
    assert calls["agent_factory"]["tools"] == runtime.tools


def test_build_expert_turn_runtime_blocks_when_skill_content_missing():
    loader = FakeSkillsLoader({})
    called = {"tool": False}

    async def fake_tool_builder(*_args, **_kwargs):
        called["tool"] = True
        return []

    runtime = asyncio.run(
        build_expert_turn_runtime(
            dha={"agent_id": "agent-a", "skill_ids": ["missing"]},
            agent_id="agent-a",
            group_session_id="g1",
            discussion_goal="goal",
            messages=[],
            meta_item={},
            app_settings={},
            round_user_text="",
            extra_system_prompt="",
            skills_loader=loader,
            llm_resolver=lambda _dha: FakeLlm(),
            tool_builder=fake_tool_builder,
            agent_factory=lambda *_args, **_kwargs: SimpleNamespace(kind="agent"),
        )
    )

    assert runtime.blocked is True
    assert runtime.skill_route_debug["blocking_error"] == "expert_skill_content_missing"
    assert called["tool"] is False
