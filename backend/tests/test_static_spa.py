from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.static_spa import HTML_CACHE, LONG_LIVED_STATIC_CACHE, mount_static_spa


def test_static_spa_cache_headers(monkeypatch, tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "expert-avatars" / "thumbs").mkdir(parents=True)
    (tmp_path / "index.html").write_text("<!doctype html><div id='app'></div>", encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log('ok')", encoding="utf-8")
    (tmp_path / "expert-avatars" / "thumbs" / "expert-01.png").write_bytes(b"png")

    monkeypatch.setenv("STATIC_DIR", str(tmp_path))
    app = FastAPI()
    assert mount_static_spa(app) is True

    client = TestClient(app)

    index_resp = client.get("/")
    assert index_resp.status_code == 200
    assert index_resp.headers["cache-control"] == HTML_CACHE

    asset_resp = client.get("/assets/index-abc123.js")
    assert asset_resp.status_code == 200
    assert asset_resp.headers["cache-control"] == LONG_LIVED_STATIC_CACHE

    avatar_resp = client.get("/expert-avatars/thumbs/expert-01.png")
    assert avatar_resp.status_code == 200
    assert avatar_resp.headers["cache-control"] == LONG_LIVED_STATIC_CACHE

    route_resp = client.get("/workspace")
    assert route_resp.status_code == 200
    assert route_resp.headers["cache-control"] == HTML_CACHE
