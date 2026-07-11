from app.agent.expert_self_awareness import build_expert_self_awareness_block
from app.agent.skill_agent_runtime import create_skill_execution_agent
from app.agent.tool_spec import ToolSpec


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
    agent_profile = {
        "skills": [
            {"name": "技能A", "directory_name": "skill-a"},
            {"name": "技能B", "directory_name": "skill-b"},
        ]
    }

    block = build_expert_self_awareness_block(agent_profile, loader)

    assert "## 你当前绑定的 Skill" in block
    assert "技能A" in block and "负责A能力" in block
    assert "技能B" in block and "负责B能力" in block


def test_build_expert_self_awareness_block_fallback_when_description_missing():
    loader = _FakeSkillsLoader({"skill-a": _FakeSkill("技能A", "")})
    agent_profile = {"skills": [{"name": "技能A", "directory_name": "skill-a"}]}

    block = build_expert_self_awareness_block(agent_profile, loader)

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


def test_create_skill_execution_agent_omits_legacy_prompt_scaffolding():
    skill_content = "按技能正文执行。"

    agent = create_skill_execution_agent(
        llm=object(),
        tools=[ToolSpec(name="read_workspace_file", description="读文件")],
        skill_full_content=skill_content,
        extra_system_prompt="额外系统提示",
    )
    prompt = agent.system_prompt

    assert "你是一个有用的 AI 助手，正在按以下技能说明执行用户请求。" not in prompt
    assert '{"action":"tool_call"' not in prompt
    assert "额外系统提示" in prompt
    assert skill_content in prompt
    assert "当你需要使用工具时，选择当前运行环境提供的可用工具并填写参数" in prompt
    assert "- read_workspace_file: 读文件" in prompt


def test_create_skill_execution_agent_injects_current_workspace_file_timestamp(monkeypatch):
    import app.agent.skill_execution_prompt_rules as prompt_rules

    monkeypatch.setattr(prompt_rules, "_current_workspace_file_timestamp", lambda: "2026070422145700")

    agent = create_skill_execution_agent(
        llm=object(),
        tools=[ToolSpec(name="write_workspace_file", description="写文件")],
        skill_full_content="按技能正文执行。",
    )
    prompt = agent.system_prompt

    assert "当前文件时间戳：`2026070422145700`" in prompt
    assert "新建工作区文件时直接把这个时间戳写入文件名" in prompt
