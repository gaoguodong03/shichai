from __future__ import annotations

import json
from pathlib import Path

import yaml


USER_RESOURCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "users"
    / "user-d8f26bf88991429789b4905ba0ae8040"
    / "resources"
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_skill(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---", 2)
    return yaml.safe_load(frontmatter) or {}, body


def test_collaboration_scenario_has_three_current_protocol_experts():
    scenario = _read_json(USER_RESOURCE_ROOT / "scenarios" / "协作" / "scenario.json")

    assert scenario["agent_names"] == [
        "信息检索专家",
        "文档合著专家",
        "图片生成专家",
    ]
    assert set(scenario) >= {"name", "agent_names", "host"}
    legacy_host_key = "host_" + "config"
    assert legacy_host_key not in scenario

    host = scenario["host"]
    assert host["skill_directory"] == "skill-0909791c1d74"
    assert host["skill_name"] == "协作主持"

    host_fm, host_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-0909791c1d74" / "SKILL.md")
    assert host_fm["name"] == "协作主持"
    assert "信息检索专家" in host_body
    assert "文档合著专家" in host_body
    assert "图片生成专家" in host_body
    for legacy_field in ("speaker_task", "invite", "agent_id", "workflow_state", "result_code"):
        assert legacy_field not in host_body


def test_collaboration_web_and_image_skills_use_the_business_template():
    web_agent = _read_json(USER_RESOURCE_ROOT / "agents" / "信息检索专家" / "agent.json")
    image_agent = _read_json(USER_RESOURCE_ROOT / "agents" / "图片生成专家" / "agent.json")

    assert web_agent["skills"] == [{"name": "资料检索", "directory_name": "skill-collab-web-research"}]
    assert image_agent["skills"] == [{"name": "图片生成", "directory_name": "skill-collab-image-generation"}]

    web_fm, web_body = _read_skill(
        USER_RESOURCE_ROOT / "skills" / "skill-collab-web-research" / "SKILL.md"
    )
    image_fm, image_body = _read_skill(
        USER_RESOURCE_ROOT / "skills" / "skill-collab-image-generation" / "SKILL.md"
    )

    assert web_fm["name"] == "资料检索"
    assert web_fm["allowed-tools"]["mcp"] == ["Exa 搜索", "Linkup抓取网页"]
    assert image_fm["name"] == "图片生成"
    assert image_fm["allowed-tools"]["mcp"] == ["图片生成 MCP"]

    for body in (web_body, image_body):
        assert body.count("## 执行规则") == 1
        assert body.count("## 结束条件") == 1
        assert body.count("\n## ") == 2
        for platform_fragment in (
            "schema_version",
            "expert_final_state",
            '"next_action"',
            "agent_turn",
            "skill_session",
            '"handoff"',
            '"resume"',
            "workflow_state",
            "result_code",
        ):
            assert platform_fragment not in body


def test_collaboration_experts_follow_cross_scenario_prompt_template():
    agents = [
        _read_json(USER_RESOURCE_ROOT / "agents" / agent_name / "agent.json")
        for agent_name in ("信息检索专家", "文档合著专家", "图片生成专家")
    ]
    common_principles = (
        "只根据明确输入和本轮实际获得的结果作出结论，不虚构事实、产物或完成状态。",
        "信息不足以完成职责内任务时，只提出当前任务所需的最小补充问题。",
    )
    platform_owned_fragments = (
        "协同写作场景",
        "主持人",
        "Skill",
        "工作区",
        "最终状态",
        "next_action",
        "expert_final_state",
    )

    for agent in agents:
        description = str(agent.get("description") or "").strip()
        prompt = str(agent.get("system_prompt") or "").strip()

        assert description
        assert "交付" in description
        assert agent["name"] not in prompt
        for heading in ("职责边界：", "专业标准：", "判断原则："):
            assert heading in prompt
        for principle in common_principles:
            assert principle in prompt
        for fragment in platform_owned_fragments:
            assert fragment not in prompt


def test_collaboration_host_owns_dispatch_output_while_coauthor_uses_business_template():
    _, host_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-0909791c1d74" / "SKILL.md")
    _, coauthor_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-b604cfa284ca" / "SKILL.md")

    assert '"message"' in host_body
    assert '"target_agent_name"' in host_body
    assert '"next_speaker"' not in host_body
    assert '"next_action": "' not in host_body
    assert coauthor_body.count("## 执行规则") == 1
    assert coauthor_body.count("## 结束条件") == 1
    for platform_fragment in (
        "expert_final_state",
        "schema_version",
        '"next_action"',
        "agent_turn",
        "skill_session",
        '"handoff"',
        '"resume"',
        "[[SKILL_SESSION_STATE]]",
    ):
        assert platform_fragment not in coauthor_body
