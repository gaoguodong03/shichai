import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEGACY_LEADER_AGENT_NAME = "leader_agent" + "_name"
LEGACY_HOST_CONFIG = "host_" + "config"
LEGACY_ORCHESTRATION_PROFILE = "orchestration" + "_profile"


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
        LEGACY_LEADER_AGENT_NAME,
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


def test_backend_runtime_does_not_keep_noop_scene_profile_upgrade_hook():
    """Session runtime must not keep empty legacy scene-profile upgrade hooks."""
    runtime_files = [
        PROJECT_ROOT / "backend" / "app" / "agent" / "group_session_service.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_title_meta.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)

    assert "_ensure_scene_profile_contract" not in combined
    assert "scene_profile" not in combined


def test_simple_agent_tool_summary_helpers_are_not_named_as_fallbacks():
    """Tool-result summary paths are product behavior, not legacy fallback branches."""
    runtime_files = [
        PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_streaming.py",
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
    streaming_module = PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent_streaming.py"

    assert summary_module.exists()
    summary_text = summary_module.read_text(encoding="utf-8")
    error_text = error_module.read_text(encoding="utf-8")
    streaming_text = streaming_module.read_text(encoding="utf-8")

    assert "def _final_response_or_tool_summary" in summary_text
    assert "def _final_response_or_tool_summary" not in error_text
    assert "from app.agent.simple_agent_tool_summary import _final_response_or_tool_summary" in streaming_text


def test_simple_agent_does_not_advertise_content_tool_call_fallback():
    """SimpleAgent documentation must not reintroduce legacy content-json tool-call fallback."""
    text = (PROJECT_ROOT / "backend" / "app" / "agent" / "simple_agent.py").read_text(encoding="utf-8")

    for forbidden in [
        "content-json 回退",
        "content 中的 tool_call JSON",
    ]:
        assert forbidden not in text


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


def test_design_docs_do_not_reference_removed_host_profile_module():
    """Formal design docs must point to current host profile modules."""
    text = (PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md").read_text(encoding="utf-8")

    assert f"backend/app/core/{LEGACY_HOST_CONFIG}.py" not in text
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


def test_formal_docs_do_not_advertise_removed_chat_stream_start_event():
    """The chat stream contract starts with route/message/progress, not a start event."""
    docs = [
        PROJECT_ROOT / "docs" / "contracts" / "runtime-interface-contract.md",
        PROJECT_ROOT / "docs" / "contracts" / "data-structure-and-field-logic.md",
        PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md",
        PROJECT_ROOT / "docs" / "design" / "interface-document.md",
        PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md",
    ]
    forbidden = [
        "start\n  -> route?",
        "start -> message?",
        "`start`、`route`",
        "`start`、`route`、`progress`、`message`、`end`、`error`",
        "start/route/progress/message/end/error",
        "| `start` |",
        "处理 `start`",
    ]

    for path in docs:
        text = path.read_text(encoding="utf-8")
        for marker in forbidden:
            assert marker not in text, f"{path}: {marker}"


def test_chat_once_runtime_is_not_named_as_fallback():
    """The non-stream chat endpoint is a formal aggregation path, not fallback logic."""
    text = (PROJECT_ROOT / "backend" / "app" / "api" / "sessions.py").read_text(encoding="utf-8")
    section = text.split("async def session_chat_once", 1)[1].split("\n\n@router.", 1)[0]

    assert "兜底" not in section
    assert "fallback" not in section


def test_session_api_delegates_chat_once_aggregation_to_agent_module():
    """The non-stream chat endpoint is a thin API entry, not the SSE aggregator."""
    api_text = (PROJECT_ROOT / "backend" / "app" / "api" / "sessions.py").read_text(encoding="utf-8")
    aggregator_path = PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_once.py"
    aggregator_text = aggregator_path.read_text(encoding="utf-8") if aggregator_path.exists() else ""
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "`sessions.py` | 会话 CRUD、聊天流入口、停止运行、会话详情 API。只做薄入口。" in boundary_text
    assert "`group_chat_once.py` | 非流式 `/chat` 聚合入口，只消费 SSE 契约事件并返回聚合 JSON。" in boundary_text
    assert "import asyncio" not in api_text
    assert "import json" not in api_text
    assert "SseErrorEvent" not in api_text
    assert "body_iterator" not in api_text
    assert "def _parse_sse_block" not in api_text
    assert "async def group_chat_once" in aggregator_text


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
    """Skill import reads MCP rows in the service layer, not the API route module."""
    api_text = (PROJECT_ROOT / "backend" / "app" / "api" / "settings_skills.py").read_text(encoding="utf-8")
    service_text = (PROJECT_ROOT / "backend" / "app" / "core" / "skill_bundle_service.py").read_text(encoding="utf-8")

    assert "read_bundle_tool_rows(tmp)" in service_text
    assert "def _read_mcp_bundle_rows" not in api_text
    assert "def _parse_mcp_bundle_rows" not in api_text


def test_opensandbox_file_operations_do_not_keep_command_channel_fallbacks():
    """OpenSandbox file operations must fail loudly when the filesystem endpoint is unavailable."""
    adapter_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            PROJECT_ROOT / "backend" / "app" / "agent" / "sandbox_adapter.py",
            PROJECT_ROOT / "backend" / "app" / "agent" / "opensandbox_runtime_client.py",
        ]
    )

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
        PROJECT_ROOT / "backend" / "app" / "core" / "settings_bundle_missing_references.py",
        PROJECT_ROOT / "backend" / "app" / "core" / "skill_bundle_service.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "group_session_service.py",
        PROJECT_ROOT / "backend" / "app" / "api" / "group_chat_state.py",
        PROJECT_ROOT / "backend" / "app" / "api" / "files.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "message_contracts.py",
    ]

    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            assert not re.match(r"\s+#", line), f"{path}:{lineno}"


