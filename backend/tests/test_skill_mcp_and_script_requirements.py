"""技能 allowed-tools / tool 解析与校验。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.api.settings_skill_frontmatter import (
    ALLOWED_TOOLS_FM_KEY,
    normalize_allowed_tools_payload,
    normalized_allowed_tools_dict,
    sanitize_skill_frontmatter_for_write,
)
from app.api.settings_skill_store import get_mcp_servers_for_skill, write_skill_file


def test_normalized_allowed_tools_reads_mcp_http_api_and_python_only():
    fm = {
        ALLOWED_TOOLS_FM_KEY: {
            "mcp": ["Exa", "Exa"],
            "http_api": ["Weather"],
            "python": ["requests>=2", "requests>=2", " pandas "],
        },
        "unused": "drop",
    }
    out = normalized_allowed_tools_dict(fm)
    assert out == {"mcp": ["Exa"], "http_api": ["Weather"], "python": ["requests>=2", "pandas"]}


def test_normalized_allowed_tools_rejects_python_string_shape():
    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": [], "http_api": [], "python": "requests>=2\n\npandas\n"}}

    out = normalized_allowed_tools_dict(fm)

    assert out["python"] == []


def test_normalize_allowed_tools_payload_accepts_http_api_alias():
    out = normalize_allowed_tools_payload({"mcp": ["Exa"], "http-api": ["Weather"], "python": ["requests>=2", ""]})
    assert out == {"mcp": ["Exa"], "http_api": ["Weather"], "python": ["requests>=2"]}


def test_normalize_allowed_tools_payload_rejects_python_string_shape():
    out = normalize_allowed_tools_payload({"mcp": ["Exa"], "http-api": ["Weather"], "python": "requests>=2\npandas"})
    assert out == {"mcp": ["Exa"], "http_api": ["Weather"], "python": []}


def test_sanitize_skill_frontmatter_keeps_only_contract_fields():
    fm = {
        "name": "Skill A",
        "description": "desc",
        ALLOWED_TOOLS_FM_KEY: {"mcp": ["Exa"], "http-api": ["Weather"], "python": ["pandas", "requests"]},
        "extra": "nope",
    }
    sanitize_skill_frontmatter_for_write(fm)
    assert fm == {
        "name": "Skill A",
        "description": "desc",
        ALLOWED_TOOLS_FM_KEY: {"mcp": ["Exa"], "http_api": ["Weather"], "python": ["pandas", "requests"]},
    }


def test_write_skill_file_emits_python_dependencies_as_yaml_list(tmp_path: Path):
    skill_dir = tmp_path / "skill"
    skill_dir.mkdir()

    write_skill_file(
        skill_dir,
        {
            "name": "Skill A",
            "description": "desc",
            ALLOWED_TOOLS_FM_KEY: {"mcp": [], "http_api": [], "python": ["requests>=2", "pandas"]},
        },
        "body\n",
    )

    written = skill_dir.joinpath("SKILL.md").read_text(encoding="utf-8")
    assert "python:\n" in written
    assert "  - requests>=2\n" in written
    assert "  - pandas\n" in written
    assert "python: 'requests" not in written


def test_get_mcp_servers_reads_mcp_and_http_api_from_skill_md(tmp_path: Path, monkeypatch):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: T\n{ALLOWED_TOOLS_FM_KEY}:\n  mcp: [Exa]\n  http_api: [Weather]\n  python: []\n---\nbody\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.api.settings_skill_store._get_skills_dir", lambda: skills_root)
    monkeypatch.setattr("app.api.settings_skill_store.get_builtin_skills_dir", lambda: tmp_path / "none")

    with patch(
        "app.api.settings_skill_store.load_mcp_config",
        return_value=[{"name": "Exa", "type": "mcp"}, {"name": "Weather", "type": "http_api"}],
    ):
        assert get_mcp_servers_for_skill("my-skill") == ["Exa", "Weather"]


def test_get_mcp_servers_rejects_legacy_reference_label_ids(tmp_path: Path, monkeypatch):
    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "webv10"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: Web\n"
        "allowed-tools:\n"
        "  mcp:\n"
        "    - mcp-fb19dbb1\n"
        "reference-labels:\n"
        "  mcp:\n"
        "    - id: mcp-fb19dbb1\n"
        "      name: Exa 搜索\n"
        "---\nbody\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("app.api.settings_skill_store._get_skills_dir", lambda: skills_root)
    monkeypatch.setattr("app.api.settings_skill_store.get_builtin_skills_dir", lambda: tmp_path / "none")

    with patch("app.api.settings_skill_store.load_mcp_config", return_value=[{"name": "Exa 搜索", "type": "mcp"}]):
        assert get_mcp_servers_for_skill("webv10") == []


def test_mcp_rows_for_bundle_refs_reads_allowed_tool_names():
    from app.core.settings_bundle_import import mcp_refs_from_skill_frontmatter, mcp_rows_for_bundle_refs

    fm = {ALLOWED_TOOLS_FM_KEY: {"mcp": ["Exa"], "http_api": ["Weather"], "python": []}}
    refs = mcp_refs_from_skill_frontmatter(fm)
    assert refs == [{"name": "Exa"}, {"name": "Weather"}]

    rows = mcp_rows_for_bundle_refs(
        refs,
        [{"name": "Exa", "type": "mcp"}, {"name": "Weather", "type": "http_api"}],
    )
    assert rows == [
        {"name": "Exa", "type": "mcp", "description": "", "server_config": ""},
        {
            "name": "Weather",
            "type": "http_api",
            "description": "",
            "config": {
                "type": "GET",
                "base_url": "",
                "path": "",
                "header": {},
                "query": {},
                "body": "",
                "timeout_seconds": 60,
            },
        },
    ]


def test_mcp_refs_from_skill_frontmatter_ignores_legacy_label_without_name():
    from app.core.settings_bundle_import import mcp_refs_from_skill_frontmatter

    fm = {
        ALLOWED_TOOLS_FM_KEY: {
            "mcp": [{"label": "Exa 搜索"}, {"name": "Exa"}],
            "http_api": [{"label": "Weather API"}],
            "python": [],
        }
    }

    assert mcp_refs_from_skill_frontmatter(fm) == [{"name": "Exa"}]


def test_collect_tool_names_from_skill_dirs_reads_allowed_tools(tmp_path: Path):
    from app.core.settings_bundle_import import collect_tool_names_from_skill_dirs

    skills_root = tmp_path / "skills"
    skill_dir = skills_root / "skill-a"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "---\n"
        "name: Skill A\n"
        "allowed-tools:\n"
        "  mcp:\n"
        "    - Exa\n"
        "  http_api:\n"
        "    - Weather\n"
        "  python: []\n"
        "---\n"
        "body\n",
        encoding="utf-8",
    )

    assert collect_tool_names_from_skill_dirs(skills_root, ["skill-a", "missing"]) == ["Exa", "Weather"]
