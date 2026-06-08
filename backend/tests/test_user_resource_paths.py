def test_user_context_uses_user_id_not_email(monkeypatch, tmp_path):
    from app.core.user_context import build_user_context

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))

    ctx = build_user_context(user_id="user-abc123", username="alice@example.com")

    assert ctx.user_id == "user-abc123"
    assert ctx.username == "alice@example.com"
    assert ctx.base_dir == (tmp_path / "users" / "user-abc123").resolve()
    assert ctx.resources_dir == ctx.base_dir / "resources"
    assert ctx.sessions_dir == ctx.base_dir / "sessions"
    assert ctx.vault_dir == ctx.base_dir / "vault"
    assert not (tmp_path / "users" / "alice@example.com").exists()


def test_atomic_write_json_preserves_existing_file_on_serializer_error(tmp_path):
    from app.core.atomic_json import atomic_write_json, read_json_or_default

    target = tmp_path / "resource.json"
    atomic_write_json(target, {"version": 1, "name": "old"})

    class NotJson:
        pass

    try:
        atomic_write_json(target, {"bad": NotJson()})
    except TypeError:
        pass

    assert read_json_or_default(target, {}) == {"version": 1, "name": "old"}
    assert not list(tmp_path.glob("resource.json.*.tmp"))


def test_resource_path_helpers_point_to_resources(monkeypatch, tmp_path):
    from app.core.user_context import reset_current_user_identity, set_current_user_identity
    from app.core.user_settings_paths import (
        agents_resources_dir,
        models_resources_dir,
        scenarios_resources_dir,
        skills_dir_path,
        tools_resources_dir,
        vault_secrets_path,
    )

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-paths", username="paths@example.com")
    try:
        root = (tmp_path / "users" / "user-paths").resolve()
        assert scenarios_resources_dir() == root / "resources" / "scenarios"
        assert agents_resources_dir() == root / "resources" / "agents"
        assert skills_dir_path() == root / "resources" / "skills"
        assert tools_resources_dir() == root / "resources" / "tools"
        assert models_resources_dir() == root / "resources" / "models"
        assert vault_secrets_path() == root / "vault" / "secrets.enc.json"
    finally:
        reset_current_user_identity(token)


def test_api_secret_values_use_current_user_context_dir(monkeypatch, tmp_path):
    import json

    from app.api.settings_secrets import load_api_secret_values
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    user_config = tmp_path / "users" / "user-secret-owner" / "config"
    user_config.mkdir(parents=True)
    (user_config / "api_secrets.json").write_text(
        json.dumps({"items": {"jeniya": {"label": "Jeniya", "api_key": "from-user-id-dir"}}}),
        encoding="utf-8",
    )

    token = set_current_user_identity(user_id="user-secret-owner", username="owner@example.com")
    try:
        assert load_api_secret_values() == {"jeniya": "from-user-id-dir"}
    finally:
        reset_current_user_identity(token)


def test_save_agent_instances_mirrors_agents_resource_files(monkeypatch, tmp_path):
    import json

    from app.api.agents import save_agent_instances
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-save", username="save@example.com")
    try:
        save_agent_instances(
            [
                {
                    "agent_id": "agent-resource-flow",
                    "name": "资源目录专家",
                    "role": "验证专家资源落盘",
                    "skill_ids": [],
                    "mcp_server_ids": [],
                }
            ]
        )

        user_root = tmp_path / "users" / "user-resource-save"
        agent_file = user_root / "resources" / "agents" / "agent-resource-flow" / "agent.json"
        assert agent_file.is_file()
        agent_data = json.loads(agent_file.read_text(encoding="utf-8"))
        assert agent_data["id"] == "agent-resource-flow"
        assert agent_data["name"] == "资源目录专家"

        save_agent_instances([])
        assert not agent_file.exists()
    finally:
        reset_current_user_identity(token)


def test_update_session_presets_mirrors_scenarios_resource_files(monkeypatch, tmp_path):
    import asyncio
    import json

    from app.api.settings_presets import SessionPresetItem, SessionPresetsBody, update_session_presets
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-save", username="save@example.com")
    try:
        body = SessionPresetsBody(
            presets=[
                SessionPresetItem(
                    id="scenario-resource-flow",
                    name="资源目录场景",
                    agent_ids=["agent-resource-flow"],
                    description="验证场景资源落盘",
                    leader_agent_id="agent-resource-flow",
                )
            ]
        )
        asyncio.run(update_session_presets(body))

        user_root = tmp_path / "users" / "user-resource-save"
        scenario_file = user_root / "resources" / "scenarios" / "scenario-resource-flow" / "scenario.json"
        assert scenario_file.is_file()
        assert json.loads(scenario_file.read_text(encoding="utf-8"))["name"] == "资源目录场景"

        asyncio.run(update_session_presets(SessionPresetsBody(presets=[])))
        assert not scenario_file.exists()
    finally:
        reset_current_user_identity(token)


def test_get_session_presets_recovers_from_scenario_resource_files(monkeypatch, tmp_path):
    import asyncio
    import json

    from app.api.settings_presets import get_session_presets
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-recover", username="recover@example.com")
    try:
        user_root = tmp_path / "users" / "user-resource-recover"
        scenario_file = user_root / "resources" / "scenarios" / "online-scene" / "scenario.json"
        scenario_file.parent.mkdir(parents=True)
        scenario_file.write_text(
            json.dumps(
                {
                    "id": "online-scene",
                    "name": "线上导入场景",
                    "agent_ids": ["online-expert"],
                    "description": "只剩资源目录镜像时也应能刷新出来",
                    "leader_agent_id": "online-expert",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        preset_path = user_root / "config" / "session_presets.json"
        preset_path.parent.mkdir(parents=True)
        preset_path.write_text("[]", encoding="utf-8")

        result = asyncio.run(get_session_presets())

        assert result["data"]["presets"] == [
            {
                "id": "online-scene",
                "name": "线上导入场景",
                "agent_ids": ["online-expert"],
                "leader_agent_id": "online-expert",
                "description": "只剩资源目录镜像时也应能刷新出来",
                "discussion_goal_example": "",
            }
        ]
        assert json.loads(preset_path.read_text(encoding="utf-8"))[0]["id"] == "online-scene"
    finally:
        reset_current_user_identity(token)


def test_save_mcp_config_mirrors_tools_resource_files(monkeypatch, tmp_path):
    import json

    from app.api.settings_mcp import save_mcp_config
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-save", username="save@example.com")
    try:
        save_mcp_config(
            [
                {
                    "id": "tool-resource-flow",
                    "name": "资源目录工具",
                    "type": "mcp",
                    "enabled": True,
                    "transport": {"type": "stdio", "command": "python", "args": ["server.py"]},
                }
            ]
        )

        user_root = tmp_path / "users" / "user-resource-save"
        tool_file = user_root / "resources" / "tools" / "tool-resource-flow" / "tool.json"
        assert tool_file.is_file()
        assert json.loads(tool_file.read_text(encoding="utf-8"))["name"] == "资源目录工具"

        save_mcp_config([])
        assert not tool_file.exists()
    finally:
        reset_current_user_identity(token)