def test_resource_import_comments_use_directory_name_not_id_language():
    """Resource import code comments must not reintroduce id-based Skill identity wording."""
    text = (PROJECT_ROOT / "backend" / "app" / "core" / "scenario_bundle.py").read_text(encoding="utf-8")

    assert "bundle_dir/skills/<id>/" not in text
    assert "bundle_dir/skills/{directory_name}/" in text


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
        "def run_skill_outputs_request_agent_turn_continue",
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


def test_module_boundary_doc_uses_current_resource_file_paths():
    """Module boundary docs must cite current filenames, not removed secret/resource paths."""
    text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    removed_secret_module = "settings_" + "secrets.py"
    assert "settings_env_vars.py" in text
    assert removed_secret_module not in text
    assert "frontend/src/features/resources/mcpConfigContract.ts" in text
    assert "frontend/src/features/settings/mcpConfigContract.ts" not in text
    assert (PROJECT_ROOT / "backend" / "app" / "api" / "settings_env_vars.py").exists()
    assert (PROJECT_ROOT / "frontend" / "src" / "features" / "resources" / "mcpConfigContract.ts").exists()


def test_code_and_tests_do_not_carry_legacy_secret_contract_literals():
    """Code and tests must not carry removed secret/vault contract literals."""
    forbidden = [
        "api_key" + "_ref",
        "api-" + "secrets",
        "settings/" + "secrets.enc.json",
        "${" + "vault:",
        "settings_" + "secrets.py",
        "set" + "Vault",
    ]
    roots = [
        PROJECT_ROOT / "backend" / "app",
        PROJECT_ROOT / "backend" / "tests",
        PROJECT_ROOT / "frontend" / "src",
        PROJECT_ROOT / "frontend" / "e2e",
    ]
    offenders = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".vue"}:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{token}")
    assert offenders == []


def test_code_and_tests_do_not_carry_legacy_session_contract_literals():
    """Code and tests must not carry removed session-definition field literals."""
    forbidden = [
        "scenario" + "_name",
        "orchestration" + "_profile",
        "leader_agent" + "_name",
        "host_" + "config",
    ]
    roots = [
        PROJECT_ROOT / "backend" / "app",
        PROJECT_ROOT / "backend" / "tests",
        PROJECT_ROOT / "frontend" / "src",
        PROJECT_ROOT / "frontend" / "e2e",
    ]
    offenders = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".vue"}:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{token}")
    assert offenders == []


