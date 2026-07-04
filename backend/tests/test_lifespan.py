from fastapi.testclient import TestClient

from app.main import create_app
from app.core.lifespan import _startup_prewarm_all_users_enabled
from app.core.security import _prewarm_on_user_request_enabled


def test_health_endpoint_returns_ok(monkeypatch):
    monkeypatch.delenv("STATIC_DIR", raising=False)
    client = TestClient(create_app())

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_endpoint_is_not_shadowed_by_static_spa(monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id='app'></div>", encoding="utf-8")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    client = TestClient(create_app())

    resp = client.get("/health")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"status": "ok"}


def test_startup_prewarm_all_users_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SANDBOX_PREWARM_ALL_USERS", raising=False)

    assert _startup_prewarm_all_users_enabled() is False


def test_startup_prewarm_all_users_cannot_be_enabled(monkeypatch):
    monkeypatch.setenv("SANDBOX_PREWARM_ALL_USERS", "1")

    assert _startup_prewarm_all_users_enabled() is False


def test_request_prewarm_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SANDBOX_PREWARM_ON_USER_REQUEST", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    assert _prewarm_on_user_request_enabled() is False


def test_request_prewarm_cannot_be_enabled(monkeypatch):
    monkeypatch.setenv("SANDBOX_PREWARM_ON_USER_REQUEST", "1")

    assert _prewarm_on_user_request_enabled() is False
