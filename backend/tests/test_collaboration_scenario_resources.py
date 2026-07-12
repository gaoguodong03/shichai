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


def test_collaboration_web_and_image_experts_are_rewritten_for_current_state_contract():
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
        assert "schema_version" in body
        assert "expert_final_state.v2" in body
        assert '"agent_turn": "respond"' in body
        assert '"skill_session": "keep"' in body
        assert '"skill_session": "release"' in body
        assert '"handoff"' not in body
        assert '"resume"' not in body
        assert '"reason"' not in body
        assert '"instruction"' not in body
        assert "workflow_state" not in body
        assert "result_code" not in body


def test_collaboration_host_and_coauthor_use_message_based_vnext_contract():
    _, host_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-0909791c1d74" / "SKILL.md")
    _, coauthor_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-b604cfa284ca" / "SKILL.md")

    assert '"message"' in host_body
    assert '"target_agent_name"' in host_body
    assert '"next_speaker"' not in host_body
    assert '"next_action": "' not in host_body
    assert "expert_final_state.v2" in coauthor_body
    assert '"skill_session": "keep"' in coauthor_body
    assert '"skill_session": "release"' in coauthor_body
    for legacy in ('"handoff"', '"resume"', '"reason"', '"instruction"', "[[SKILL_SESSION_STATE]]"):
        assert legacy not in coauthor_body
