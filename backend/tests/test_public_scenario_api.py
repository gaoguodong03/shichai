from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_public_scenario_meta_404_on_invalid_share_id():
    from app.main import app

    client = TestClient(app)
    resp = client.get("/api/public/scenarios/not-valid-id")
    assert resp.status_code == 404


def test_public_scenario_meta_returns_entry(monkeypatch):
    from app.api import public_scenario as api
    from app.main import app

    monkeypatch.setattr(api, "validate_share_id", lambda _sid: True)
    monkeypatch.setattr(
        api,
        "get_share_entry",
        lambda _sid: {
            "preset_name": "示例场景",
            "source_preset_id": "preset-1",
            "created_at": "2026-04-22T00:00:00+00:00",
        },
    )

    client = TestClient(app)
    resp = client.get("/api/public/scenarios/aaaaaaaaaaaa")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["share_id"] == "aaaaaaaaaaaa"
    assert data["preset_name"] == "示例场景"
    assert data["source_preset_id"] == "preset-1"


def test_public_scenario_bundle_download_success(monkeypatch, tmp_path: Path):
    from app.api import public_scenario as api
    from app.main import app

    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(b"PK\x03\x04dummy")
    monkeypatch.setattr(api, "validate_share_id", lambda _sid: True)
    monkeypatch.setattr(api, "bundle_path_for_share", lambda _sid: bundle_path)

    client = TestClient(app)
    resp = client.get("/api/public/scenarios/aaaaaaaaaaaa/bundle")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/zip")
    assert resp.content.startswith(b"PK")


def test_public_scenario_bundle_404_when_file_missing(monkeypatch):
    from app.api import public_scenario as api
    from app.main import app

    monkeypatch.setattr(api, "validate_share_id", lambda _sid: True)
    monkeypatch.setattr(api, "bundle_path_for_share", lambda _sid: None)

    client = TestClient(app)
    resp = client.get("/api/public/scenarios/aaaaaaaaaaaa/bundle")
    assert resp.status_code == 404
