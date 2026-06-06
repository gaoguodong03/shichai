from fastapi.testclient import TestClient

from app.main import create_app
from app.core.lifespan import _startup_prewarm_all_users_enabled, _startup_prewarm_timeout_ms
from app.core.security import _prewarm_on_user_request_enabled


def test_health_endpoint_returns_ok(monkeypatch):
    monkeypatch.delenv("STATIC_DIR", raising=False)
    client = TestClient(create_app())

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_startup_prewarm_all_users_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SANDBOX_PREWARM_ALL_USERS", raising=False)

    assert _startup_prewarm_all_users_enabled() is False


def test_startup_prewarm_all_users_can_be_enabled(monkeypatch):
    monkeypatch.setenv("SANDBOX_PREWARM_ALL_USERS", "1")

    assert _startup_prewarm_all_users_enabled() is True


def test_request_prewarm_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SANDBOX_PREWARM_ON_USER_REQUEST", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    assert _prewarm_on_user_request_enabled() is False


def test_request_prewarm_can_be_enabled(monkeypatch):
    monkeypatch.setenv("SANDBOX_PREWARM_ON_USER_REQUEST", "1")

    assert _prewarm_on_user_request_enabled() is True


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
