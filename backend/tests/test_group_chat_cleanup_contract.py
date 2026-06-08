from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_backend_core_files_stay_bounded_after_extraction():
    assert len(_read("app/api/group_chat.py").splitlines()) <= 900
    assert len(_read("app/agent/group_chat_runtime.py").splitlines()) <= 1500
    assert len(_read("app/agent/simple_agent.py").splitlines()) <= 900
    assert len(_read("app/agent/skill_agent_runtime.py").splitlines()) <= 800
    assert len(_read("app/agent/sandbox_service.py").splitlines()) <= 1200


def test_backend_extraction_modules_exist_without_legacy_smells():
    modules = (
        "app/agent/group_chat_memory_prompt.py",
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
            "app/agent/leader_scheduler.py",
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
