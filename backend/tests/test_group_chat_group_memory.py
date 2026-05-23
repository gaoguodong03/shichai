"""群聊记忆开关与回退路径测试。"""
import os

os.environ.setdefault("QWEN_API_KEY", "test-key-for-unit-test")


def _get_group_chat_module():
    from app.api import group_chat

    return group_chat


def test_next_prompt_fallback_when_memory_disabled():
    gc = _get_group_chat_module()
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
    gc = _get_group_chat_module()

    def _fake_dispatch_context(*args, **kwargs):
        return {
            "has_memory": True,
            "rendered": "【关键事实】\n- 已确认标题\n\n【相关历史摘录】\n1. xxx",
        }

    monkeypatch.setattr(gc, "build_dispatch_context", _fake_dispatch_context)
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


def test_persist_group_memory_turn_writes_host_messages_and_logs(tmp_path):
    gc = _get_group_chat_module()
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    msg = {
        "role": "host",
        "agent_id": "agent-scene-host",
        "content": "请用户补充或继续提问。",
        "timestamp": "2026-05-13T12:30:50+00:00",
        "skill_id": "group-host-general",
    }

    gc._persist_group_memory_turn(
        session_id="group-test",
        msg=msg,
        discussion_goal="数据库中有内容吗",
        input_prompt_summary="这是全部信息了吗",
        app_settings={"group_memory": {"enabled": True, "max_logs": 5, "max_facts": 20}},
        workspace_root=ws,
    )

    messages = sorted((ws / "memory" / "messages").glob("*_agent-scene-host.md"))
    logs = sorted((ws / "memory" / "logs").glob("*_agent-scene-host.md"))
    assert len(messages) == 1
    assert len(logs) == 1

    message_content = messages[0].read_text(encoding="utf-8")
    log_content = logs[0].read_text(encoding="utf-8")
    assert "# Host Message" in message_content
    assert "- agent_id: agent-scene-host" in message_content
    assert "- skill_id: group-host-general" in message_content
    assert "请用户补充或继续提问。" in message_content
    assert "- full_message_ref: memory/messages/2026-05-13T12-30-50+00-00_agent-scene-host.md" in log_content
    assert "## Response Summary" in log_content
    assert "请用户补充或继续提问。" in log_content


def test_append_workspace_image_preview_markdown_keeps_non_image_content():
    gc = _get_group_chat_module()
    base = "工具执行成功。"
    raw = ['{"ok": true, "stdout": "抓取到正文 markdown ..."}']
    out = gc._append_workspace_image_preview_markdown(base, raw)
    assert out == base


def test_append_workspace_image_preview_markdown_appends_image_links():
    gc = _get_group_chat_module()
    base = "已生成图片。"
    raw = ['下载链接：/api/workspaces/s1/files/download?path=generated_images/a.jpg']
    out = gc._append_workspace_image_preview_markdown(base, raw)
    assert "![生成图片1](/api/workspaces/s1/files/download?path=generated_images/a.jpg)" in out


def test_has_auto_continue_signal_detects_continue_intent():
    gc = _get_group_chat_module()
    assert gc._has_auto_continue_signal("接下来我会继续执行下一步。") is True
    assert gc._has_auto_continue_signal("[[AUTO_CONTINUE]] proceeding.") is True


def test_has_auto_continue_signal_defaults_to_handoff_user():
    gc = _get_group_chat_module()
    assert gc._has_auto_continue_signal("这是当前结论，请你确认是否继续。") is False
    assert gc._has_auto_continue_signal("想接项目就别上来问这种空话。") is False
    assert gc._has_auto_continue_signal("你先挑一块具体的，别泛泛而谈。") is False
