"""群聊记忆开关与回退路径测试。"""
import os

os.environ.setdefault("QWEN_API_KEY", "test-key-for-unit-test")


def _get_context_module():
    from app.agent import group_context

    return group_context


def _get_memory_prompt_module():
    from app.agent import group_chat_memory_prompt

    return group_chat_memory_prompt


def _get_tool_trace_module():
    from app.agent import group_chat_tool_trace

    return group_chat_tool_trace


def _get_host_runtime_module():
    from app.agent import group_chat_host_runtime

    return group_chat_host_runtime


def test_next_prompt_fallback_when_memory_disabled():
    gc = _get_memory_prompt_module()
    app_settings = {"group_memory": {"enabled": False}}
    out = gc._build_next_prompt_with_memory(
        session_id="group-test",
        target_agent_id="agent-a",
        discussion_goal="写周报",
        context="最近讨论内容",
        app_settings=app_settings,
        decision_next_prompt="",
    )
    assert "最近几轮讨论内容" in out
    assert "写周报" in out


def test_next_prompt_uses_memory_when_available(monkeypatch):
    gc = _get_memory_prompt_module()
    from app.agent import group_chat_memory_prompt

    def _fake_dispatch_context(*args, **kwargs):
        return {
            "has_memory": True,
            "rendered": "【关键事实】\n- 已确认标题",
        }

    monkeypatch.setattr(group_chat_memory_prompt, "build_dispatch_context", _fake_dispatch_context)
    out = gc._build_next_prompt_with_memory(
        session_id="group-test",
        target_agent_id="agent-a",
        discussion_goal="写周报",
        context="ignored",
        app_settings={"group_memory": {"enabled": True, "dispatch_top_k": 2, "max_facts": 20}},
        decision_next_prompt="补充要求",
    )
    assert "关键事实" in out
    assert "补充要求" in out
    assert "主持人本轮指派" in out
    assert "复述当前你要完成的子任务" not in out
    assert "复述" not in out
    assert "我这轮要做" not in out
    assert "直接进入本轮角色发言" in out


def test_next_prompt_short_fallback_avoids_meta_task_preface():
    gc = _get_memory_prompt_module()

    out = gc._ensure_structured_next_prompt(
        prompt="请说明边界",
        discussion_goal="伴学研讨",
        context="学生正在讨论 AI 是否替代了本来该被考察的能力。",
        target_agent_id="agent-peer",
    )

    assert "先用 1-2 句确认你理解的子任务" not in out
    assert "复述" not in out
    assert "不要先说明你理解的子任务" in out


def test_persist_group_memory_turn_updates_only_facts_for_assistant(tmp_path):
    gc = _get_memory_prompt_module()
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    host_msg = {
        "role": "host",
        "agent_id": "agent-scene-host",
        "content": "请用户补充或继续提问。",
        "timestamp": "2026-05-13T12:30:50+00:00",
        "skill_id": "group-host-general",
    }

    gc._persist_group_memory_turn(
        session_id="group-test",
        msg=host_msg,
        discussion_goal="数据库中有内容吗",
        input_prompt_summary="这是全部信息了吗",
        app_settings={"group_memory": {"enabled": True, "max_logs": 5, "max_facts": 20}},
        workspace_root=ws,
    )

    assert not (ws / "memory" / "facts.md").exists()
    assert not (ws / "memory" / "messages").exists()
    assert not (ws / "memory" / "logs").exists()

    assistant_msg = {
        "role": "assistant",
        "agent_id": "agent-data",
        "content": "- 用户希望输出周报\n- 需要包含趋势图表",
        "timestamp": "2026-05-13T12:31:50+00:00",
        "skill_id": "weekly-report",
    }
    gc._persist_group_memory_turn(
        session_id="group-test",
        msg=assistant_msg,
        discussion_goal="数据库中有内容吗",
        input_prompt_summary="这是全部信息了吗",
        app_settings={"group_memory": {"enabled": True, "max_logs": 5, "max_facts": 20}},
        workspace_root=ws,
    )

    facts = (ws / "memory" / "facts.md").read_text(encoding="utf-8")
    assert "- 用户希望输出周报" in facts
    assert "- 需要包含趋势图表" in facts
    assert not (ws / "memory" / "messages").exists()
    assert not (ws / "memory" / "logs").exists()


def test_log_llm_roundtrip_does_not_write_session_workspace_jsonl(tmp_path):
    gc = _get_host_runtime_module()
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    gc._log_llm_roundtrip(
        "host_decide",
        session_id="group-test",
        workspace_root=ws,
        system_content="系统提示",
        user_content="用户提示",
        model_output="模型输出",
        extra={"agent_id": "agent-host", "model": "qwen3"},
    )

    assert not (ws / "memory" / "llm_roundtrips.jsonl").exists()

def test_append_workspace_image_preview_markdown_keeps_non_image_content():
    gc = _get_tool_trace_module()
    base = "工具执行成功。"
    raw = ['{"ok": true, "stdout": "抓取到正文 markdown ..."}']
    out = gc.append_workspace_image_preview_markdown(base, raw)
    assert out == base


def test_append_workspace_image_preview_markdown_appends_image_links():
    gc = _get_tool_trace_module()
    base = "已生成图片。"
    raw = ['下载链接：/api/workspaces/s1/files/download?path=generated_images/a.jpg']
    out = gc.append_workspace_image_preview_markdown(base, raw)
    assert "![生成图片1](/api/workspaces/s1/files/download?path=generated_images/a.jpg)" in out


def test_has_auto_continue_signal_detects_continue_intent():
    gc = _get_context_module()
    assert gc.has_auto_continue_signal("接下来我会继续执行下一步。") is True
    assert gc.has_auto_continue_signal("[[AUTO_CONTINUE]] proceeding.") is True


def test_has_auto_continue_signal_defaults_to_handoff_user():
    gc = _get_context_module()
    assert gc.has_auto_continue_signal("这是当前结论，请你确认是否继续。") is False
    assert gc.has_auto_continue_signal("想接项目就别上来问这种空话。") is False
    assert gc.has_auto_continue_signal("你先挑一块具体的，别泛泛而谈。") is False
