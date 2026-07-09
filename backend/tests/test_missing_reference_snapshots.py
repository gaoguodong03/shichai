from __future__ import annotations

import json

def test_deleted_skill_reference_keeps_display_name(monkeypatch, tmp_path):
    from app.api.agents import save_agent_instances
    from app.api.settings_presets import _mirror_session_presets_to_resources
    from app.core.settings_references import remove_skill_path_from_user_configs
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        save_agent_instances(
            [{"name": "专家", "skills": [{"name": "旧名", "directory_name": "skill-a"}]}]
        )
        _mirror_session_presets_to_resources(
            [{"name": "场景", "agent_names": ["专家"], "host": {"name": "主持人", "skill_name": "旧名", "skill_directory": "skill-a"}}]
        )

        remove_skill_path_from_user_configs("skill-a", "技能 A")

        expert = json.loads((ctx.agents_dir / "专家" / "agent.json").read_text(encoding="utf-8"))
        preset = json.loads((ctx.scenarios_dir / "场景" / "scenario.json").read_text(encoding="utf-8"))
        assert expert["skills"] == [{"name": "技能 A", "directory_name": "skill-a"}]
        assert preset["host"]["skill_name"] == "技能 A"
        assert preset["host"]["skill_directory"] == "skill-a"
    finally:
        reset_current_username(token)


def test_renamed_skill_path_updates_directory_only(monkeypatch, tmp_path):
    from app.api.agents import save_agent_instances
    from app.core.settings_references import replace_skill_path_in_user_configs
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
        save_agent_instances(
            [{"name": "专家", "skills": [{"name": "技能 A", "directory_name": "skill-a"}]}]
        )

        replace_skill_path_in_user_configs("skill-a", "skill-b")

        expert = json.loads((ctx.agents_dir / "专家" / "agent.json").read_text(encoding="utf-8"))
        assert expert["skills"] == [{"name": "技能 A", "directory_name": "skill-b"}]
    finally:
        reset_current_username(token)
