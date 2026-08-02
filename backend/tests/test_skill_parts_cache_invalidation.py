"""SkillsLoader 缓存必须能感知 references/assets/other 附加文件变化。"""
from __future__ import annotations

from pathlib import Path

from app.skills.loader import (
    SkillsLoader,
    _skills_tree_mtime,
    get_skills_loader_for_user,
    invalidate_skills_cache_for_user,
)


def _write_skill(root: Path, directory_name: str) -> None:
    d = root / directory_name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        "---\nname: 测试\ndescription: 测试技能\n---\n读附加文件。",
        encoding="utf-8",
    )


def test_skills_tree_mtime_tracks_part_files_without_skil_md(tmp_path: Path) -> None:
    _write_skill(tmp_path, "skill-a")
    mtime_before = _skills_tree_mtime(tmp_path)

    # 新增 references/guide.md，不改 SKILL.md
    refs = tmp_path / "skill-a" / "references"
    refs.mkdir()
    (refs / "guide.md").write_text("# guide", encoding="utf-8")

    assert _skills_tree_mtime(tmp_path) > mtime_before


def test_loader_discovers_references_assets_and_other(tmp_path: Path) -> None:
    _write_skill(tmp_path, "skill-a")
    refs = tmp_path / "skill-a" / "references"
    refs.mkdir()
    (refs / "guide.md").write_text("# guide", encoding="utf-8")
    assets = tmp_path / "skill-a" / "assets"
    assets.mkdir()
    (assets / "template.md").write_text("# template", encoding="utf-8")
    other = tmp_path / "skill-a" / "other"
    other.mkdir()
    (other / "notes.md").write_text("# notes", encoding="utf-8")

    loader = SkillsLoader(str(tmp_path))
    skills = loader.load_all_skills()
    skill = skills["skill-a"]
    assert skill.references == ["references/guide.md"]
    assert skill.assets == ["assets/template.md"]
    assert skill.other_files == ["other/notes.md"]

    full = loader.get_skill_full_content("skill-a") or ""
    assert "references/guide.md" in full
    assert "assets/template.md" in full
    assert "other/notes.md" in full


def test_user_loader_cache_refreshes_when_part_file_added(tmp_path: Path) -> None:
    user_id = "cache-user"
    _write_skill(tmp_path, "skill-a")
    invalidate_skills_cache_for_user(user_id)

    loader1 = get_skills_loader_for_user(user_id, tmp_path)
    assert loader1.skills["skill-a"].references == []

    refs = tmp_path / "skill-a" / "references"
    refs.mkdir()
    (refs / "guide.md").write_text("# guide", encoding="utf-8")

    loader2 = get_skills_loader_for_user(user_id, tmp_path)
    assert loader2.skills["skill-a"].references == ["references/guide.md"]
