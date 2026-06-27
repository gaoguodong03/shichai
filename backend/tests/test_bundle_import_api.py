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


def test_scene_bundle_import_keeps_same_name_tree(monkeypatch, tmp_path: Path):
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
                    "role": "old role",
                    "skill_ids": ["local-skill"],
                    "mcp_server_ids": ["local-mcp"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_dir.joinpath("mcp_servers.json").write_text(
        json.dumps([{"id": "local-mcp", "name": "Tool A", "transport": {"type": "stdio", "command": "old"}}], ensure_ascii=False),
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
                "role": "new role",
                "skill_ids": ["shared-skill"],
                "mcp_server_ids": ["shared-mcp"],
            }
        ],
        [{"id": "shared-mcp", "name": "Tool A", "transport": {"type": "stdio", "command": "new"}}],
        source_skills,
        ["shared-skill"],
    )

    try:
        preview = __import__("asyncio").run(api._import_scene_from_bundle_bytes(raw, dry_run=True))
        assert preview["preview"]["skill_names"] == {"shared-skill": "Skill A"}
        result = __import__("asyncio").run(api._import_scene_from_bundle_bytes(raw, dry_run=False))
    finally:
        reset_current_username(token)
    summary = result["summary"]
    assert summary["skipped_by_name"] == []
    assert summary["kept_existing_ids"] == ["local-scene"]
    assert summary["skill_id_map"] == {"shared-skill": "local-skill"}
    assert summary["mcp_id_map"] == {"shared-mcp": "local-mcp"}
    assert local_skill.exists()
    assert not (skills_dir / "shared-skill" / "SKILL.md").exists()
    assert "description: old" in local_skill.joinpath("SKILL.md").read_text(encoding="utf-8")

    experts = json.loads(config_dir.joinpath("dha_instances.json").read_text(encoding="utf-8"))
    assert [x["agent_id"] for x in experts] == ["local-expert"]
    assert experts[0]["role"] == "old role"
    assert experts[0]["skill_ids"] == ["local-skill"]
    assert experts[0]["mcp_server_ids"] == ["local-mcp"]

    mcps = json.loads(config_dir.joinpath("mcp_servers.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in mcps] == ["local-mcp"]
    assert mcps[0]["transport"]["command"] == "old"

    presets = json.loads(config_dir.joinpath("session_presets.json").read_text(encoding="utf-8"))
    assert [x["id"] for x in presets] == ["local-scene"]
    assert presets[0]["host_config"]["skill_ids"] == ["local-skill"]
    assert presets[0]["host_config"]["mcp_server_ids"] == ["local-mcp"]

    scenario_resource = user_root / "resources" / "scenarios" / "local-scene" / "scenario.json"
    agent_resource = user_root / "resources" / "agents" / "local-expert" / "agent.json"
    tool_resource = user_root / "resources" / "tools" / "local-mcp" / "tool.json"
    skill_resource = user_root / "resources" / "skills" / "local-skill" / "SKILL.md"
    assert json.loads(scenario_resource.read_text(encoding="utf-8"))["name"] == "Scene A"
    assert json.loads(agent_resource.read_text(encoding="utf-8"))["id"] == "local-expert"
    assert json.loads(tool_resource.read_text(encoding="utf-8"))["name"] == "Tool A"
    assert skill_resource.is_file()


def test_scene_bundle_import_regenerates_ids_when_names_differ(monkeypatch, tmp_path: Path):
    import json

    from app.api import settings_presets as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    config_dir = ctx.config_dir
    skills_dir = ctx.skills_dir
    existing_skill = skills_dir / "shared-skill"
    existing_skill.mkdir()
    existing_skill.joinpath("SKILL.md").write_text(
        "---\nname: Old Skill\ndescription: old\n---\nold\n",
        encoding="utf-8",
    )
    config_dir.joinpath("dha_instances.json").write_text(
        json.dumps(
            [
                {
                    "agent_id": "shared-expert",
                    "name": "Old Expert",
                    "skill_ids": ["shared-skill"],
                    "mcp_server_ids": ["shared-mcp"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config_dir.joinpath("mcp_servers.json").write_text(
        json.dumps([{"id": "shared-mcp", "name": "Old Tool", "enabled": True}], ensure_ascii=False),
        encoding="utf-8",
    )
    config_dir.joinpath("session_presets.json").write_text(
        json.dumps(
            [
                {
                    "id": "shared-scene",
                    "name": "Old Scene",
                    "agent_ids": ["shared-expert"],
                    "host_config": {"skill_ids": ["shared-skill"], "mcp_server_ids": ["shared-mcp"]},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    source_skills = tmp_path / "source_skills"
    incoming_skill = source_skills / "shared-skill"
    incoming_skill.mkdir(parents=True)
    incoming_skill.joinpath("SKILL.md").write_text(
        "---\nname: New Skill\ndescription: new\n---\nnew\n",
        encoding="utf-8",
    )
    raw = build_scenario_bundle_zip_bytes(
        {
            "id": "shared-scene",
            "name": "New Scene",
            "agent_ids": ["shared-expert"],
            "host_config": {"skill_ids": ["shared-skill"], "mcp_server_ids": ["shared-mcp"]},
        },
        [
            {
                "agent_id": "shared-expert",
                "name": "New Expert",
                "skill_ids": ["shared-skill"],
                "mcp_server_ids": ["shared-mcp"],
            }
        ],
        [{"id": "shared-mcp", "name": "New Tool", "enabled": True}],
        source_skills,
        ["shared-skill"],
    )

    try:
        result = __import__("asyncio").run(api._import_scene_from_bundle_bytes(raw, dry_run=False))
    finally:
        reset_current_username(token)

    summary = result["summary"]
    new_scene_id = summary["preset_imported_ids"][0]
    new_skill_id = summary["skill_id_map"]["shared-skill"]
    new_mcp_id = summary["mcp_id_map"]["shared-mcp"]
    assert new_scene_id != "shared-scene"
    assert new_skill_id != "shared-skill"
    assert new_mcp_id != "shared-mcp"
    assert new_skill_id.startswith("skill-")
    assert new_mcp_id.startswith("mcp-")

    experts = json.loads(config_dir.joinpath("dha_instances.json").read_text(encoding="utf-8"))
    assert len(experts) == 2
    new_expert = next(row for row in experts if row["name"] == "New Expert")
    assert new_expert["agent_id"] != "shared-expert"
    assert new_expert["skill_ids"] == [new_skill_id]
    assert new_expert["mcp_server_ids"] == [new_mcp_id]

    mcps = json.loads(config_dir.joinpath("mcp_servers.json").read_text(encoding="utf-8"))
    assert {row["name"] for row in mcps} == {"Old Tool", "New Tool"}
    assert any(row["id"] == new_mcp_id and row["name"] == "New Tool" for row in mcps)

    presets = json.loads(config_dir.joinpath("session_presets.json").read_text(encoding="utf-8"))
    assert len(presets) == 2
    new_scene = next(row for row in presets if row["name"] == "New Scene")
    assert new_scene["id"] == new_scene_id
    assert new_scene["agent_ids"] == [new_expert["agent_id"]]
    assert new_scene["host_config"]["skill_ids"] == [new_skill_id]
    assert new_scene["host_config"]["mcp_server_ids"] == [new_mcp_id]

    assert (skills_dir / "shared-skill" / "SKILL.md").read_text(encoding="utf-8").find("Old Skill") >= 0
    assert (skills_dir / new_skill_id / "SKILL.md").is_file()


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
    summary = imported.json()["data"]["summary"]
    imported_scene_id = summary["preset_imported_ids"][0]
    imported_agent_id = summary["agent_id_map"]["online-expert"]
    assert imported_scene_id != "online-scene"
    assert imported_agent_id != "online-expert"

    refreshed = client.get("/api/settings/session-presets", headers=headers)
    assert refreshed.status_code == 200
    presets = refreshed.json()["data"]["presets"]
    assert [x["id"] for x in presets] == [imported_scene_id]
    assert presets[0]["agent_ids"] == [imported_agent_id]

    user_root = user_root_base / "u1"
    scenario_resource = user_root / "resources" / "scenarios" / imported_scene_id / "scenario.json"
    assert json.loads(scenario_resource.read_text(encoding="utf-8"))["name"] == "Online Scene"


def test_scene_bundle_upload_dry_run_reports_same_name_expert_conflicts(monkeypatch, tmp_path: Path):
    import json

    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username
    from app.main import app

    user_root_base = tmp_path / "users"
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(user_root_base))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    ctx.config_dir.joinpath("dha_instances.json").write_text(
        json.dumps(
            [
                {"agent_id": "local-expert-a", "name": "Expert A"},
                {"agent_id": "local-expert-b", "name": "Expert B"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    reset_current_username(token)

    source_skills = tmp_path / "source_skills"
    bundle_bytes = build_scenario_bundle_zip_bytes(
        {"id": "scene-1", "name": "Scene 1", "agent_ids": ["incoming-a", "incoming-b"]},
        [
            {"agent_id": "incoming-a", "name": "Expert A"},
            {"agent_id": "incoming-b", "name": "Expert B"},
        ],
        [],
        source_skills,
        [],
    )

    from fastapi.testclient import TestClient

    client = TestClient(app)
    preview = client.post(
        "/api/settings/session-presets/import-bundle",
        files={
            "file": ("scene-bundle.zip", bundle_bytes, "application/zip"),
            "dry_run": (None, "true"),
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert preview.status_code == 200
    bundle_preview = preview.json()["data"]["bundle_preview"]
    assert bundle_preview["would_overwrite_experts"] == {
        "incoming-a": ["local-expert-a"],
        "incoming-b": ["local-expert-b"],
    }


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


def test_scene_bundle_dry_run_ignores_legacy_group_host_stale_ref(monkeypatch, tmp_path: Path):
    from app.api import settings_presets as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None

    raw = build_scenario_bundle_zip_bytes(
        {
            "id": "scene-1",
            "name": "Scene 1",
            "agent_ids": ["expert-1"],
            "host_config": {
                "skill_ids": ["group-host"],
                "skill_refs": [{"id": "group-host", "name": "网文协同写作主持人"}],
            },
        },
        [{"agent_id": "expert-1", "name": "Expert 1", "skill_ids": [], "mcp_server_ids": []}],
        [],
        tmp_path / "source_skills",
        [],
    )
    try:
        result = __import__("asyncio").run(api._import_scene_from_bundle_bytes(raw, dry_run=True))
    finally:
        reset_current_username(token)

    missing = result["preview"]["missing_references"]
    assert result["preview"]["skills"] == []
    assert missing["experts"] == []
    assert missing["skills"] == []
    assert missing["tools"] == []


def test_expert_bundle_dry_run_reports_missing_skill(monkeypatch, tmp_path: Path):
    from app.api import settings_skills as api
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

    from app.api import settings_skills as api
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
    from app.api import settings_skills as api
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

    from app.api import settings_skills as api
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
    imported_mcp_id = result["summary"]["mcp_id_map"]["tool-a"]
    assert imported_mcp_id.startswith("mcp-")
    assert [row["id"] for row in mcp_rows] == [imported_mcp_id]
    skill_text = (ctx.skills_dir / str(result["imported_skill_id"]) / "SKILL.md").read_text(encoding="utf-8")
    assert imported_mcp_id in skill_text
    assert "tool-a" not in skill_text
    assert not (ctx.skills_dir / str(result["imported_skill_id"]) / "mcp_servers.json").exists()


def test_skill_zip_import_keeps_same_name_local_skill(monkeypatch, tmp_path: Path):
    from app.api import settings_skills as api
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username
    from app.main import app

    user_root_base = tmp_path / "users"
    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(user_root_base))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")

    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    local_skill = ctx.skills_dir / "local-skill"
    local_skill.mkdir(parents=True)
    local_skill.joinpath("SKILL.md").write_text(
        "---\nname: Skill A\ndescription: old\n---\nold body\n",
        encoding="utf-8",
    )
    reset_current_username(token)

    source_skill = tmp_path / "source_skill"
    source_skill.mkdir()
    source_skill.joinpath("SKILL.md").write_text(
        "---\nname: Skill A\ndescription: new\n---\nnew body\n",
        encoding="utf-8",
    )
    raw = api._build_skill_zip_bytes(source_skill, [])

    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/api/settings/skills/import-zip",
        files={"file": ("skill-a.zip", raw, "application/zip")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["id"] == "local-skill"
    assert data["kept_skill_ids"] == ["local-skill"]
    assert "description: old" in local_skill.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert not (ctx.skills_dir / "skill-a" / "SKILL.md").exists()
