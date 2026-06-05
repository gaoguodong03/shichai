from __future__ import annotations

from pathlib import Path


def test_public_share_routes_are_removed():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    assert client.get("/api/public/shares/aaaaaaaaaaaa/meta").status_code == 404
    assert client.get("/api/public/scenarios/aaaaaaaaaaaa").status_code == 404
    assert client.post("/api/settings/session-presets/scenario-1/publish-share").status_code == 404
    assert client.get("/api/settings/session-presets/scenario-1/share-link").status_code == 404


def test_scene_bundle_import_remaps_same_name_tree(monkeypatch, tmp_path: Path):
    import json

    from app.api import settings_presets as api
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

    scenario_resource = user_root / "resources" / "scenarios" / "shared-scene" / "scenario.json"
    agent_resource = user_root / "resources" / "agents" / "shared-expert" / "agent.json"
    tool_resource = user_root / "resources" / "tools" / "shared-mcp" / "tool.json"
    skill_resource = user_root / "resources" / "skills" / "shared-skill" / "SKILL.md"
    assert json.loads(scenario_resource.read_text(encoding="utf-8"))["name"] == "Scene A"
    assert json.loads(agent_resource.read_text(encoding="utf-8"))["id"] == "shared-expert"
    assert json.loads(tool_resource.read_text(encoding="utf-8"))["name"] == "Tool A"
    assert skill_resource.is_file()


def test_scene_bundle_upload_import_persists_for_refresh(monkeypatch, tmp_path: Path):
    import json

    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.main import app

    user_root_base = tmp_path / "users"
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(user_root_base))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")

    source_skills = tmp_path / "source_skills"
    shared_skill = source_skills / "shared-skill"
    shared_skill.mkdir(parents=True)
    shared_skill.joinpath("SKILL.md").write_text(
        "---\nname: Shared Skill\ndescription: new\n---\nnew\n",
        encoding="utf-8",
    )
    bundle_bytes = build_scenario_bundle_zip_bytes(
        {
            "id": "online-scene",
            "name": "Online Scene",
            "agent_ids": ["online-expert"],
            "host_config": {"skill_ids": ["shared-skill"], "mcp_server_ids": ["online-mcp"]},
        },
        [
            {
                "agent_id": "online-expert",
                "name": "Online Expert",
                "skill_ids": ["shared-skill"],
                "mcp_server_ids": ["online-mcp"],
            }
        ],
        [{"id": "online-mcp", "name": "Online Tool", "enabled": True}],
        source_skills,
        ["shared-skill"],
    )

    from fastapi.testclient import TestClient

    client = TestClient(app)
    headers = {"Authorization": "Bearer test-token"}
    imported = client.post(
        "/api/settings/session-presets/import-bundle",
        files={
            "file": ("scene-bundle.zip", bundle_bytes, "application/zip"),
            "dry_run": (None, "false"),
            "overwrite_experts": (None, "true"),
            "overwrite_skills": (None, "true"),
            "mcp_skip_existing": (None, "false"),
            "preset_id_conflict": (None, "overwrite"),
        },
        headers=headers,
    )
    assert imported.status_code == 200

    refreshed = client.get("/api/settings/session-presets", headers=headers)
    assert refreshed.status_code == 200
    presets = refreshed.json()["data"]["presets"]
    assert [x["id"] for x in presets] == ["online-scene"]
    assert presets[0]["agent_ids"] == ["online-expert"]

    user_root = user_root_base / "u1"
    scenario_resource = user_root / "resources" / "scenarios" / "online-scene" / "scenario.json"
    assert json.loads(scenario_resource.read_text(encoding="utf-8"))["name"] == "Online Scene"


def test_scene_bundle_dry_run_reports_missing_expert(monkeypatch, tmp_path: Path):
    from app.api import settings_presets as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None

    raw = build_scenario_bundle_zip_bytes(
        {"id": "scene-1", "name": "Scene 1", "agent_ids": ["missing-expert"]},
        [],
        [],
        tmp_path / "source_skills",
        [],
    )
    try:
        result = __import__("asyncio").run(api._import_scene_from_bundle_bytes(raw, dry_run=True))
    finally:
        reset_current_username(token)

    missing = result["preview"]["missing_references"]
    assert missing["experts"][0]["id"] == "missing-expert"
    assert missing["experts"][0]["display_name"] == "专家 missing-expert"
    assert missing["experts"][0]["type_label"] == "专家"
    assert missing["skills"] == []
    assert missing["tools"] == []