def test_frontend_settings_env_vars_do_not_use_secret_navigation_identity():
    """Frontend settings navigation must use the env-vars contract, not the old secrets identity."""
    frontend_files = {
        "navigation": PROJECT_ROOT / "frontend" / "src" / "features" / "shell" / "mainNavigation.ts",
        "router": PROJECT_ROOT / "frontend" / "src" / "router" / "index.ts",
        "main_view": PROJECT_ROOT / "frontend" / "src" / "views" / "MainView.vue",
        "mcp_add": PROJECT_ROOT / "frontend" / "src" / "features" / "resources" / "MCPAddView.vue",
        "mcp_detail": PROJECT_ROOT / "frontend" / "src" / "features" / "resources" / "MCPDetailView.vue",
        "module_doc": PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md",
    }
    combined = "\n".join(path.read_text(encoding="utf-8") for path in frontend_files.values())

    assert "env-vars" in combined
    assert "环境变量" in frontend_files["navigation"].read_text(encoding="utf-8")
    assert "EnvVarsSettingsView" in combined
    assert "useEnvVars" in (
        PROJECT_ROOT / "frontend" / "src" / "features" / "resources" / "MCPAddView.vue"
    ).read_text(encoding="utf-8")
    assert (PROJECT_ROOT / "frontend" / "src" / "features" / "settings" / "EnvVarsSettingsView.vue").exists()
    assert (PROJECT_ROOT / "frontend" / "src" / "composables" / "useEnvVars.ts").exists()

    for legacy in ["ApiSecretsSettingsView", "useApiSecrets", "'secrets'", "label: '密钥'", "填入密钥"]:
        assert legacy not in combined


