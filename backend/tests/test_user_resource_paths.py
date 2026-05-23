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
