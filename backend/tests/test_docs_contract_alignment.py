from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_host_skill_docs_use_current_next_action_contract():
    """Keep Skill authoring docs aligned with the current host scheduler contract."""
    docs = sorted((PROJECT_ROOT / "docs" / "skills").glob("**/*.md"))

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "speaker_task" not in text, path