def test_runtime_user_messages_do_not_reference_removed_secret_settings_entry():
    """Runtime-facing notices must send users to env vars, not the removed secret settings entry."""
    runtime_paths = [
        PROJECT_ROOT / "backend" / "app" / "agent" / "llm_client.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "llm_prompt_trace.py",
        PROJECT_ROOT / "backend" / "app" / "mcp" / "stdio" / "audio_asr.py",
        PROJECT_ROOT / "backend" / "app" / "mcp" / "stdio" / "volces_icon.py",
        PROJECT_ROOT / "backend" / "app" / "mcp" / "stdio" / "image_generation.py",
        PROJECT_ROOT / "backend" / "app" / "agent" / "tools_for_skill.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_paths)

    for legacy in ["设置 → 密钥", "选择密钥", "添加密钥", "密钥设置", "配置该密钥", "对应密钥", "未设置的密钥"]:
        assert legacy not in combined


def test_frontend_model_types_do_not_keep_legacy_api_key_set_field():
    """Frontend model types must not expose the removed inline-key status field."""
    frontend_paths = [
        PROJECT_ROOT / "frontend" / "src" / "features" / "resources" / "LLMSettingsView.vue",
        PROJECT_ROOT / "frontend" / "src" / "features" / "resources" / "useBundleImports.ts",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in frontend_paths)

    assert "api_key_env" in combined
    assert "api_key_set" not in combined


def test_sandbox_tool_docs_use_current_workspace_rename_schema():
    """Sandbox tool authoring docs must match the current workspace rename parameter."""
    text = (PROJECT_ROOT / "docs" / "skills" / "sandbox-tool-interface.md").read_text(encoding="utf-8")
    section = text.split("### `rename_workspace_file`", 1)[1].split("### `mkdir_workspace`", 1)[0]

    assert "target_path" in section
    assert "new_name" not in section


def test_resource_import_docs_use_skill_directory_identity():
    """Resource import docs must not describe Skill import identity as display-name based."""
    paths = [
        PROJECT_ROOT / "docs" / "design" / "interface-document.md",
        PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md",
        PROJECT_ROOT / "docs" / "architecture" / "scenario-bundle-export.md",
        PROJECT_ROOT / "docs" / "architecture" / "user-resource-store" / "storage-standard.md",
    ]

    for path in paths:
        text = path.read_text(encoding="utf-8")
        for forbidden in [
            "同名 Skill",
            "frontmatter `name` 判断",
            "导入同名判断",
            "同名展示名 Skill",
            "Skill 同名覆盖",
        ]:
            assert forbidden not in text, path


def test_name_based_resource_helpers_do_not_keep_skill_display_name_directory_planner():
    """Skill directory conflict helpers must not use frontmatter name as import identity."""
    text = (PROJECT_ROOT / "backend" / "app" / "core" / "name_based_resources.py").read_text(encoding="utf-8")

    for forbidden in [
        "def next_available_skill_folder",
        "def _read_skill_name",
        "def _normalize_skill_folder",
    ]:
        assert forbidden not in text


def test_data_structure_contract_does_not_use_skill_display_name_for_import_identity():
    """The field contract must state Skill name is display-only for import identity."""
    text = (PROJECT_ROOT / "docs" / "contracts" / "data-structure-and-field-logic.md").read_text(encoding="utf-8")
    section = text.split("## 5. Skill 字段", 1)[1].split("## 6. 工具字段", 1)[0]

    for forbidden in [
        "也用于同名导入判断",
        "导入冲突",
        "同名导入判断",
    ]:
        assert forbidden not in section


def _configured_layer1_modules() -> list[str]:
    text = (PROJECT_ROOT / "backend" / "tests" / "conftest.py").read_text(encoding="utf-8")
    block = text.split("LAYER1_CORE_MODULES", 1)[1].split(")\n\n\n", 1)[0]
    return sorted(set(re.findall(r'"(test_[A-Za-z0-9_]+)"', block)))


def test_layer1_regression_doc_matches_configured_modules():
    """Layer-1 docs must be regenerated from the current marker configuration."""
    text = (PROJECT_ROOT / "docs" / "testing" / "layer1-regression.md").read_text(encoding="utf-8")
    modules = _configured_layer1_modules()

    assert f"当前 {len(modules)} 个" in text
    for module in modules:
        assert f"`{module}.py`" in text
    for old_reference in [
        "当前 31 个",
        "test_scene_scheduler.py",
        "test_scene_runtime.py",
        "test_orchestration_contracts.py",
    ]:
        assert old_reference not in text


def test_contract_traceability_matrix_exists_with_required_columns():
    """Contract implementation tracking belongs in a dedicated traceability matrix."""
    text = (PROJECT_ROOT / "docs" / "testing" / "contract-traceability-matrix.md").read_text(encoding="utf-8")

    for column in [
        "契约编号",
        "契约来源",
        "条款摘要",
        "当前代码锚点",
        "当前测试锚点",
        "状态",
        "缺口",
        "修改动作",
        "验证命令",
    ]:
        assert column in text
    for status in [
        "已实现且有测试",
        "已实现但测试不足",
        "文档已定，代码待改",
        "代码存在旧逻辑，待删除",
        "需确认",
    ]:
        assert status in text
    assert "PROMPT-01" in text
    assert "backend/app/agent/platform_prompt_templates.json" in text


def test_runtime_and_design_docs_do_not_reference_removed_scene_scheduler():
    """Formal docs must not point host post-processing at removed scheduler files."""
    runtime_text = (PROJECT_ROOT / "docs" / "contracts" / "runtime-interface-contract.md").read_text(encoding="utf-8")
    design_text = (PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md").read_text(encoding="utf-8")

    assert "backend/app/core/scene_scheduler.py" not in runtime_text
    assert "backend/app/core/scene_scheduler.py" not in design_text
    assert "主持人严格输出与后处理：[`backend/app/agent/group_host_decision.py`" in runtime_text
    assert "`backend/app/agent/group_host_decision.py`" in design_text


def test_skill_contract_test_index_exists_with_required_sections():
    """Skill contract coverage must be traceable by document section."""
    text = (PROJECT_ROOT / "docs" / "testing" / "skill-contract-test-index.md").read_text(encoding="utf-8")

    for column in [
        "文档章节",
        "契约要求",
        "代码锚点",
        "测试锚点",
        "验证命令",
    ]:
        assert column in text
    for section in [
        "skill-standard.md §2",
        "skill-standard.md §4.2",
        "sandbox-tool-interface.md 总体规则",
        "sandbox-tool-interface.md 技能脚本工具",
        "sandbox-tool-interface.md 保存型 HTTP API 工具",
    ]:
        assert section in text
    for test_file in [
        "backend/tests/test_skill_mcp_and_script_requirements.py",
        "backend/tests/test_skill_agent_tool_resolution.py",
        "backend/tests/test_file_ref_and_gateway.py",
    ]:
        assert test_file in text


def test_prompt_contract_test_index_exists_with_llm_call_points():
    """Prompt contract coverage must be traceable by LLM call point."""
    text = (PROJECT_ROOT / "docs" / "testing" / "prompt-contract-test-index.md").read_text(encoding="utf-8")

    for column in [
        "LLM 调用点",
        "Prompt 块边界",
        "代码锚点",
        "测试锚点",
        "验证命令",
    ]:
        assert column in text
    for call_point in [
        "主持人选择专家",
        "专家选择 Skill",
        "专家通过 Skill 执行能力",
        "标题生成",
        "展示重写",
        "LLM 可见工具消息",
    ]:
        assert call_point in text
    for test_file in [
        "backend/tests/test_host_takeover.py",
        "backend/tests/test_expert_runtime.py",
        "backend/tests/test_expert_self_awareness_prompt.py",
        "backend/tests/test_group_chat_presentation_rewriter.py",
        "backend/tests/test_platform_prompts.py",
        "backend/tests/test_simple_agent_tool_intent.py",
    ]:
        assert test_file in text


def test_prompt_contract_points_to_current_template_registry():
    """Prompt contract must name the current template registry as the implementation target."""
    text = (PROJECT_ROOT / "docs" / "contracts" / "prompt-assembly-contract.md").read_text(encoding="utf-8")

    assert "版本：v1.0 当前契约" in text
    assert "统一平台内置模板文件：`backend/app/agent/platform_prompt_templates.json`" in text
    assert "本文是目标契约" not in text
    assert "后续代码、测试和文档应按本文收敛" not in text


def test_formal_testing_docs_reference_existing_test_files():
    """Concrete test-file references in formal testing docs must resolve to real files."""
    actual_paths = {str(path.relative_to(PROJECT_ROOT)) for path in (PROJECT_ROOT / "backend" / "tests").glob("test_*.py")}
    actual_paths.update(
        str(path.relative_to(PROJECT_ROOT)) for path in (PROJECT_ROOT / "frontend" / "e2e").glob("*.spec.ts")
    )
    actual_by_name = {Path(path).name: path for path in actual_paths}
    docs = [
        PROJECT_ROOT / "docs" / "testing" / "layer1-regression.md",
        PROJECT_ROOT / "docs" / "testing" / "contract-traceability-matrix.md",
        PROJECT_ROOT / "docs" / "testing" / "prompt-contract-test-index.md",
        PROJECT_ROOT / "docs" / "testing" / "skill-contract-test-index.md",
        PROJECT_ROOT / "docs" / "testing" / "test-case-catalog.md",
        PROJECT_ROOT / "docs" / "testing" / "full-flow-business-tests.md",
        PROJECT_ROOT / "docs" / "testing" / "pre-release-testing.md",
        PROJECT_ROOT / "docs" / "requirements" / "acceptance-and-tests.md",
        PROJECT_ROOT / "docs" / "design" / "detailed-design-spec.md",
        PROJECT_ROOT / "docs" / "design" / "interface-document.md",
    ]
    pattern = re.compile(
        r"(?:(?:backend/tests|frontend/e2e|tests)/)?test_[A-Za-z0-9_]+\.py"
        r"|frontend/e2e/[A-Za-z0-9_.-]+\.spec\.ts"
        r"|[A-Za-z0-9_.-]+\.spec\.ts"
    )
    missing = []

    for doc in docs:
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            for match in pattern.finditer(line):
                ref = match.group(0)
                if ref in {"test_xxx.py", "tests/test_xxx.py"}:
                    continue
                if ref.startswith("tests/"):
                    normalized = "backend/" + ref
                elif ref.startswith(("backend/tests/", "frontend/e2e/")):
                    normalized = ref
                elif ref.endswith(".spec.ts"):
                    normalized = "frontend/e2e/" + ref
                else:
                    normalized = actual_by_name.get(ref, "backend/tests/" + ref)
                if normalized not in actual_paths:
                    missing.append(f"{doc.relative_to(PROJECT_ROOT)}:{lineno}:{ref}")

    assert missing == []


def test_formal_docs_do_not_reference_removed_test_modules():
    """Formal docs must not point readers to removed test modules."""
    docs = [
        PROJECT_ROOT / "docs" / "testing",
        PROJECT_ROOT / "docs" / "requirements",
        PROJECT_ROOT / "docs" / "design",
    ]
    forbidden = [
        "test_scene_scheduler",
        "test_scene_runtime",
        "test_orchestration_contracts",
    ]
    offenders = []

    for root in docs:
        for path in root.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)}:{token}")

    assert offenders == []


