"""技能 allowed-tools / MCP 解析与校验。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api import settings as settings_mod
from app.api.settings import (
    ALLOWED_TOOLS_FM_KEY,
    _mcp_ids_from_frontmatter,
    _normalized_allowed_tools_dict,
    get_mcp_servers_for_skill,
)


def test_mcp_ids_from_allowed_tools():
    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["exa", "exa"], "python": "x"}}
    assert _mcp_ids_from_frontmatter(fm) == ["exa"]


def test_mcp_ids_legacy_mcp_server_ids():
    fm = {"mcp_server_ids": ["a", "b", "a"]}
    assert _mcp_ids_from_frontmatter(fm) == ["a", "b"]


def test_mcp_ids_allowed_tools_wins_over_legacy():
    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["x"]}, "mcp_server_ids": ["y"]}
    assert _mcp_ids_from_frontmatter(fm) == ["x"]


def test_normalized_allowed_tools_from_legacy_only():
    fm = {"mcp_server_ids": ["file-reader"]}
    out = _normalized_allowed_tools_dict(fm)
    assert out["mcp"] == ["file-reader"]
    assert out["python"] == ""


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

    monkeypatch.setattr(settings_mod, "_get_skills_dir", fake_get_skills_dir)
    monkeypatch.setattr(settings_mod, "get_builtin_skills_dir", lambda: tmp_path / "none")

    with patch(
        "app.api.settings.load_mcp_config",
        return_value=[{"id": "exa", "enabled": True}, {"id": "other", "enabled": True}],
    ):
        assert get_mcp_servers_for_skill("my-skill") == ["exa"]


def test_validate_skill_mcp_server_ids_unknown():
    from app.api.settings import _validate_skill_mcp_server_ids

    with patch("app.api.settings.load_mcp_config", return_value=[{"id": "ok", "enabled": True}]):
        assert _validate_skill_mcp_server_ids(["ok"]) == ["ok"]
        with pytest.raises(HTTPException) as ei:
            _validate_skill_mcp_server_ids(["nope"])
        assert ei.value.status_code == 400
