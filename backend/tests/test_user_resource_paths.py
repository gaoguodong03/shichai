def test_user_context_uses_user_id_not_email(monkeypatch, tmp_path):
    from app.core.user_context import build_user_context

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))

    ctx = build_user_context(user_id="user-abc123", username="alice@example.com")

    assert ctx.user_id == "user-abc123"
    assert ctx.username == "alice@example.com"
    assert ctx.base_dir == (tmp_path / "users" / "user-abc123").resolve()
    assert ctx.resources_dir == ctx.base_dir / "resources"
    assert ctx.sessions_dir == ctx.base_dir / "sessions"
    assert ctx.settings_dir == ctx.base_dir / "settings"
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
        env_vars_path,
        app_settings_path,
        sandbox_requirements_path,
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
        assert app_settings_path() == root / "settings" / "app.json"
        assert env_vars_path() == root / "settings" / "env.enc.json"
        assert sandbox_requirements_path() == root / "settings" / "sandbox" / "requirements.txt"
    finally:
        reset_current_user_identity(token)


def test_env_var_values_use_current_user_env_store(monkeypatch, tmp_path):
    import json

    from app.api.settings_env_vars import load_env_var_values
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    user_settings = tmp_path / "users" / "user-env-owner" / "settings"
    user_settings.mkdir(parents=True)
    (user_settings / "env.enc.json").write_text(
        json.dumps({"items": {"JENIYA_API_KEY": {"label": "Jeniya", "value": "from-user-env", "sensitive": True}}}),
        encoding="utf-8",
    )

    token = set_current_user_identity(user_id="user-env-owner", username="owner@example.com")
    try:
        assert load_env_var_values() == {"JENIYA_API_KEY": "from-user-env"}
    finally:
        reset_current_user_identity(token)


def test_env_var_values_ignore_legacy_secret_files(monkeypatch, tmp_path):
    import json

    from app.api.settings_env_vars import load_env_var_values
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    user_config = tmp_path / "users" / "user-env-owner" / "settings"
    user_config.mkdir(parents=True)
    (user_config / ("secrets" + ".enc.json")).write_text(
        json.dumps({"items": {"legacy": {"label": "Legacy", "api_key": "from-legacy-secret"}}}),
        encoding="utf-8",
    )

    token = set_current_user_identity(user_id="user-env-owner", username="owner@example.com")
    try:
        assert load_env_var_values() == {}
    finally:
        reset_current_user_identity(token)


def test_create_env_var_writes_current_user_env_store_only(monkeypatch, tmp_path):
    import asyncio
    import json

    from app.api.settings_env_vars import EnvVarCreate, create_env_var
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-env-owner", username="owner@example.com")
    try:
        asyncio.run(
            create_env_var(
                EnvVarCreate(name="JENIYA_API_KEY", label="Jeniya", value="from-user-env")
            )
        )

        user_root = tmp_path / "users" / "user-env-owner"
        env_path = user_root / "settings" / "env.enc.json"
        secret_path = user_root / "settings" / ("secrets" + ".enc.json")
        assert env_path.is_file()
        assert not secret_path.exists()
        data = json.loads(env_path.read_text(encoding="utf-8"))
        assert data["items"]["JENIYA_API_KEY"]["value"] == "from-user-env"
        assert data["items"]["JENIYA_API_KEY"]["sensitive"] is True
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
                    "name": "资源目录专家",
                    "description": "验证专家资源落盘",
                    "skills": [],
                }
            ]
        )

        user_root = tmp_path / "users" / "user-resource-save"
        agent_file = user_root / "resources" / "agents" / "资源目录专家" / "agent.json"
        assert agent_file.is_file()
        agent_data = json.loads(agent_file.read_text(encoding="utf-8"))
        assert "id" not in agent_data
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
                    name="资源目录场景",
                    agent_names=["资源目录专家"],
                    description="验证场景资源落盘",
                    host={"name": "主持人"},
                )
            ]
        )
        asyncio.run(update_session_presets(body))

        user_root = tmp_path / "users" / "user-resource-save"
        scenario_file = user_root / "resources" / "scenarios" / "资源目录场景" / "scenario.json"
        assert scenario_file.is_file()
        scenario_data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert scenario_data["name"] == "资源目录场景"
        assert "id" not in scenario_data

        asyncio.run(update_session_presets(SessionPresetsBody(presets=[])))
        assert not scenario_file.exists()
    finally:
        reset_current_user_identity(token)