def test_tools_for_skill_delegates_builtin_workspace_tool_implementation():
    """Tool assembly should not own builtin workspace tool implementations."""
    text = (PROJECT_ROOT / "backend" / "app" / "agent" / "tools_for_skill.py").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "字段契约、运行决策、状态落盘、Prompt 组装、工具组装和前端展示状态必须分开" in boundary_text
    assert "def _create_builtin_workspace_tools" not in text
    assert "class EditWorkspaceFileInput" not in text
    assert "from app.agent.builtin_workspace_tools import create_builtin_workspace_tools" in text


def test_group_chat_runtime_delegates_sse_serialization_to_streaming_module():
    """Group-chat runtime should not own SSE event serialization helpers."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    streaming_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_streaming.py").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "`group_chat_streaming.py` | SSE 事件构造和序列化。" in boundary_text
    assert "def _sse(" not in runtime_text
    assert "def _end_event_payload" not in runtime_text
    assert "serialize_sse_event" in streaming_text
    assert "end_event_payload" in streaming_text


def test_group_chat_runtime_delegates_tool_artifact_collection():
    """Tool-result artifact extraction belongs with tool-result content helpers."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    tool_content_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_tool_result_content.py").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "`group_chat_tool_result_content.py` | 工具结果转用户可见内容和公开 artifact 提取。" in boundary_text
    assert "def _collect_artifacts" not in runtime_text
    assert "ArtifactRef" not in runtime_text
    assert "def collect_artifacts" in tool_content_text
    assert "has_failed = any(" not in runtime_text
    assert "has_blocked = any(" not in runtime_text
    assert "skill_result_from_content(" not in runtime_text
    assert "def build_expert_skill_result" in tool_content_text


