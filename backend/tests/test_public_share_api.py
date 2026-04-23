from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def test_public_share_meta_returns_object_type(monkeypatch):
    from app.api import public_scenario as api
    from app.main import app

    monkeypatch.setattr(api, "validate_share_id", lambda _sid: True)
    monkeypatch.setattr(
        api,
        "get_share_entry",
        lambda _sid: {
            "object_type": "skill",
            "source_ref": "skill-1",
            "title": "技能A",
            "summary": {"skill_count": 1},
            "created_at": "2026-04-23T00:00:00+00:00",
        },
    )

    client = TestClient(app)
    resp = client.get("/api/public/shares/aaaaaaaaaaaa/meta")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["share_id"] == "aaaaaaaaaaaa"
    assert data["object_type"] == "skill"
    assert data["source_ref"] == "skill-1"
    assert data["title"] == "技能A"


def test_public_share_bundle_download_success(monkeypatch, tmp_path: Path):
    from app.api import public_scenario as api
    from app.main import app

    bundle_path = tmp_path / "bundle.zip"
    bundle_path.write_bytes(b"PK\x03\x04dummy")
    monkeypatch.setattr(api, "validate_share_id", lambda _sid: True)
    monkeypatch.setattr(api, "bundle_path_for_share", lambda _sid: bundle_path)

    client = TestClient(app)
    resp = client.get("/api/public/shares/aaaaaaaaaaaa/bundle")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/zip")
    assert resp.content.startswith(b"PK")


def test_settings_share_import_dispatch_scene(monkeypatch):
    from app.api import settings as api
    from app.main import app

    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: {"sub": "u1"})
    monkeypatch.setattr("app.core.scenario_share_store.validate_share_id", lambda _sid: True)
    monkeypatch.setattr(
        "app.core.scenario_share_store.get_share_entry",
        lambda _sid: {"object_type": "scene", "source_ref": "preset-1"},
    )
    monkeypatch.setattr("app.core.scenario_share_store.bundle_path_for_share", lambda _sid: Path(__file__))

    async def _mock_import_scene(raw: bytes, *, dry_run: bool):
        assert isinstance(raw, bytes)
        return {"object_type": "scene", "summary": {"preset_imported_ids": ["preset-1"]}}

    monkeypatch.setattr(api, "_import_scene_from_bundle_bytes", _mock_import_scene)

    client = TestClient(app)
    resp = client.post(
        "/api/settings/shares/aaaaaaaaaaaa/import",
        files={"dry_run": (None, "false")},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    j = resp.json()
    assert j["status"] == "ok"
    assert j["data"]["object_type"] == "scene"