def test_update_session_presets_preserves_missing_agent_references(monkeypatch, tmp_path):
    import asyncio
    import json

    from app.api.agents import save_agent_instances
    from app.api.settings_presets import SessionPresetItem, SessionPresetsBody, update_session_presets
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-missing-ref", username="missing-ref@example.com")
    try:
        save_agent_instances([{"name": "现有专家", "description": "", "skills": []}])

        body = SessionPresetsBody(
            presets=[
                SessionPresetItem(
                    name="保留缺失专家场景",
                    agent_names=["现有专家", "已删除专家"],
                    description="验证缺失引用保留",
                )
            ]
        )
        asyncio.run(update_session_presets(body))

        scenario_file = (
            tmp_path
            / "users"
            / "user-resource-missing-ref"
            / "resources"
            / "scenarios"
            / "保留缺失专家场景"
            / "scenario.json"
        )
        scenario_data = json.loads(scenario_file.read_text(encoding="utf-8"))
        assert scenario_data["agent_names"] == ["现有专家", "已删除专家"]
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
        scenario_file = user_root / "resources" / "scenarios" / "线上导入场景" / "scenario.json"
        scenario_file.parent.mkdir(parents=True)
        scenario_file.write_text(
            json.dumps(
                {
                    "name": "线上导入场景",
                    "agent_names": ["线上专家"],
                    "description": "只剩资源目录镜像时也应能刷新出来",
                    "host": {"name": "主持人"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = asyncio.run(get_session_presets())

        assert result["data"]["presets"] == [
            {
                "name": "线上导入场景",
                "agent_names": ["线上专家"],
                "host": {"name": "主持人", "llm_name": "", "system_prompt": "", "skill_name": "", "skill_directory": ""},
                "description": "只剩资源目录镜像时也应能刷新出来",
                "system_prompt": "",
            }
        ]
        assert not (user_root / "settings" / "presets.json").exists()
        assert not (user_root / "config" / "session_presets.json").exists()
    finally:
        reset_current_user_identity(token)


def test_get_session_presets_does_not_log_noisy_ids(monkeypatch, tmp_path, caplog):
    import asyncio
    import json
    import logging

    from app.api.settings_presets import get_session_presets
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-quiet", username="quiet@example.com")
    try:
        user_root = tmp_path / "users" / "user-resource-quiet"
        scenario_file = user_root / "resources" / "scenarios" / "安静场景" / "scenario.json"
        scenario_file.parent.mkdir(parents=True)
        scenario_file.write_text(
            json.dumps(
                {
                    "name": "安静场景",
                    "agent_names": ["安静专家"],
                    "host": {"name": "主持人"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        with caplog.at_level(logging.INFO, logger="app.api.settings_presets"):
            result = asyncio.run(get_session_presets())

        assert result["data"]["presets"][0]["name"] == "安静场景"
        assert "scenario_presets_get" not in caplog.text
        assert "aggregate_ids=" not in caplog.text
        assert "returned_ids=" not in caplog.text
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
                    "name": "资源目录工具",
                    "type": "mcp",
                    "transport": {"type": "stdio", "command": "python", "args": ["server.py"]},
                }
            ]
        )

        user_root = tmp_path / "users" / "user-resource-save"
        tool_file = user_root / "resources" / "tools" / "资源目录工具" / "tool.json"
        assert tool_file.is_file()
        tool_data = json.loads(tool_file.read_text(encoding="utf-8"))
        assert tool_data["name"] == "资源目录工具"
        assert "id" not in tool_data

        save_mcp_config([])
        assert not tool_file.exists()
        assert not (user_root / "settings" / "mcp.json").exists()
        assert not (user_root / "config" / "mcp_servers.json").exists()
    finally:
        reset_current_user_identity(token)


def test_load_mcp_config_reads_tools_resource_files(monkeypatch, tmp_path):
    import json

    from app.api.settings_mcp import load_mcp_config
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-resource-load", username="load@example.com")
    try:
        user_root = tmp_path / "users" / "user-resource-load"
        tool_file = user_root / "resources" / "tools" / "资源目录工具" / "tool.json"
        tool_file.parent.mkdir(parents=True)
        tool_file.write_text(
            json.dumps(
                {
                    "name": "资源目录工具",
                    "type": "mcp",
                    "transport": {"type": "stdio", "command": "python", "args": ["server.py"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        rows = load_mcp_config()

        assert [row["name"] for row in rows] == ["资源目录工具"]
        assert not (user_root / "settings" / "mcp.json").exists()
        assert not (user_root / "config" / "mcp_servers.json").exists()
    finally:
        reset_current_user_identity(token)


def test_save_app_settings_stores_llm_providers_as_model_resources(monkeypatch, tmp_path):
    import json

    from app.api.settings_app import load_app_settings, save_app_settings
    from app.core.user_context import reset_current_user_identity, set_current_user_identity

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_user_identity(user_id="user-model-save", username="models@example.com")
    try:
        save_app_settings(
            {
                "default_llm": "自定义模型",
                "llm_providers": {
                    "自定义模型": {
                        "base_url": "https://example.test/v1",
                        "model": "custom-chat",
                        "api_key_env": "CUSTOM_API_KEY",
                    }
                },
            }
        )

        user_root = tmp_path / "users" / "user-model-save"
        app_path = user_root / "settings" / "app.json"
        model_file = user_root / "resources" / "models" / "自定义模型" / "model.json"
        assert app_path.is_file()
        assert model_file.is_file()
        assert "llm_providers" not in json.loads(app_path.read_text(encoding="utf-8"))
        model_data = json.loads(model_file.read_text(encoding="utf-8"))
        assert model_data["name"] == "自定义模型"
        assert model_data["base_url"] == "https://example.test/v1"
        assert model_data["api_key_env"] == "CUSTOM_API_KEY"
        assert load_app_settings()["llm_providers"]["自定义模型"]["model"] == "custom-chat"
    finally:
        reset_current_user_identity(token)
