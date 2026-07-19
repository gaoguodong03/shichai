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


def _read_host_flow_rows(body: str) -> list[dict[str, str]]:
    table_lines = [line for line in body.splitlines() if line.startswith("|")]
    assert len(table_lines) >= 3
    headers = [cell.strip() for cell in table_lines[0].strip("|").split("|")]
    assert headers == ["当前阶段", "如果", "主持人就", "然后进入"]
    assert all(set(cell.strip()) <= {"-", ":"} for cell in table_lines[1].strip("|").split("|"))
    return [
        dict(zip(headers, [cell.strip() for cell in line.strip("|").split("|")], strict=True))
        for line in table_lines[2:]
    ]


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

    scenario_prompt = str(scenario.get("system_prompt") or "").strip()
    assert "场景目标：" in scenario_prompt
    assert "共同要求：" in scenario_prompt
    assert "完成标准：" in scenario_prompt
    assert '"current_phase"' not in scenario_prompt

    host = scenario["host"]
    assert host["skill_directory"] == "skill-0909791c1d74"
    assert host["skill_name"] == "协作主持"

    host_prompt = str(host.get("system_prompt") or "").strip()
    assert "只负责调度" in host_prompt
    assert "阶段表使用规则：" in host_prompt
    assert '"current_phase"' in host_prompt
    assert '"suggested_add_agent_names"' in host_prompt
    for agent_name in scenario["agent_names"]:
        assert agent_name not in host_prompt

    host_fm, host_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-0909791c1d74" / "SKILL.md")
    assert host_fm["name"] == "协作主持"
    assert host_body.count("| 当前阶段 | 如果 | 主持人就 | 然后进入 |") == 1
    assert "| （无） |" in host_body
    assert "\n## " not in host_body
    assert "信息检索专家" in host_body
    assert "文档合著专家" in host_body
    assert "图片生成专家" in host_body
    assert (
        "| 资料检索 | 资料检索已经完成，用户剩余目标包括图片或图文装配且不包括文档写作 | "
        "调度`图片生成专家`"
    ) in host_body

    flow_rows = _read_host_flow_rows(host_body)
    rows_by_phase = {
        phase: [row for row in flow_rows if row["当前阶段"] == phase]
        for phase in {row["当前阶段"] for row in flow_rows}
    }
    assert set(rows_by_phase) == {"（无）", "资料检索", "文档合著", "图片生成"}
    assert {row["然后进入"] for row in flow_rows} <= {
        "（无）",
        "资料检索",
        "文档合著",
        "图片生成",
        "end",
    }
    expected_routing = {
        "（无）": (
            ("询问用户：", "（无）"),
            ("调度`信息检索专家`", "资料检索"),
            ("调度`文档合著专家`", "文档合著"),
            ("调度`图片生成专家`", "图片生成"),
        ),
        "资料检索": (
            ("调度`信息检索专家`", "资料检索"),
            ("询问用户：", "资料检索"),
            ("调度`文档合著专家`", "文档合著"),
            ("调度`图片生成专家`", "图片生成"),
            ("告知用户协作结束：", "end"),
        ),
        "文档合著": (
            ("询问用户：", "文档合著"),
            ("调度`文档合著专家`", "文档合著"),
            ("调度`图片生成专家`", "图片生成"),
            ("告知用户协作结束：", "end"),
        ),
        "图片生成": (
            ("询问用户：", "图片生成"),
            ("调度`图片生成专家`", "图片生成"),
            ("告知用户协作结束：", "end"),
        ),
    }
    for phase, expected_rows in expected_routing.items():
        actual_rows = rows_by_phase[phase]
        assert len(actual_rows) == len(expected_rows)
        for row, (action_prefix, target_phase) in zip(actual_rows, expected_rows, strict=True):
            assert row["主持人就"].startswith(action_prefix)
            assert row["然后进入"] == target_phase
    for platform_field in (
        '"current_phase"',
        '"message"',
        '"suggested_add_agent_names"',
        "speaker_task",
        "invite",
        "agent_id",
        "workflow_state",
        "result_code",
    ):
        assert platform_field not in host_body


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
        assert "- 等待用户：" in body
        assert "- 完成：" in body
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
    specialty_fragments = (
        ("公开资料搜索", "关键事实和结论必须对应到明确来源"),
        ("结构化文档", "文档结构、内容层次和表达方式"),
        ("配图方案", "生成或装配的视觉内容"),
    )

    for agent, specialty in zip(agents, specialty_fragments, strict=True):
        description = str(agent.get("description") or "").strip()
        prompt = str(agent.get("system_prompt") or "").strip()

        assert description
        assert "交付" in description
        assert agent["name"] not in prompt
        for heading in ("职责边界：", "专业标准：", "执行要求：", "输出：", "流程控制："):
            assert heading in prompt
        for fragment in specialty:
            assert fragment in prompt
        for fragment in (
            '"execution_status"',
            '"next_action"',
            "continue + keep",
            "continue + release",
            "respond + keep",
            "respond + release",
        ):
            assert fragment in prompt
        assert "execution_status 只允许 succeeded、blocked 或 failed" in prompt
        assert "agent_turn 只允许 continue 或 respond" in prompt
        assert "skill_session 只允许 keep 或 release" in prompt
        assert "不选择下一位专家" in prompt
        assert "不得填写 target_agent_name" in prompt
        assert "协同写作场景" not in prompt

        output_start = prompt.index("{", prompt.index("输出："))
        output_end = prompt.index("\n- execution_status", output_start)
        output_example = json.loads(prompt[output_start:output_end])
        assert set(output_example) == {"execution_status", "message", "next_action"}
        assert set(output_example["message"]) == {"content", "attachments", "artifacts"}
        assert set(output_example["next_action"]) == {"agent_turn", "skill_session"}


def test_collaboration_host_owns_dispatch_output_while_coauthor_uses_business_template():
    scenario = _read_json(USER_RESOURCE_ROOT / "scenarios" / "协作" / "scenario.json")
    host_prompt = str(scenario["host"].get("system_prompt") or "").strip()
    _, host_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-0909791c1d74" / "SKILL.md")
    _, coauthor_body = _read_skill(USER_RESOURCE_ROOT / "skills" / "skill-b604cfa284ca" / "SKILL.md")

    assert '"message"' in host_prompt
    assert '"target_agent_name"' in host_prompt
    assert '"message"' not in host_body
    assert '"target_agent_name"' not in host_body
    assert '"next_speaker"' not in host_body
    assert '"next_action": "' not in host_body
    assert coauthor_body.count("## 执行规则") == 1
    assert coauthor_body.count("## 结束条件") == 1
    for business_gate in (
        "大纲未确认前不写正文",
        "当前章节未确认前不进入下一节",
        "所有章节确认后",
        "最终完整文档已经保存",
        "- 等待用户：",
        "- 完成：",
    ):
        assert business_gate in coauthor_body
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