def test_expert_bundle_dry_run_reports_missing_skill(monkeypatch, tmp_path: Path):
    from app.api import settings as api
    from app.core.expert_bundle import build_expert_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None

    raw = build_expert_bundle_zip_bytes(
        {
            "agent_id": "expert-1",
            "name": "Expert 1",
            "skill_ids": ["missing-skill"],
            "mcp_server_ids": [],
        },
        [],
        tmp_path / "source_skills",
        [],
    )
    try:
        result = __import__("asyncio").run(api._import_expert_from_bundle_bytes(raw, dry_run=True))
    finally:
        reset_current_username(token)

    missing = result["preview"]["missing_references"]
    assert missing["skills"][0]["id"] == "missing-skill"
    assert missing["skills"][0]["display_name"] == "技能 missing-skill"
    assert missing["skills"][0]["required_by"] == ["专家 Expert 1"]
    assert missing["experts"] == []
    assert missing["tools"] == []


def test_skill_bundle_dry_run_reports_missing_mcp_and_ignores_existing(monkeypatch, tmp_path: Path):
    import json

    from app.api import settings as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    ctx.config_dir.joinpath("mcp_servers.json").write_text(
        json.dumps([{"id": "existing-tool", "name": "Existing"}], ensure_ascii=False),
        encoding="utf-8",
    )

    source_skills = tmp_path / "source_skills"
    skill_dir = source_skills / "skill-a"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\n"
        "name: Skill A\n"
        "auto-tools:\n"
        "  mcp:\n"
        "    - missing-tool\n"
        "    - existing-tool\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    raw = build_scenario_bundle_zip_bytes(
        {"id": "dummy", "name": "Dummy", "agent_ids": ["dummy"]},
        [],
        [],
        source_skills,
        ["skill-a"],
    )
    try:
        result = __import__("asyncio").run(api._import_skill_from_bundle_bytes(raw, dry_run=True))
    finally:
        reset_current_username(token)

    missing = result["preview"]["missing_references"]
    assert [x["id"] for x in missing["tools"]] == ["missing-tool"]
    assert missing["tools"][0]["display_name"] == "MCP 工具 missing-tool"
    assert missing["tools"][0]["required_by"] == ["技能 Skill A"]


def test_skill_bundle_missing_mcp_uses_name_hint_when_declared(monkeypatch, tmp_path: Path):
    from app.api import settings as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None

    source_skills = tmp_path / "source_skills"
    skill_dir = source_skills / "skill-a"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\n"
        "name: Skill A\n"
        "auto-tools:\n"
        "  mcp:\n"
        "    - id: missing-tool\n"
        "      name: Missing Tool Name\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    raw = build_scenario_bundle_zip_bytes(
        {"id": "dummy", "name": "Dummy", "agent_ids": ["dummy"]},
        [],
        [],
        source_skills,
        ["skill-a"],
    )
    try:
        result = __import__("asyncio").run(api._import_skill_from_bundle_bytes(raw, dry_run=True))
    finally:
        reset_current_username(token)

    missing = result["preview"]["missing_references"]
    assert missing["tools"][0]["id"] == "missing-tool"
    assert missing["tools"][0]["name"] == "Missing Tool Name"
    assert missing["tools"][0]["display_name"] == "Missing Tool Name"


def test_skill_bundle_import_merges_bundled_mcp(monkeypatch, tmp_path: Path):
    import json

    from app.api import settings as api
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None

    source_skill = tmp_path / "source_skill"
    source_skill.mkdir()
    source_skill.joinpath("SKILL.md").write_text(
        "---\n"
        "name: Skill A\n"
        "auto-tools:\n"
        "  mcp:\n"
        "    - tool-a\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    raw = api._build_skill_zip_bytes(source_skill, [{"id": "tool-a", "name": "Tool A", "enabled": True}])
    try:
        result = __import__("asyncio").run(api._import_skill_from_bundle_bytes(raw, dry_run=False))
        mcp_rows = json.loads(ctx.config_dir.joinpath("mcp_servers.json").read_text(encoding="utf-8"))
    finally:
        reset_current_username(token)

    assert result["summary"]["mcp_added"] == 1
    assert result["summary"]["missing_references"]["tools"] == []
    assert [row["id"] for row in mcp_rows] == ["tool-a"]
    assert not (ctx.skills_dir / str(result["imported_skill_id"]) / "mcp_servers.json").exists()
