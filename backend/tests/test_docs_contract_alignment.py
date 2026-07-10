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


def test_backend_runtime_does_not_keep_session_index_contract():
    """Runtime code must not keep the removed sessions/index.json contract alive."""
    runtime_files = [
        PROJECT_ROOT / "backend" / "app" / "api" / "group_chat_state.py",
        PROJECT_ROOT / "backend" / "app" / "api" / "sessions.py",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    assert "SESSION_INDEX_FILE" not in combined
    assert "sessions/index.json" not in combined


def test_skill_script_manifest_has_independent_module_boundary():
    """Script manifest parsing belongs outside the sandbox execution entrypoint."""
    manifest_module = PROJECT_ROOT / "backend" / "app" / "tools" / "skill_script_manifest.py"
    runner_module = PROJECT_ROOT / "backend" / "app" / "tools" / "run_skill_script.py"

    assert manifest_module.exists()
    manifest_text = manifest_module.read_text(encoding="utf-8")
    runner_text = runner_module.read_text(encoding="utf-8")

    for name in [
        "def normalize_skill_script_path",
        "def load_skill_script_manifest",
        "def manifest_args_to_cli_argv",
        "def input_schema_from_manifest",
    ]:
        assert name in manifest_text
    for old_private_definition in [
        "def _normalize_skill_script_path",
        "def _load_manifest",
        "def _manifest_args_to_cli_argv",
        "def _input_schema_from_manifest",
    ]:
        assert old_private_definition not in runner_text
