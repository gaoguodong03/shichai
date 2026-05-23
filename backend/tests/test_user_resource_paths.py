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
