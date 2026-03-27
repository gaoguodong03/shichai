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
    assert "主持人补充指令" not in out


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
