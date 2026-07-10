"""Name-based bundle/import API tests."""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path


def _skill_ref(name: str, directory_name: str) -> dict:
    return {"name": name, "directory_name": directory_name}


def _mcp_row(name: str) -> dict:
    return {
        "name": name,
        "type": "mcp",
        "description": "",
        "server_config": json.dumps({"mcpServers": {name: {"command": "echo", "args": ["ok"]}}}),
    }


def test_skill_zip_import_uses_directory_name_not_display_name_identity(monkeypatch, tmp_path: Path):
    from app.api import settings_skills as api
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username
    from app.main import app

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")

    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    local_skill = ctx.skills_dir / "skill-local"
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
    import zipfile
    from io import BytesIO

    with zipfile.ZipFile(BytesIO(raw)) as zf:
        names = set(zf.namelist())
        assert "bundle.json" in names
        assert "SKILL.md" not in names
        assert "mcp_servers.json" not in names
        manifest = json.loads(zf.read("bundle.json").decode("utf-8"))
        assert manifest["bundle_type"] == "skill"
        assert "bundle_version" not in manifest
        assert "resources/skills/source_skill/SKILL.md" in names

    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/api/settings/skills/import-zip",
        files={"file": ("skill-a.zip", raw, "application/zip")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    imported_skill = ctx.skills_dir / "source_skill"
    assert data["directory_name"] == "source_skill"
    assert data["overwritten_by_directory"] is False
    assert data["summary"]["overwritten_directory_names"] == []
    assert "old body" in local_skill.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "new body" in imported_skill.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert sorted(p.name for p in ctx.skills_dir.iterdir() if p.is_dir()) == ["skill-local", "source_skill"]


def test_skill_bundle_dry_run_reports_missing_tool_by_name(monkeypatch, tmp_path: Path):
    from app.api import settings_skills as api
    from app.api.settings_mcp import save_mcp_config
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    save_mcp_config([_mcp_row("Existing")])

    source_skills = tmp_path / "source_skills"
    skill_dir = source_skills / "skill-a"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\n"
        "name: Skill A\n"
        "allowed-tools:\n"
        "  mcp:\n"
        "    - Missing Tool\n"
        "    - Existing\n"
        "  http_api: []\n"
        "  python: \"\"\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )
    raw = api._build_skill_zip_bytes(skill_dir, [])
    try:
        result = asyncio.run(api._import_skill_from_bundle_bytes(raw, dry_run=True))
    finally:
        reset_current_username(token)

    missing = result["preview"]["missing_references"]
    assert [x["name"] for x in missing["tools"]] == ["Missing Tool"]


def test_scene_bundle_import_overwrites_same_name_resources(monkeypatch, tmp_path: Path):
    from app.api.agents import save_agent_instances
    from app.api import settings_presets as api
    from app.api.settings_mcp import save_mcp_config
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    local_skill = ctx.skills_dir / "skill-local"
    local_skill.mkdir(parents=True)
    local_skill.joinpath("SKILL.md").write_text("---\nname: Skill A\ndescription: old\n---\nold\n", encoding="utf-8")
    save_agent_instances(
        [{"name": "Expert A", "description": "old role", "skills": [_skill_ref("Skill A", "skill-local")]}]
    )
    save_mcp_config([_mcp_row("Tool A")])
    api._mirror_session_presets_to_resources(
        [{"name": "Scene A", "agent_names": ["Expert A"], "host": {"name": "主持人", "skill_name": "Skill A", "skill_directory": "skill-local"}}]
    )

    source_skills = tmp_path / "source_skills"
    shared_skill = source_skills / "skill-shared-skill"
    shared_skill.mkdir(parents=True)
    shared_skill.joinpath("SKILL.md").write_text("---\nname: Skill A\ndescription: new\n---\nnew\n", encoding="utf-8")
    raw = build_scenario_bundle_zip_bytes(
        {"name": "Scene A", "agent_names": ["Expert A"], "host": {"name": "主持人", "skill_name": "Skill A", "skill_directory": "skill-shared-skill"}},
        [{"name": "Expert A", "description": "new role", "skills": [_skill_ref("Skill A", "skill-shared-skill")]}],
        [_mcp_row("Tool A")],
        source_skills,
        ["skill-shared-skill"],
    )

    try:
        preview = asyncio.run(api._import_scene_from_bundle_bytes(raw, dry_run=True))
        result = asyncio.run(api._import_scene_from_bundle_bytes(raw, dry_run=False))
        imported_scene = next(row for row in api._load_session_preset_rows_from_resource_files() if row["name"] == "Scene A")
    finally:
        reset_current_username(token)

    assert preview["preview"]["name_conflict_existing_names"] == ["Scene A"]
    assert "skill_names" not in preview["preview"]
    assert preview["preview"]["skill_display_names"] == {"skill-shared-skill": "Skill A"}
    assert result["summary"]["agent_imported_names"] == ["Expert A"]
    imported_skill = ctx.skills_dir / "skill-shared-skill"
    assert result["summary"]["skills_overwritten"] == []
    assert "old" in local_skill.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "new" in imported_skill.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert imported_scene["host"]["skill_directory"] == "skill-shared-skill"


def test_bundle_import_apis_do_not_accept_legacy_conflict_controls():
    from app.api.agents import import_agent_instance_bundle
    from app.api.settings_presets import import_session_preset_bundle
    from app.api.settings_skills import import_skill_zip

    for endpoint in [
        import_agent_instance_bundle,
        import_session_preset_bundle,
        import_skill_zip,
    ]:
        params = inspect.signature(endpoint).parameters
        for legacy_param in [
            "overwrite_experts",
            "overwrite_skills",
            "mcp_skip_existing",
            "name_conflict",
        ]:
            assert legacy_param not in params


def test_bundle_import_endpoints_reject_legacy_conflict_form_fields(monkeypatch, tmp_path: Path):
    from app.api import settings_skills as skill_api
    from app.core.expert_bundle import build_expert_bundle_zip_bytes
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username
    from app.main import app
    from fastapi.testclient import TestClient

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")

    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
    finally:
        reset_current_username(token)

    source_skills = tmp_path / "source_skills"
    skill_dir = source_skills / "skill-incoming"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text("---\nname: Incoming Skill\n---\nbody\n", encoding="utf-8")
    skill_zip = skill_api._build_skill_zip_bytes(skill_dir, [])
    expert_zip = build_expert_bundle_zip_bytes(
        {"name": "Imported Expert", "skills": [_skill_ref("Incoming Skill", "skill-incoming")]},
        [],
        source_skills,
        ["skill-incoming"],
    )
    scene_zip = build_scenario_bundle_zip_bytes(
        {"name": "Imported Scene", "agent_names": ["Imported Expert"], "host": {"name": "主持人"}},
        [{"name": "Imported Expert", "skills": [_skill_ref("Incoming Skill", "skill-incoming")]}],
        [],
        source_skills,
        ["skill-incoming"],
    )

    client = TestClient(app)
    cases = [
        ("/api/settings/skills/import-zip", skill_zip, {"name_conflict": "skip"}),
        ("/api/agents/import-bundle", expert_zip, {"dry_run": "true", "mcp_skip_existing": "true"}),
        ("/api/settings/session-presets/import-bundle", scene_zip, {"dry_run": "true", "overwrite_experts": "false"}),
    ]
    for endpoint, raw, data in cases:
        response = client.post(
            endpoint,
            data=data,
            files={"file": ("bundle.zip", raw, "application/zip")},
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 400, endpoint
        assert "旧导入策略字段已删除" in response.json()["detail"]


def test_bundle_import_api_sources_do_not_return_legacy_skip_fields():
    project_root = Path(__file__).resolve().parents[1]
    combined = "\n".join(
        (project_root / path).read_text(encoding="utf-8")
        for path in [
            "app/api/agents.py",
            "app/api/settings_presets.py",
            "app/api/settings_skills.py",
        ]
    )

    for legacy_field in [
        "skip_existing_directory_names",
        "would_skip_skills",
        "would_skip_tools",
        "skipped_by_name",
        "skills_skipped",
        "mcp_failed",
        "tools_failed",
    ]:
        assert legacy_field not in combined


def test_expert_bundle_preview_uses_skill_display_names(monkeypatch, tmp_path: Path):
    from app.core.expert_bundle import build_expert_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username
    from app.main import app

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")

    token = set_current_username("u1")
    try:
        ctx = get_current_user_context(default_fallback=False)
        assert ctx is not None
    finally:
        reset_current_username(token)

    source_skills = tmp_path / "source_skills"
    incoming_skill = source_skills / "skill-incoming"
    incoming_skill.mkdir(parents=True)
    incoming_skill.joinpath("SKILL.md").write_text("---\nname: Incoming Skill\n---\nbody\n", encoding="utf-8")
    raw = build_expert_bundle_zip_bytes(
        {"name": "Imported Expert", "skills": [_skill_ref("Incoming Skill", "skill-incoming")]},
        [],
        source_skills,
        ["skill-incoming"],
    )

    from fastapi.testclient import TestClient

    client = TestClient(app)
    response = client.post(
        "/api/agents/import-bundle",
        files={"file": ("expert.zip", raw, "application/zip")},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    preview = response.json()["data"]["bundle_preview"]
    assert "skill_names" not in preview
    assert preview["skill_display_names"] == {"skill-incoming": "Incoming Skill"}


def test_scene_bundle_import_overwrites_same_skill_directory_identity(monkeypatch, tmp_path: Path):
    from app.api import settings_presets as api
    from app.core.scenario_bundle import build_scenario_bundle_zip_bytes
    from app.core.user_context import get_current_user_context, reset_current_username, set_current_username

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    token = set_current_username("u1")
    ctx = get_current_user_context(default_fallback=False)
    assert ctx is not None
    existing_skill = ctx.skills_dir / "skill-shared-skill"
    existing_skill.mkdir(parents=True)
    existing_skill.joinpath("SKILL.md").write_text("---\nname: Old Skill\ndescription: old\n---\nold\n", encoding="utf-8")

    source_skills = tmp_path / "source_skills"
    incoming_skill = source_skills / "skill-shared-skill"
    incoming_skill.mkdir(parents=True)
    incoming_skill.joinpath("SKILL.md").write_text("---\nname: New Skill\ndescription: new\n---\nnew\n", encoding="utf-8")
    raw = build_scenario_bundle_zip_bytes(
        {"name": "New Scene", "agent_names": ["New Expert"], "host": {"name": "主持人", "skill_name": "New Skill", "skill_directory": "skill-shared-skill"}},
        [{"name": "New Expert", "skills": [_skill_ref("New Skill", "skill-shared-skill")]}],
        [],
        source_skills,
        ["skill-shared-skill"],
    )

    try:
        result = asyncio.run(api._import_scene_from_bundle_bytes(raw, dry_run=False))
    finally:
        reset_current_username(token)

    imported = result["summary"]["skills_imported"]
    assert len(imported) == 1
    assert imported[0] == "skill-shared-skill"
    assert result["summary"]["skills_overwritten"] == ["skill-shared-skill"]
    text = (ctx.skills_dir / "skill-shared-skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "new" in text
    assert "old" not in text
