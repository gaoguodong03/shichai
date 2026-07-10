import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_formal_docs_tree_excludes_legacy_planning_directories():
    """Old planning trees must not stay under docs as searchable formal documentation."""
    for relative in [
        "docs/superpowers",
        "docs/project",
    ]:
        root = PROJECT_ROOT / relative
        files = list(root.rglob("*")) if root.exists() else []
        assert not any(path.is_file() for path in files), relative


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


def test_simple_agent_tool_summary_helpers_are_not_named_as_fallbacks():
    """Tool-result summary paths are product behavior, not legacy fallback branches."""
    runtime_files = [
        PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_tool_errors.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_finalization.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    for forbidden in [
        "_final_response_or_tool_fallback",
        "_script_dependency_fallback_summary",
    ]:
        assert forbidden not in combined


def test_simple_agent_tool_summary_has_independent_module_boundary():
    """Tool-result finalization belongs outside error handling and SimpleAgent loops."""
    summary_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_tool_summary.py"
    error_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_tool_errors.py"
    agent_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent.py"

    assert summary_module.exists()
    summary_text = summary_module.read_text(encoding="utf-8")
    error_text = error_module.read_text(encoding="utf-8")
    agent_text = agent_module.read_text(encoding="utf-8")

    assert "def _final_response_or_tool_summary" in summary_text
    assert "def _final_response_or_tool_summary" not in error_text
    assert "from app.agent.simple_agent_tool_summary import _final_response_or_tool_summary" in agent_text


def test_architecture_docs_do_not_advertise_session_index_contract():
    """Architecture docs must not reintroduce sessions/index.json after the contract removed it."""
    docs = [
        PROJECT_ROOT / "docs" / "architecture" / "user-resource-store" / "README.md",
        PROJECT_ROOT / "docs" / "architecture" / "user-resource-store" / "storage-standard.md",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sessions/\s*\n\s*index\.json", text), path


def test_data_structure_contract_does_not_advertise_session_index_contract():
    """The field source-of-truth doc must not show sessions/index.json as current storage."""
    text = (PROJECT_ROOT / "docs" / "contracts" / "data-structure-and-field-logic.md").read_text(encoding="utf-8")

    assert not re.search(r"sessions/\s*\n\s*index\.json", text)


def test_user_resource_storage_docs_use_name_based_resource_index_examples():
    """Resource storage docs must not show id-based resource index rows."""
    text = (PROJECT_ROOT / "docs" / "architecture" / "user-resource-store" / "storage-standard.md").read_text(encoding="utf-8")

    assert '"id": "scenario-' not in text
    assert '"resource_key"' not in text
    assert '"name": "编写PPT"' in text


def test_design_docs_do_not_reference_removed_host_config_module():
    """Formal design docs must point to current host profile modules."""
    text = (PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md").read_text(encoding="utf-8")

    assert "backend/app/core/host_config.py" not in text
    assert "backend/app/api/settings_app.py" in text
    assert "backend/app/core/host_profile_contract.py" in text


def test_session_api_docs_do_not_advertise_host_skill_display_snapshot():
    """Session host snapshots use the runtime contract, not scenario display fields."""
    text = (PROJECT_ROOT / "docs" / "design" / "interface-document.md").read_text(encoding="utf-8")
    section = text.split("### 5.2 新建会话", 1)[1].split("### 5.3 会话详情", 1)[0]

    assert "host.skill_directory" in section
    assert "host.skill_name" not in section
    assert '"skill_name"' not in section


def test_chat_once_docs_only_advertise_current_aggregated_event_payloads():
    """Non-stream chat docs must not reintroduce legacy response flags."""
    text = (PROJECT_ROOT / "docs" / "design" / "interface-document.md").read_text(encoding="utf-8")
    section = text.split("### 5.7 非流式对话", 1)[1].split("### 5.8 停止会话回复", 1)[0]

    for field in [
        '"interrupted"',
        '"contents"',
        '"content"',
        '"meta"',
        '"phase"',
    ]:
        assert field not in section

    for field in [
        '"route"',
        '"progress"',
        '"messages"',
        '"message"',
        '"end"',
        '"error"',
    ]:
        assert field in section


def test_chat_once_runtime_is_not_named_as_fallback():
    """The non-stream chat endpoint is a formal aggregation path, not fallback logic."""
    text = (PROJECT_ROOT / "backend" / "app" / "api" / "sessions.py").read_text(encoding="utf-8")
    section = text.split("async def session_chat_once", 1)[1].split("\n\n@router.", 1)[0]

    assert "兜底" not in section
    assert "fallback" not in section


def test_runtime_docs_do_not_route_from_message_text():
    """Runtime routing docs must not reintroduce message-text control channels."""
    paths = [
        PROJECT_ROOT / "docs" / "contracts" / "runtime-interface-contract.md",
        PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for forbidden in [
            "用户要求结束 Skill 会话",
            "用户未要求主持人接管",
            "主持人接管意图",
            "请主持人接管",
            "换专家",
            "结束当前技能",
        ]:
            assert forbidden not in text, path


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


def test_scene_bundle_import_planning_has_core_module_boundary():
    """Scene bundle import planning belongs in core, not in the scene API route."""
    api_text = (PROJECT_ROOT / "backend" / "app" / "api" / "settings_presets.py").read_text(encoding="utf-8")
    module_text = (PROJECT_ROOT / "backend" / "app" / "core" / "settings_bundle_import.py").read_text(encoding="utf-8")

    for expected in [
        "def agent_name_identity_import_plan",
        "def agent_name_conflicts",
        "def remap_scene_references",
        "def remap_agent_skill_references",
        "def prepare_scene_import_by_name_identity",
    ]:
        assert expected in module_text

    for forbidden in [
        "def _agent_name_identity_import_plan",
        "def _agent_name_conflicts",
        "def _remap_scene_references",
        "def _remap_agent_skill_references",
        "def _prepare_import_scene_by_name_identity",
    ]:
        assert forbidden not in api_text


def test_skill_bundle_import_reference_rewrites_have_core_module_boundary():
    """Skill bundle tool reference remapping belongs in core, not API routes."""
    api_text = "\n".join(
        [
            (PROJECT_ROOT / "backend" / "app" / "api" / "settings_skills.py").read_text(encoding="utf-8"),
            (PROJECT_ROOT / "backend" / "app" / "api" / "settings_presets.py").read_text(encoding="utf-8"),
        ]
    )
    module_text = (PROJECT_ROOT / "backend" / "app" / "core" / "settings_bundle_import.py").read_text(encoding="utf-8")

    assert "def mcp_name_map_for_import" in module_text
    assert "def remap_frontmatter_mcp_refs" in module_text
    assert "def _mcp_name_map_for_import" not in api_text
    assert "def _remap_frontmatter_mcp_refs" not in api_text
    assert "_mcp_name_map_for_import(" not in api_text
    assert "_remap_frontmatter_mcp_refs(" not in api_text


def test_mcp_bundle_packaging_has_core_module_boundary():
    """MCP bundle ZIP packaging and parsing belongs in core, not API routes."""
    api_text = (PROJECT_ROOT / "backend" / "app" / "api" / "settings_mcp.py").read_text(encoding="utf-8")
    module_text = (PROJECT_ROOT / "backend" / "app" / "core" / "settings_bundle_import.py").read_text(encoding="utf-8")

    assert "def build_single_mcp_bundle_zip_bytes" in module_text
    assert "def read_mcp_bundle_rows" in module_text
    assert "def _build_single_mcp_bundle_zip_bytes" not in api_text
    assert "def _read_mcp_bundle_rows" not in api_text


def test_skill_import_does_not_keep_api_mcp_bundle_parsers():
    """Skill import reads MCP rows through the current resource-bundle core helper."""
    api_text = (PROJECT_ROOT / "backend" / "app" / "api" / "settings_skills.py").read_text(encoding="utf-8")

    assert "read_bundle_tool_rows(tmp)" in api_text
    assert "def _read_mcp_bundle_rows" not in api_text
    assert "def _parse_mcp_bundle_rows" not in api_text


def test_opensandbox_file_operations_do_not_keep_command_channel_fallbacks():
    """OpenSandbox file operations must fail loudly when the filesystem endpoint is unavailable."""
    adapter_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "sandbox_adapter.py").read_text(encoding="utf-8")

    for forbidden in [
        "命令通道兜底",
        "read_file fallback failed",
        "write_file fallback failed",
        "fallback write too large",
        "base64.b64encode(data)",
        "base64.b64decode",
    ]:
        assert forbidden not in adapter_text


def test_resource_import_modules_keep_comments_at_file_or_function_boundary():
    """Contract-critical modules follow the comment placement coding standard."""
    paths = [
        PROJECT_ROOT / "backend" / "app" / "api" / "settings_presets.py",
        PROJECT_ROOT / "backend" / "app" / "api" / "settings_skills.py",
        PROJECT_ROOT / "backend" / "app" / "core" / "settings_bundle_import.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "group_session_service.py",
        PROJECT_ROOT / "backend" / "app" / "api" / "group_chat_state.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "message_contracts.py",
    ]

    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            assert not re.match(r"\s+#", line), f"{path}:{lineno}"


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
        "def tool_should_stop_after_result",
        "def read_file_should_synthesize_after_result",
    ]:
        assert name in flow_text
    for old_private_definition in [
        "def _iter_run_skill_raw_output_payloads",
        "def _run_skill_outputs_request_agent_turn_continue",
        "def _remember_successful_workspace_writes",
        "def _all_workspace_write_calls_already_succeeded",
        "def _post_tool_synthesis_should_use_bound_client",
        "def _tool_should_stop_after_result",
        "def _read_file_should_synthesize_after_result",
    ]:
        assert old_private_definition not in agent_text


def test_simple_agent_text_tool_protocol_has_independent_module_boundary():
    """Text-tool protocol retry/failure handling belongs outside the SimpleAgent loop file."""
    protocol_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_text_tool_protocol.py"
    agent_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent.py"

    assert protocol_module.exists()
    protocol_text = protocol_module.read_text(encoding="utf-8")
    agent_text = agent_module.read_text(encoding="utf-8")

    for name in [
        "def append_text_tool_protocol_retry_or_failure",
        "def last_message_is_text_tool_protocol_retry",
        "def text_tool_protocol_failure_message",
    ]:
        assert name in protocol_text
    for old_private_definition in [
        "def _append_text_tool_protocol_retry_or_failure",
        "def _last_message_is_text_tool_protocol_retry",
        "def _text_tool_protocol_failure_message",
    ]:
        assert old_private_definition not in agent_text


def test_resource_import_docs_do_not_advertise_legacy_conflict_controls():
    """Resource import docs must expose the current overwrite contract, not caller-selected strategies."""
    text = (PROJECT_ROOT / "docs" / "design" / "interface-document.md").read_text(encoding="utf-8")
    section = text.split("### 7.5 专家资源包", 1)[1].split("## 11. 工作区文件接口", 1)[0]

    for legacy_control in [
        "overwrite_experts",
        "overwrite_skills",
        "mcp_skip_existing",
        "name_conflict",
        "是否覆盖",
        "是否跳过",
    ]:
        assert legacy_control not in section
