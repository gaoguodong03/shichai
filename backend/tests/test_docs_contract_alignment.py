import re
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


def test_architecture_docs_do_not_advertise_session_index_contract():
    """Architecture docs must not reintroduce sessions/index.json after the contract removed it."""
    docs = [
        PROJECT_ROOT / "docs" / "architecture" / "user-resource-store" / "README.md",
        PROJECT_ROOT / "docs" / "architecture" / "user-resource-store" / "storage-standard.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sessions/\s*\n\s*index\.json", text), path


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


def test_group_chat_archive_has_independent_module_boundary():
    """Archive segmentation is presentation logic, not session state storage."""
    archive_module = PROJECT_ROOT / "backend" / "app" / "api" / "group_chat_archive.py"
    state_module = PROJECT_ROOT / "backend" / "app" / "api" / "group_chat_state.py"

    assert archive_module.exists()
    archive_text = archive_module.read_text(encoding="utf-8")
    state_text = state_module.read_text(encoding="utf-8")

    assert "def build_archive_segments" in archive_text
    assert "def build_archive_segments" not in state_text
    assert len(state_text.splitlines()) < 600


def test_skill_script_sandbox_request_has_independent_module_boundary():
    """Sandbox command construction belongs outside the script execution entrypoint."""
    sandbox_module = PROJECT_ROOT / "backend" / "app" / "tools" / "skill_script_sandbox_request.py"
    runner_module = PROJECT_ROOT / "backend" / "app" / "tools" / "run_skill_script.py"

    assert sandbox_module.exists()
    sandbox_text = sandbox_module.read_text(encoding="utf-8")
    runner_text = runner_module.read_text(encoding="utf-8")

    for name in [
        "def build_script_command",
        "def build_sandbox_exec_request",
        "def inline_shell_env",
        "def resolve_script_timeout_sec",
    ]:
        assert name in sandbox_text
    for old_private_definition in [
        "def _build_script_command",
        "def _build_sandbox_script_command",
        "def _build_sandbox_exec_request",
        "def _inline_shell_env",
        "def _resolve_script_timeout_sec",
    ]:
        assert old_private_definition not in runner_text
    assert len(runner_text.splitlines()) < 600


def test_simple_agent_tool_flow_has_independent_module_boundary():
    """Tool-output flow predicates belong outside the SimpleAgent loop file."""
    flow_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_tool_flow.py"
    agent_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent.py"

    assert flow_module.exists()
    flow_text = flow_module.read_text(encoding="utf-8")
    agent_text = agent_module.read_text(encoding="utf-8")

    for name in [
        "def iter_run_skill_raw_output_payloads",
        "def run_skill_outputs_request_agent_turn_continue",
        "def remember_successful_workspace_writes",
        "def all_workspace_write_calls_already_succeeded",
        "def post_tool_synthesis_should_use_bound_client",
    ]:
        assert name in flow_text
    for old_private_definition in [
        "def _iter_run_skill_raw_output_payloads",
        "def _run_skill_outputs_request_agent_turn_continue",
        "def _remember_successful_workspace_writes",
        "def _all_workspace_write_calls_already_succeeded",
        "def _post_tool_synthesis_should_use_bound_client",
    ]:
        assert old_private_definition not in agent_text