def test_group_chat_runtime_delegates_tool_trace_logging():
    """Tool trace logging belongs with group-chat tool trace helpers."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    trace_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_tool_trace.py").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "`group_chat_tool_trace.py` | 工具 trace、日志和调试记录。" in boundary_text
    assert "from app.agent.session_runtime_logs import append_tool_execution_logs" not in runtime_text
    assert "append_tool_execution_logs(" not in runtime_text
    assert "def record_group_chat_tool_trace" in trace_text
    assert "append_tool_execution_logs(" in trace_text


def test_group_chat_runtime_delegates_expert_turn_budget_to_soft_stop():
    """Expert turn budget and waiting-user pause rules belong with soft-stop helpers."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    soft_stop_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_soft_stop.py").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")
    contract_text = (PROJECT_ROOT / "docs" / "contracts" / "runtime-interface-contract.md").read_text(encoding="utf-8")

    assert "`group_chat_soft_stop.py` | soft stop 和等待用户规则。" in boundary_text
    assert "超过后用 `timeout_or_budget_exceeded` 中断并等待用户" in contract_text
    assert "MAX_EXPERT_TURNS_PER_STREAM" not in runtime_text
    assert "turns >" not in runtime_text
    assert 'phase="timeout_or_budget_exceeded"' in runtime_text
    assert "| `timeout_or_budget_exceeded` |" in contract_text
    assert "MAX_EXPERT_TURNS_PER_STREAM" in soft_stop_text
    assert "def expert_turn_budget_exceeded" in soft_stop_text


