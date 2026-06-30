from __future__ import annotations

import json

def test_deleted_skill_reference_keeps_display_name(monkeypatch, tmp_path):
    from app.core.settings_references import remove_skill_path_from_user_configs
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        agents_path = ctx.config_dir / "agents.json"
        preset_path = ctx.config_dir / "session_presets.json"
        agents_path.write_text(
            json.dumps([{"name": "专家", "skills": [{"name": "旧名", "directory_name": "skill-a"}]}], ensure_ascii=False),
            encoding="utf-8",
        )
        preset_path.write_text(
            json.dumps(
                [{"name": "场景", "agent_names": ["专家"], "host_config": {"leader_agent_name": "主持人", "skill_name": "旧名", "skill_directory": "skill-a"}}],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        remove_skill_path_from_user_configs("skill-a", "技能 A")

        experts = json.loads(agents_path.read_text(encoding="utf-8"))
        presets = json.loads(preset_path.read_text(encoding="utf-8"))
        assert experts[0]["skills"] == [{"name": "技能 A", "directory_name": "skill-a"}]
        assert presets[0]["host_config"]["skill_name"] == "技能 A"
        assert presets[0]["host_config"]["skill_directory"] == "skill-a"
    finally:
        reset_current_username(token)


def test_renamed_skill_path_updates_directory_only(monkeypatch, tmp_path):
    from app.core.settings_references import replace_skill_path_in_user_configs
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        agents_path = ctx.config_dir / "agents.json"
        agents_path.write_text(
            json.dumps([{"name": "专家", "skills": [{"name": "技能 A", "directory_name": "skill-a"}]}], ensure_ascii=False),
            encoding="utf-8",
        )

        replace_skill_path_in_user_configs("skill-a", "skill-b")

        experts = json.loads(agents_path.read_text(encoding="utf-8"))
        assert experts[0]["skills"] == [{"name": "技能 A", "directory_name": "skill-b"}]
    finally:
        reset_current_username(token)

