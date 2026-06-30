from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml


USER_RESOURCE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "users"
    / "user-23a7ad6fe421441793838ff8fdff6eb1"
)


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---")
    return yaml.safe_load(text.split("---", 2)[1]) or {}


def test_webnovel_image_expert_references_loadable_image_generation_skill():
    agent_path = USER_RESOURCE_ROOT / "resources" / "agents" / "图片生成专家v1.1" / "agent.json"
    if not agent_path.is_file():
        pytest.skip(f"webnovel image agent fixture not present: {agent_path}")
    agent = json.loads(agent_path.read_text(encoding="utf-8"))

    skill_directories = [
        str(x.get("directory_name") or "").strip()
        for x in agent.get("skills") or []
        if isinstance(x, dict) and str(x.get("directory_name") or "").strip()
    ]
    assert skill_directories

    skill_root = USER_RESOURCE_ROOT / "resources" / "skills"
    missing = [directory for directory in skill_directories if not (skill_root / directory / "SKILL.md").is_file()]
    if missing:
        pytest.skip(f"webnovel skill fixtures not present: {missing}")

    skills = [_frontmatter(skill_root / directory / "SKILL.md") for directory in skill_directories]
    image_skill = next((fm for fm in skills if fm.get("name") == "网文配图v1.0"), None)
    assert image_skill is not None
    assert image_skill.get("allowed-tools", {}).get("mcp") == ["image-generation"]
