from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_host_skill_docs_use_current_next_action_contract():
    """Keep Skill authoring docs aligned with the current host scheduler contract."""
    docs = sorted((PROJECT_ROOT / "docs" / "skills").glob("**/*.md"))

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert "speaker_task" not in text, path


def test_backend_readme_uses_current_runtime_contract_fields():
    """Backend README must not advertise legacy runtime or Skill stdout fields."""
    text = (PROJECT_ROOT / "backend" / "README.md").read_text(encoding="utf-8")

    for legacy in [
        "skill_session_owner_name",
        "skill_session_skill",
        "result_code",
        "`message`、`artifacts`",
        "leader_agent_name",
        "历史场景包和旧磁盘配置只在导入/读取边界做兼容转换",
    ]:
        assert legacy not in text
