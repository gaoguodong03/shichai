from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_group_chat_api_shell_stays_small():
    """group_chat API should stay a thin route shell after runtime extraction."""
    lines = _read("app/api/group_chat.py").splitlines()

    assert len(lines) <= 900


def test_group_chat_removes_legacy_mode_and_placeholder_fields():
    """Deprecated manual/auto mode and placeholder chat-agent fields must not leak through APIs."""
    combined = "\n".join(
        [
            _read("app/api/group_chat.py"),
            _read("app/agent/group_chat_runtime.py"),
            _read("app/agent/group_session_service.py"),
            _read("app/api/group_chat_state.py"),
            _read("app/api/sessions.py"),
        ]
    )

    assert "speak_mode" not in combined
    assert "custom_prompt" not in combined
    assert "GroupPromptPreviewRequest" not in combined
    assert "preview_next_speaker_prompt" not in combined
    assert "CHAT_AGENT_ID" not in combined
    assert "agent-chat" not in combined


def test_group_chat_no_longer_writes_internal_memory_artifacts():
    """Runtime should not create host_plan, LLM roundtrip, or orchestration-audit memory files."""
    production_files = [
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
    ]
    combined = "\n".join(_read(path) for path in production_files)

    assert "host_plan.md" not in combined
    assert "llm_roundtrips.jsonl" not in combined
    assert "orchestrator_audit.jsonl" not in combined
    assert "append_llm_roundtrip" not in combined
    assert "append_audit_event" not in combined
