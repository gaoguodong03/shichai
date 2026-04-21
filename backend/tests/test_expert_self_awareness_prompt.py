from app.agent.expert_self_awareness import build_expert_self_awareness_block
from app.agent.graph import create_skill_execution_agent


class _FakeSkill:
    def __init__(self, name: str, description: str, enabled: bool = True):
        self.name = name
        self.description = description
        self.metadata = {"enabled": enabled}


class _FakeSkillsLoader:
    def __init__(self, skills: dict):
        self.skills = skills


def test_build_expert_self_awareness_block_with_multi_skills():
    loader = _FakeSkillsLoader(
        {
            "skill-a": _FakeSkill("技能A", "负责A能力"),
            "skill-b": _FakeSkill("技能B", "负责B能力"),
        }
    )
    dha = {"skill_ids": ["skill-a", "skill-b"]}

    block = build_expert_self_awareness_block(dha, loader)

    assert "## 你当前绑定的 Skill" in block
    assert "技能A" in block and "负责A能力" in block
    assert "技能B" in block and "负责B能力" in block


def test_build_expert_self_awareness_block_fallback_when_description_missing():
    loader = _FakeSkillsLoader({"skill-a": _FakeSkill("技能A", "")})
    dha = {"skill_ids": ["skill-a"]}

    block = build_expert_self_awareness_block(dha, loader)

    assert "技能A" in block
    assert "无描述，仅按技能名称推断能力边界。" in block


def test_create_skill_execution_agent_injects_self_awareness_after_skill_content():
    skill_content = "你是测试专家。"
    self_awareness = "## 你当前绑定的 Skill\n- **技能A**（标识：`skill-a`）\n  负责A能力"

    agent = create_skill_execution_agent(
        llm=object(),
        tools=[],
        skill_full_content=skill_content,
        extra_system_prompt="额外系统提示",
        expert_self_awareness=self_awareness,
    )
    prompt = agent.system_prompt

    assert "额外系统提示" in prompt
    assert skill_content in prompt
    assert self_awareness in prompt
    assert prompt.index(skill_content) < prompt.index(self_awareness)
