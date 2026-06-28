"""技能 allowed-tools / MCP 解析与校验。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api import settings_skills as settings_skills_mod
from app.api.settings_skill_frontmatter import (
    ALLOWED_TOOLS_FM_KEY,
    AUTO_TOOLS_FM_KEY,
    mcp_ids_from_frontmatter,
    normalize_allowed_tools_payload,
    normalized_allowed_tools_dict,
)
from app.api.settings_skill_store import get_mcp_servers_for_skill
from app.skills.loader import SkillsLoader


def test_mcp_ids_from_allowed_tools():
    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["exa", "exa"], "python": "x"}}
    assert mcp_ids_from_frontmatter(fm) == ["exa"]


def test_mcp_ids_legacy_mcp_server_ids():
    fm = {"mcp_server_ids": ["a", "b", "a"]}
    assert mcp_ids_from_frontmatter(fm) == ["a", "b"]


def test_mcp_ids_allowed_tools_wins_over_legacy():
    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["x"]}, "mcp_server_ids": ["y"]}
    assert mcp_ids_from_frontmatter(fm) == ["x"]


def test_mcp_ids_auto_tools_wins_over_allowed_tools():
    fm = {
        AUTO_TOOLS_FM_KEY: {"mcp": ["auto"]},
        ALLOWED_TOOLS_FM_KEY: {"mcp": ["allowed"]},
    }
    assert mcp_ids_from_frontmatter(fm) == ["auto"]


def test_normalized_allowed_tools_from_legacy_only():
    fm = {"mcp_server_ids": ["file-reader"]}
    out = normalized_allowed_tools_dict(fm)
    assert out["mcp"] == ["file-reader"]
    assert out["python"] == ""


def test_normalized_allowed_tools_writes_mcp_names(monkeypatch):
    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["mcp-local"], "python": ""}}

    monkeypatch.setattr(
        "app.api.settings_skill_frontmatter.load_mcp_config",
        lambda: [{"id": "mcp-local", "name": "Exa 搜索"}],
    )

    out = normalized_allowed_tools_dict(fm)
    assert out["mcp"] == ["Exa 搜索"]
    assert out["mcp_refs"] == [{"id": "Exa 搜索", "name": "Exa 搜索"}]


def test_normalize_allowed_tools_payload_writes_mcp_names(monkeypatch):
    monkeypatch.setattr(
        "app.api.settings_skill_frontmatter.load_mcp_config",
        lambda: [{"id": "mcp-local", "name": "Linkup抓取网页"}],
    )

    out = normalize_allowed_tools_payload({"mcp": ["mcp-local"], "python": ""})
    assert out["mcp"] == ["Linkup抓取网页"]
    assert out["mcp_refs"] == [{"id": "Linkup抓取网页", "name": "Linkup抓取网页"}]


def test_get_mcp_servers_reads_skill_md(tmp_path: Path, monkeypatch):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: T\n{ALLOWED_TOOLS_FM_KEY}:\n  mcp: [exa]\n  python: ''\n---\nbody\n",
        encoding="utf-8",
    )

    def fake_get_skills_dir():
        return skills_root

    monkeypatch.setattr("app.api.settings_skill_store._get_skills_dir", fake_get_skills_dir)
    monkeypatch.setattr("app.api.settings_skill_store.get_builtin_skills_dir", lambda: tmp_path / "none")

    with patch(
        "app.api.settings_skill_store.load_mcp_config",
        return_value=[{"id": "exa", "enabled": True}, {"id": "other", "enabled": True}],
    ):
        assert get_mcp_servers_for_skill("my-skill") == ["exa"]


def test_get_mcp_servers_resolves_by_name(tmp_path: Path, monkeypatch):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: T\n{ALLOWED_TOOLS_FM_KEY}:\n  mcp: [exa]\n  python: ''\n"
        "reference-labels:\n  mcp:\n    - id: exa\n      name: Exa\n---\nbody\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.api.settings_skill_store._get_skills_dir", lambda: skills_root)
    monkeypatch.setattr("app.api.settings_skill_store.get_builtin_skills_dir", lambda: tmp_path / "none")

    with patch(
        "app.api.settings_skill_store.load_mcp_config",
        return_value=[{"id": "mcp-local", "name": "Exa", "enabled": True}],
    ):
        assert get_mcp_servers_for_skill("my-skill") == ["mcp-local"]


def test_validate_skill_mcp_server_ids_unknown():
    from app.api.settings_skill_store import validate_skill_mcp_server_ids

    with patch("app.api.settings_skill_store.load_mcp_config", return_value=[{"id": "ok", "enabled": True}]):
        assert validate_skill_mcp_server_ids(["ok"]) == ["ok"]
        with pytest.raises(HTTPException) as ei:
            validate_skill_mcp_server_ids(["nope"])
        assert ei.value.status_code == 400


def test_validate_skill_mcp_server_ids_resolves_by_name():
    from app.api.settings_skill_store import validate_skill_mcp_server_ids

    with patch(
        "app.api.settings_skill_store.load_mcp_config",
        return_value=[{"id": "mcp-local", "name": "Exa", "enabled": True}],
    ):
        assert validate_skill_mcp_server_ids(["exa"], [{"id": "exa", "name": "Exa"}]) == ["mcp-local"]


def test_mcp_rows_for_bundle_refs_reads_allowed_tool_names():
    from app.core.settings_bundle_import import mcp_refs_from_skill_frontmatter, mcp_rows_for_bundle_refs

    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["Exa 搜索"], "python": ""}}
    refs = mcp_refs_from_skill_frontmatter(fm)
    assert refs == [{"id": "Exa 搜索", "name": ""}]

    rows = mcp_rows_for_bundle_refs(
        refs,
        [{"id": "mcp-local", "name": "Exa 搜索", "transport": {"type": "http"}}],
    )
    assert rows == [{"id": "Exa 搜索", "name": "Exa 搜索", "transport": {"type": "http"}}]


def test_python_requirements_from_allowed_and_auto_tools(tmp_path: Path):
    from app.api.settings_skills import _python_requirements_from_skill_dir

    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: T\n"
        "auto-tools:\n"
        "  python:\n"
        "    - requests>=2\n"
        "    - pandas==2.2.0\n"
        "---\nbody\n",
        encoding="utf-8",
    )
    assert _python_requirements_from_skill_dir(skill_dir) == ["requests>=2", "pandas==2.2.0"]


def test_merge_sandbox_requirements_lines_dedupes_by_package(tmp_path: Path, monkeypatch):
    from app.api.settings_skills import _merge_sandbox_requirements_lines

    req_path = tmp_path / "config" / "sandbox" / "requirements.txt"
    req_path.parent.mkdir(parents=True)
    req_path.write_text("requests==2.31.0\n", encoding="utf-8")
    monkeypatch.setattr(settings_skills_mod, "_get_sandbox_requirements_path", lambda: req_path)

    added, merged = _merge_sandbox_requirements_lines(["requests>=2", "pandas==2.2.0"])
    assert added == ["pandas==2.2.0"]
    assert merged == "requests==2.31.0\npandas==2.2.0\n"
    assert req_path.read_text(encoding="utf-8") == merged


def test_collect_mcp_ids_from_skill_dirs_reads_auto_tools(tmp_path: Path):
    from app.core.settings_bundle_import import collect_mcp_ids_from_skill_dirs

    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "skill-a"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\n"
        "name: Skill A\n"
        "auto-tools:\n"
        "  mcp:\n"
        "    - tool-a\n"
        "    - tool-a\n"
        "    - id: tool-b\n"
        "      name: Tool B\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    assert collect_mcp_ids_from_skill_dirs(skills_root, ["skill-a", "missing"]) == ["tool-a", "tool-b"]


def test_skill_import_zip_merges_root_mcp_servers(monkeypatch, tmp_path: Path):
    import io
    import json
    import zipfile

    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("SHUTONG_USER_DATA_ROOT", str(tmp_path / "users"))
    monkeypatch.setattr("app.core.security.decode_access_token", lambda _t: "u1")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SKILL.md",
            "---\n"
            "name: Skill A\n"
            "auto-tools:\n"
            "  mcp:\n"
            "    - tool-a\n"
            "---\n"
            "body\n",
        )
        zf.writestr("mcp_servers.json", json.dumps([{"id": "tool-a", "name": "Tool A", "enabled": True}]))

    client = TestClient(app)
    resp = client.post(
        "/api/settings/skills/import-zip",
        files={"file": ("skill-a.zip", buf.getvalue(), "application/zip")},
        headers={"Authorization": "Bearer test-token"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["mcp_added"] == 1

    mcp_path = tmp_path / "users" / "u1" / "config" / "mcp_servers.json"
    imported_mcp_id = json.loads(mcp_path.read_text(encoding="utf-8"))[0]["id"]
    assert imported_mcp_id.startswith("mcp-")
    skill_text = (
        tmp_path
        / "users"
        / "u1"
        / "resources"
        / "skills"
        / data["id"]
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "Tool A" in skill_text
    assert imported_mcp_id not in skill_text
    assert not (tmp_path / "users" / "u1" / "skills" / data["id"] / "mcp_servers.json").exists()


def test_skills_loader_reports_contract_diagnostics(tmp_path: Path):
    skills_root = tmp_path / "skills"
    valid_dir = skills_root / "valid-skill"
    missing_dir = skills_root / "missing-skill-md"
    invalid_dir = skills_root / "invalid-frontmatter"
    valid_dir.mkdir(parents=True)
    missing_dir.mkdir()
    invalid_dir.mkdir()
    (valid_dir / "SKILL.md").write_text(
        "---\nname: Valid\ndescription: ok\n---\nbody\n",
        encoding="utf-8",
    )
    (invalid_dir / "SKILL.md").write_text(
        "---\nname: [unterminated\n---\nbody\n",
        encoding="utf-8",
    )

    loader = SkillsLoader(str(skills_root))
    assert sorted(loader.load_all_skills()) == ["valid-skill"]

    diagnostics = loader.get_diagnostics()
    by_id = {item["skill_id"]: item for item in diagnostics}
    assert by_id["missing-skill-md"]["code"] == "missing_skill_md"
    assert "SKILL.md" in by_id["missing-skill-md"]["message"]
    assert by_id["invalid-frontmatter"]["code"] == "invalid_frontmatter"
    assert "frontmatter" in by_id["invalid-frontmatter"]["message"]
