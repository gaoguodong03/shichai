from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_backend_core_files_stay_bounded_after_extraction():
    assert len(_read("app/api/group_chat.py").splitlines()) <= 900
    assert len(_read("app/agent/group_chat_runtime.py").splitlines()) <= 1500
    assert len(_read("app/agent/simple_agent.py").splitlines()) <= 1600
    assert len(_read("app/agent/skill_agent_runtime.py").splitlines()) <= 800
    assert len(_read("app/agent/sandbox_service.py").splitlines()) <= 1200


def test_backend_extraction_modules_exist_without_legacy_smells():
    modules = (
        "app/agent/group_chat_memory_prompt.py",
        "app/agent/group_orchestration_fsm.py",
        "app/agent/group_chat_skill_session.py",
        "app/agent/group_chat_host_runtime.py",
        "app/agent/group_chat_host_messages.py",
        "app/agent/simple_agent_finalization.py",
        "app/agent/simple_agent_tool_errors.py",
        "app/agent/skill_agent_paths.py",
        "app/agent/sandbox_requirements_verifier.py",
        "app/agent/sandbox_requirements_installer.py",
        "app/agent/sandbox_workspace_ops.py",
    )
    for path in modules:
        assert (ROOT / path).is_file()

    runtime_text = _read("app/agent/group_chat_runtime.py")
    skill_paths = _read("app/agent/skill_agent_paths.py")
    for text in (
        "# ========== Pydantic 模型 ==========",
        "_safe_format_template",
        "_expert_runtime_model_name",
        "_extract_path_from_last_user_for_read",
        "_apply_read_file_path_from_user_message",
        "_collect_paths_from_user_text",
        "_pick_best_workspace_path",
    ):
        assert text not in runtime_text
        assert text not in skill_paths


def test_group_chat_removes_legacy_mode_and_internal_memory_artifacts():
    for deleted_path in (
        "app/agent/leader_scheduler.py",
        "app/agent/orchestrator_runtime.py",
        "app/agent/orchestrator_reducer.py",
        "app/agent/orchestrator_state.py",
        "app/agent/scene_runtime.py",
        "app/agent/group_chat_hooks.py",
        "app/core/scene_scheduler.py",
    ):
        assert not (ROOT / deleted_path).exists()

    combined = "\n".join(
        _read(path)
        for path in (
            "app/api/group_chat.py",
            "app/agent/group_chat_runtime.py",
            "app/agent/group_session_service.py",
            "app/api/group_chat_state.py",
            "app/api/sessions.py",
            "app/agent/group_memory_store.py",
            "app/agent/expert_runtime.py",
            "app/agent/sandbox_audit.py",
            "app/agent/tools_for_skill.py",
            "app/tools/write_workspace_file.py",
            "app/agent/workspace_visibility.py",
        )
    )
    for text in (
        "speak_mode",
        "custom_prompt",
        "GroupPromptPreviewRequest",
        "preview_next_speaker_prompt",
        "CHAT_AGENT_ID",
        "agent-chat",
        "host_plan.md",
        "llm_roundtrips.jsonl",
        "orchestrator_audit.jsonl",
        "append_llm_roundtrip",
        "append_audit_event",
    ):
        assert text not in combined


def test_group_chat_runtime_does_not_replace_unverified_delivery_claims():
    runtime_text = _read("app/agent/group_chat_runtime.py")

    assert "guard_unverified_delivery_claims" not in runtime_text
    assert "本轮没有确认文件生成成功" not in runtime_text


def test_group_chat_title_meta_does_not_infer_required_user_fields():
    title_meta = _read("app/agent/group_chat_title_meta.py")

    assert "_infer_required_user_fields_for_skill" not in title_meta
    assert "_skill_requires_confirmation_gate" not in title_meta
    assert "required_user_fields" not in title_meta


def test_runtime_code_removes_legacy_skill_and_host_control_fields():
    skill_session = _read("app/agent/skill_session_contract.py")
    host_messages = _read("app/agent/group_chat_host_messages.py")
    host_decision = _read("app/agent/group_host_decision.py")
    tool_records = _read("app/agent/skill_tool_result_records.py")
    tool_content = _read("app/agent/group_chat_tool_result_content.py")

    assert "resolve_skill_session_state" not in skill_session
    assert 'render_platform_prompt("skill.session.state_instruction.v1", {})' in skill_session
    assert "SKILL_SESSION_STATE_START" not in skill_session
    assert "announcement:" not in host_messages
    assert "reason:" not in host_messages
    assert "suggested_order:" not in host_messages
    assert "explicit_flag" not in host_decision
    assert "required_user_fields" not in tool_records
    assert "required_user_fields" not in tool_content


def test_frontend_e2e_mock_uses_current_resource_fields():
    mock = (ROOT.parent / "frontend/e2e/fixtures/mockApi.ts").read_text(encoding="utf-8")

    assert "role: string" not in mock
    assert "is_leader" not in mock
    assert "role:" not in mock
    assert "label: 'Qwen'" not in mock
    assert "kept_skill_ids" not in mock