def test_group_chat_runtime_delegates_expert_turn_execution():
    """Expert single-turn execution belongs in group_chat_expert_turn.py."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    expert_turn_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_expert_turn.py").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "`group_chat_expert_turn.py` | 专家单回合流式执行、进度事件、工具结果汇总、消息落盘和工具 trace 写入。" in boundary_text
    assert "from app.agent.group_chat_expert_turn import run_one_expert_turn" in runtime_text
    assert "async def _run_one_expert_turn" not in runtime_text
    assert "runtime.agent.astream" not in runtime_text
    assert "async def run_one_expert_turn" in expert_turn_text
    assert "runtime.agent.astream" in expert_turn_text


def test_skill_script_tool_naming_uses_directory_name_terminology():
    """Skill runtime identity is directory_name, not a legacy id."""
    naming_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "skill_tool_naming.py").read_text(encoding="utf-8")
    field_contract_text = (PROJECT_ROOT / "docs" / "contracts" / "data-structure-and-field-logic.md").read_text(encoding="utf-8")

    assert "| Skill | `directory_name` | `resources/skills/{directory_name}/SKILL.md` |" in field_contract_text
    assert "Skill id" not in naming_text
    assert "directory_name" in naming_text


def test_group_chat_runtime_delegates_request_input_parsing():
    """Request attachment validation and user prompt assembly belong in a dedicated helper."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    helper_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_request_inputs.py").read_text(encoding="utf-8")
    coding_text = (PROJECT_ROOT / "docs" / "development" / "coding-standard.md").read_text(encoding="utf-8")

    assert "请求校验和附件解析进入独立解析模块" in coding_text
    assert "def _validate_attachments" not in runtime_text
    assert "def _request_user_text" not in runtime_text
    assert "def validate_attachments" in helper_text
    assert "def request_user_text" in helper_text


def test_group_chat_runtime_delegates_recruitment_decision_finalization():
    """Host recruitment suggestion finalization belongs with host decision logic."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    host_decision_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_host_decision.py").read_text(encoding="utf-8")
    contract_text = (PROJECT_ROOT / "docs" / "contracts" / "runtime-interface-contract.md").read_text(encoding="utf-8")
    boundary_text = (PROJECT_ROOT / "docs" / "development" / "module-file-boundaries.md").read_text(encoding="utf-8")

    assert "`finalize_host_scheduler_decision()` 负责统一后处理" in contract_text
    assert "`group_host_decision.py` | 主持人严格 JSON 解析、合法性校验、保护决策、招募建议后处理和调度决策应用。" in boundary_text
    assert "def _finalize_suggested_add_agent_names" not in runtime_text
    assert "def _user_requests_recruitment" not in runtime_text
    assert "def finalize_host_scheduler_decision" in host_decision_text


def test_group_chat_runtime_delegates_host_decision_context_application():
    """Host decision application belongs with host decision logic."""
    runtime_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_chat_runtime.py").read_text(encoding="utf-8")
    host_decision_text = (PROJECT_ROOT / "backend" / "app" / "agent" / "group_host_decision.py").read_text(encoding="utf-8")
    contract_text = (PROJECT_ROOT / "docs" / "contracts" / "runtime-interface-contract.md").read_text(encoding="utf-8")

    assert "-> _apply_decision_to_ctx(...)" in contract_text
    assert "def _apply_decision_to_ctx" in host_decision_text
    assert 'str(decision.get("current_phase")' not in runtime_text
    assert 'str(decision.get("next_action")' not in runtime_text
