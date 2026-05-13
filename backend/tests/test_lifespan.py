from app.core.lifespan import _startup_prewarm_all_users_enabled, _startup_prewarm_timeout_ms


def test_startup_prewarm_all_users_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SANDBOX_PREWARM_ALL_USERS", raising=False)

    assert _startup_prewarm_all_users_enabled() is False


def test_startup_prewarm_all_users_can_be_enabled(monkeypatch):
    monkeypatch.setenv("SANDBOX_PREWARM_ALL_USERS", "1")

    assert _startup_prewarm_all_users_enabled() is True


def test_startup_prewarm_timeout_defaults_to_long_login_timeout(monkeypatch):
    monkeypatch.delenv("SANDBOX_PREWARM_ALL_USERS_TIMEOUT_MS", raising=False)
    monkeypatch.delenv("SANDBOX_LOGIN_PREWARM_TIMEOUT_MS", raising=False)

    assert _startup_prewarm_timeout_ms() == 600_000


def test_startup_prewarm_timeout_can_be_overridden(monkeypatch):
    monkeypatch.setenv("SANDBOX_LOGIN_PREWARM_TIMEOUT_MS", "240000")
    monkeypatch.setenv("SANDBOX_PREWARM_ALL_USERS_TIMEOUT_MS", "300000")

    assert _startup_prewarm_timeout_ms() == 300_000


def test_startup_prewarm_timeout_keeps_minimum(monkeypatch):
    monkeypatch.setenv("SANDBOX_PREWARM_ALL_USERS_TIMEOUT_MS", "1")

    assert _startup_prewarm_timeout_ms() == 120_000
