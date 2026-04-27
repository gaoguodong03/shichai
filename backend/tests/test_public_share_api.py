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

    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")
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


def test_scene_share_import_remaps_same_name_tree(monkeypatch, tmp_path: Path):
    import json

    from app.api import settings as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    user_root = ctx.base_dir
    config_dir = ctx.config_dir
    skills_dir = ctx.skills_dir
    local_skill = skills_dir / "local-skill"
    local_skill.mkdir()
    local_skill.joinpath("SKILL.md").write_text("---\nname: Skill A\ndescription: old\n---\nold\n", encoding="utf-8")
    config_dir.joinpath("dha_instances.json").write_text(
        json.dumps(
            [
                {
                    "agent_id": "local-expert",
                    "name": "Expert A",
                    "skill_ids": ["local-skill"],
                    "mcp_server_ids": ["local-mcp"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_dir.joinpath("mcp_servers.json").write_text(
        json.dumps([{"id": "local-mcp", "name": "Tool A", "enabled": True}], ensure_ascii=False),
        encoding="utf-8",
    )
    config_dir.joinpath("session_presets.json").write_text(
        json.dumps(
            [
                {
                    "id": "local-scene",
                    "name": "Scene A",
                    "agent_ids": ["local-expert"],
                    "host_config": {"skill_ids": ["local-skill"], "mcp_server_ids": ["local-mcp"]},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    source_skills = tmp_path / "source_skills"
    shared_skill = source_skills / "shared-skill"
    shared_skill.mkdir(parents=True)
    shared_skill.joinpath("SKILL.md").write_text("---\nname: Skill A\ndescription: new\n---\nnew\n", encoding="utf-8")
    raw = build_scenario_bundle_zip_bytes(
        {
            "id": "shared-scene",
            "name": "Scene A",
            "agent_ids": ["shared-expert"],
            "host_config": {"skill_ids": ["shared-skill"], "mcp_server_ids": ["shared-mcp"]},
        },
        [
            {
                "agent_id": "shared-expert",
                "name": "Expert A",
                "skill_ids": ["shared-skill"],
                "mcp_server_ids": ["shared-mcp"],
            }
        ],
        [{"id": "shared-mcp", "name": "Tool A", "enabled": True}],
        source_skills,
        ["shared-skill"],
    )

    try:
        result = __import__("asyncio").run(api._import_scene_from_bundle_bytes(raw, dry_run=False))
    finally:
        reset_current_username(token)
    summary = result["summary"]
    assert summary["overwritten_existing_ids"] == ["local-scene"]
    assert summary["skill_id_map"] == {"local-skill": "shared-skill"}
    assert summary["mcp_id_map"] == {"local-mcp": "shared-mcp"}
    assert not local_skill.exists()
    assert (skills_dir / "shared-skill" / "SKILL.md").is_file()

    experts = json.loads(config_dir.joinpath("dha_instances.json").read_text(encoding="utf-8"))
    assert [x["agent_id"] for x in experts] == ["shared-expert"]
    assert experts[0]["skill_ids"] == ["shared-skill"]
    assert experts[0]["mcp_server_ids"] == ["shared-mcp"]

    mcps = json.loads(config_dir.joinpath("mcp_servers.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in mcps] == ["shared-mcp"]

    presets = json.loads(config_dir.joinpath("session_presets.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in presets] == ["shared-scene"]
    assert presets[0]["host_config"]["skill_ids"] == ["shared-skill"]
    assert presets[0]["host_config"]["mcp_server_ids"] == ["shared-mcp"]
