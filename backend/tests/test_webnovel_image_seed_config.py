from __future__ import annotations

import json
from pathlib import Path

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
    agent_path = USER_RESOURCE_ROOT / "resources" / "agents" / "agent-8d0d15ba" / "agent.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8"))

    skill_ids = [str(x).strip() for x in agent.get("skill_ids") or [] if str(x).strip()]
    assert skill_ids

    skill_root = USER_RESOURCE_ROOT / "resources" / "skills"
    missing = [sid for sid in skill_ids if not (skill_root / sid / "SKILL.md").is_file()]
    assert missing == []

    skills = [_frontmatter(skill_root / sid / "SKILL.md") for sid in skill_ids]
    image_skill = next((fm for fm in skills if fm.get("name") == "网文配图v1.0"), None)
    assert image_skill is not None
    assert image_skill.get("allowed-tools", {}).get("mcp") == ["image-generation"]
