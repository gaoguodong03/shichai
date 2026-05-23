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
