from __future__ import annotations

import json

import yaml


def test_deleted_agent_reference_keeps_display_name(monkeypatch, tmp_path):
    from app.core.settings_references import mark_agent_id_missing_in_session_presets
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        path = ctx.config_dir / "session_presets.json"
        path.write_text(
            json.dumps([{"id": "scene-1", "name": "场景", "agent_ids": ["agent-a"]}], ensure_ascii=False),
            encoding="utf-8",
        )

        mark_agent_id_missing_in_session_presets("agent-a", "专家 A")

        rows = json.loads(path.read_text(encoding="utf-8"))
        assert rows[0]["agent_ids"] == ["agent-a"]
        assert rows[0]["agent_refs"] == [{"id": "agent-a", "name": "专家 A"}]
    finally:
        reset_current_username(token)


def test_deleted_skill_reference_keeps_display_name(monkeypatch, tmp_path):
    from app.core.settings_references import remove_skill_id_from_user_configs
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        agents_path = ctx.config_dir / "dha_instances.json"
        preset_path = ctx.config_dir / "session_presets.json"
        agents_path.write_text(
            json.dumps([{"agent_id": "agent-a", "name": "专家", "skill_ids": ["skill-a"]}], ensure_ascii=False),
            encoding="utf-8",
        )
        preset_path.write_text(
            json.dumps(
                [{"id": "scene-1", "name": "场景", "agent_ids": ["agent-a"], "host_config": {"skill_ids": ["skill-a"]}}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        remove_skill_id_from_user_configs("skill-a", "技能 A")

        experts = json.loads(agents_path.read_text(encoding="utf-8"))
        presets = json.loads(preset_path.read_text(encoding="utf-8"))
        assert experts[0]["skill_ids"] == ["skill-a"]
        assert experts[0]["skill_refs"] == [{"id": "skill-a", "name": "技能 A"}]
        assert presets[0]["host_config"]["skill_ids"] == ["skill-a"]
        assert presets[0]["host_config"]["skill_refs"] == [{"id": "skill-a", "name": "技能 A"}]
    finally:
        reset_current_username(token)


def test_deleted_mcp_reference_keeps_display_name_in_skill(monkeypatch, tmp_path):
    from app.api.settings_mcp import _mark_mcp_id_missing_in_skills
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        skill_dir = ctx.skills_dir / "skill-a"
        skill_dir.mkdir(parents=True)
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text(
            "---\nname: 技能 A\nallowed-tools:\n  mcp:\n    - mcp-a\n  python: ''\n---\nbody\n",
            encoding="utf-8",
        )

        _mark_mcp_id_missing_in_skills("mcp-a", "工具 A")

        frontmatter = yaml.safe_load(skill_file.read_text(encoding="utf-8").split("---", 2)[1])
        assert frontmatter["allowed-tools"]["mcp"] == ["mcp-a"]
        assert frontmatter["reference-labels"]["mcp"] == [{"id": "mcp-a", "name": "工具 A"}]
    finally:
        reset_current_username(token)
