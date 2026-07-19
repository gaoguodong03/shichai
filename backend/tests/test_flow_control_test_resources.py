from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.agent.expert_completion_contract import SkillScriptStdoutPayload


USER_RESOURCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "users"
    / "user-d8f26bf88991429789b4905ba0ae8040"
    / "resources"
)

EXISTING_SKILL_DIRECTORIES = (
    "skill-collab-web-research",
    "skill-b604cfa284ca",
    "skill-collab-image-generation",
)
FLOW_SKILL_DIRECTORY = "flow-control-next-action-test"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_skill(directory_name: str) -> tuple[dict, str]:
    text = (
        USER_RESOURCE_ROOT / "skills" / directory_name / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, frontmatter, body = text.split("---", 2)
    return yaml.safe_load(frontmatter) or {}, body.strip()


def _run_flow_script(*, agent_turn: str, skill_session: str, stage: str) -> subprocess.CompletedProcess[str]:
    script = (
        USER_RESOURCE_ROOT
        / "skills"
        / FLOW_SKILL_DIRECTORY
        / "scripts"
        / "emit_next_action.py"
    )
    return subprocess.run(
        [
            sys.executable,
            str(script),
            "--agent-turn",
            agent_turn,
            "--skill-session",
            skill_session,
            "--stage",
            stage,
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_existing_skills_use_the_two_section_business_template():
    forbidden_fragments = (
        "你是",
        "主持人",
        "expert_final_state",
        '"next_action"',
        "agent_turn",
        "skill_session",
        "schema_version",
        '"handoff"',
        '"resume"',
        "最终输出合同",
    )

    for directory_name in EXISTING_SKILL_DIRECTORIES:
        frontmatter, body = _read_skill(directory_name)

        assert str(frontmatter.get("name") or "").strip()
        assert str(frontmatter.get("description") or "").strip()
        assert body.count("## 执行规则") == 1
        assert body.count("## 结束条件") == 1
        assert body.count("\n## ") == 2
        for fragment in forbidden_fragments:
            assert fragment not in body


def test_flow_control_expert_uses_the_cross_scenario_expert_template():
    agent = _read_json(USER_RESOURCE_ROOT / "agents" / "流程控制测试专家" / "agent.json")
    prompt = str(agent.get("system_prompt") or "")

    assert agent["name"] == "流程控制测试专家"
    assert "交付" in agent["description"]
    assert agent["skills"] == [
        {"name": "流程控制测试", "directory_name": FLOW_SKILL_DIRECTORY}
    ]
    for heading in ("职责边界：", "专业标准：", "判断原则："):
        assert heading in prompt
    for principle in (
        "只根据明确输入和本轮实际获得的结果作出结论，不虚构事实、产物或完成状态。",
        "信息不足以完成职责内任务时，只提出当前任务所需的最小补充问题。",
    ):
        assert principle in prompt
    for platform_owned_fragment in (
        agent["name"],
        "主持人",
        "工作区",
        "最终状态",
        "next_action",
        "agent_turn",
        "skill_session",
        "expert_final_state",
    ):
        assert platform_owned_fragment not in prompt


def test_flow_control_skill_and_manifest_define_only_the_test_business_inputs():
    frontmatter, body = _read_skill(FLOW_SKILL_DIRECTORY)
    manifest = _read_json(
        USER_RESOURCE_ROOT
        / "skills"
        / FLOW_SKILL_DIRECTORY
        / "scripts"
        / "manifest.json"
    )

    assert frontmatter["name"] == "流程控制测试"
    assert frontmatter["allowed-tools"] == {"http_api": [], "mcp": [], "python": []}
    assert body.count("## 执行规则") == 1
    assert body.count("## 结束条件") == 1
    assert body.count("\n## ") == 2
    assert "expert_final_state" not in body
    assert "schema_version" not in body
    assert '"next_action"' not in body
    assert set(manifest) == {"entry", "description", "args"}
    assert manifest["entry"] == "emit_next_action.py"
    assert [argument["name"] for argument in manifest["args"]] == [
        "agent_turn",
        "skill_session",
        "stage",
    ]
    assert all(argument["required"] is True for argument in manifest["args"])


@pytest.mark.parametrize(
    ("agent_turn", "skill_session"),
    (
        ("continue", "keep"),
        ("continue", "release"),
        ("respond", "keep"),
        ("respond", "release"),
    ),
)
def test_flow_control_script_emits_each_requested_trigger_combination(
    agent_turn: str,
    skill_session: str,
):
    completed = _run_flow_script(
        agent_turn=agent_turn,
        skill_session=skill_session,
        stage="trigger",
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    SkillScriptStdoutPayload.model_validate(payload)
    assert set(payload) == {"execution_status", "message", "next_action"}
    assert payload["execution_status"] == "succeeded"
    assert payload["next_action"] == {
        "agent_turn": agent_turn,
        "skill_session": skill_session,
    }
    assert payload["message"]["attachments"] == []
    assert payload["message"]["artifacts"] == []
    assert f"agent_turn={agent_turn}" in payload["message"]["content"]
    assert f"skill_session={skill_session}" in payload["message"]["content"]
    assert ("FLOW_CONTROL_TEST_COMPLETE" in payload["message"]["content"]) is (
        agent_turn == "continue"
    )


@pytest.mark.parametrize("skill_session", ("keep", "release"))
def test_continue_combinations_finish_with_respond_and_the_original_skill_policy(
    skill_session: str,
):
    completed = _run_flow_script(
        agent_turn="continue",
        skill_session=skill_session,
        stage="complete",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    SkillScriptStdoutPayload.model_validate(payload)
    assert payload["execution_status"] == "succeeded"
    assert payload["next_action"] == {
        "agent_turn": "respond",
        "skill_session": skill_session,
    }
    assert "首次组合 agent_turn=continue" in payload["message"]["content"]
    assert f"skill_session={skill_session}" in payload["message"]["content"]


def test_complete_stage_rejects_a_non_continue_original_turn():
    completed = _run_flow_script(
        agent_turn="respond",
        skill_session="keep",
        stage="complete",
    )

    assert completed.returncode != 0
    assert completed.stdout == ""
