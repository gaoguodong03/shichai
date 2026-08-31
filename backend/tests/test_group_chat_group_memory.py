"""群聊记忆开关与默认动作提示测试。"""
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


def test_action_prompt_default_when_memory_disabled():
    gc = _get_memory_prompt_module()
    app_settings = {"group_memory": {"enabled": False}}
    out = gc._build_action_prompt_with_memory(
        session_id="group-test",
        target_agent_name="专家A",
        discussion_goal="写周报",
        input_prompt="最近讨论内容",
        app_settings=app_settings,
        host_next_action="",
    )
    assert "最近几轮讨论内容" in out
    assert "写周报" in out


def test_action_prompt_uses_memory_when_available(monkeypatch):
    gc = _get_memory_prompt_module()
    from app.agent import group_chat_memory_prompt

    def _fake_dispatch_context(*args, **kwargs):
        return {
            "has_memory": True,
            "rendered": "【关键事实】\n- 已确认标题",
        }

    monkeypatch.setattr(group_chat_memory_prompt, "build_dispatch_context", _fake_dispatch_context)
    out = gc._build_action_prompt_with_memory(
        session_id="group-test",
        target_agent_name="专家A",
        discussion_goal="写周报",
        input_prompt="ignored",
        app_settings={"group_memory": {"enabled": True, "dispatch_top_k": 2, "max_facts": 20}},
        host_next_action="补充要求",
    )
    assert "关键事实" in out
    assert "补充要求" in out
    assert "主持人本轮指派" in out
    assert "复述当前你要完成的子任务" not in out
    assert "复述" not in out
    assert "我这轮要做" not in out
    assert "直接进入本轮角色发言" in out


def test_action_prompt_short_default_avoids_meta_task_preface():
    gc = _get_memory_prompt_module()

    out = gc._ensure_structured_action_prompt(
        prompt="请说明边界",
        discussion_goal="伴学研讨",
        input_prompt="学生正在讨论 AI 是否替代了本来该被考察的能力。",
        target_agent_name="同伴专家",
    )

    assert "先用 1-2 句确认你理解的子任务" not in out
    assert "复述" not in out
    assert "不要先说明你理解的子任务" in out


def test_persist_group_memory_turn_updates_only_facts_for_assistant(tmp_path):
    gc = _get_memory_prompt_module()
    session_root = tmp_path / "session"
    ws = session_root / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    host_msg = {
        "message_id": "host-1",
        "speaker": {"type": "host", "agent_name": "场景主持人"},
        "content": "请用户补充或继续提问。",
        "created_at": "2026-05-13T12:30:50+00:00",
    }

    gc._persist_group_memory_turn(
        session_id="group-test",
        msg=host_msg,
        discussion_goal="数据库中有内容吗",
        input_prompt_summary="这是全部信息了吗",
        app_settings={"group_memory": {"enabled": True, "max_logs": 5, "max_facts": 20}},
        workspace_root=ws,
    )

    assert not (session_root / "memory" / "facts.md").exists()
    assert not (session_root / "memory" / "messages").exists()
    assert not (session_root / "memory" / "logs").exists()
    assert not (ws / "memory").exists()

    assistant_msg = {
        "message_id": "expert-1",
        "speaker": {"type": "expert", "agent_name": "数据专家", "skill": "weekly-report"},
        "message": {"content": "- 用户希望输出周报\n- 需要包含趋势图表"},
        "created_at": "2026-05-13T12:31:50+00:00",
    }
    gc._persist_group_memory_turn(
        session_id="group-test",
        msg=assistant_msg,
        discussion_goal="数据库中有内容吗",
        input_prompt_summary="这是全部信息了吗",
        app_settings={"group_memory": {"enabled": True, "max_logs": 5, "max_facts": 20}},
        workspace_root=ws,
    )

    assert not (ws / "memory").exists()
    facts = (session_root / "memory" / "facts.md").read_text(encoding="utf-8")
    assert "- 用户希望输出周报" in facts
    assert "- 需要包含趋势图表" in facts
    assert not (session_root / "memory" / "messages").exists()
    assert not (session_root / "memory" / "logs").exists()


def test_persist_group_memory_turn_updates_index_from_message_artifacts(tmp_path):
    gc = _get_memory_prompt_module()
    session_root = tmp_path / "session"
    ws = session_root / "workspace"
    ws.mkdir(parents=True, exist_ok=True)

    assistant_msg = {
        "message_id": "expert-1",
        "speaker": {"type": "expert", "agent_name": "写作专家", "skill": "weekly-report"},
        "message": {
            "content": "已完成周报初稿，并保存到工作区。",
            "artifacts": [{"type": "markdown", "name": "周报", "path": "reports/weekly.md"}],
        },
        "created_at": "2026-05-13T12:31:50+00:00",
        "skill_result": {
            "execution_status": "succeeded",
        },
    }

    gc._persist_group_memory_turn(
        session_id="group-test",
        msg=assistant_msg,
        discussion_goal="输出周报",
        input_prompt_summary="请写周报",
        app_settings={"group_memory": {"enabled": True, "max_logs": 5, "max_facts": 20}},
        workspace_root=ws,
    )

    assert not (ws / "memory").exists()
    index = (session_root / "memory" / "index.md").read_text(encoding="utf-8")
    assert "agent_name: 写作专家" in index
    assert "skill: weekly-report" in index
    assert "summary: 已完成周报初稿，并保存到工作区。" in index
    assert "- reports/weekly.md" in index

def test_append_workspace_image_preview_markdown_keeps_non_image_content():
    gc = _get_tool_trace_module()
    base = "工具执行成功。"
    raw = ['{"ok": true, "stdout": "抓取到正文 markdown ..."}']
    out = gc.append_workspace_image_preview_markdown(base, raw)
    assert out == base


def test_append_workspace_image_preview_markdown_appends_image_links():
    gc = _get_tool_trace_module()
    base = "已生成图片。"
    raw = ['下载链接：/api/sessions/s1/workspace/files/download?path=generated_images/a.jpg']
    out = gc.append_workspace_image_preview_markdown(base, raw)
    assert "![生成图片1](/api/sessions/s1/workspace/files/download?path=generated_images/a.jpg)" in out


def test_append_workspace_image_preview_markdown_skips_image_already_in_content_from_json_artifact():
    gc = _get_tool_trace_module()
    url = "/api/sessions/s1/workspace/files/download?path=generated_images/a.jpg"
    base = f"已生成图片。\n\n![AI配图]({url})"
    raw = [
        (
            '{"execution_status":"succeeded","artifacts":{'
            f'"output":"{url}","download_url":"{url}",'
            f'"markdown":"![生成图片]({url})"'
            "}}"
        )
    ]

    out = gc.append_workspace_image_preview_markdown(base, raw)

    assert out == base
    assert "生成图片1" not in out


def test_append_workspace_image_preview_markdown_trims_json_delimiters_from_image_url():
    gc = _get_tool_trace_module()
    url = "/api/sessions/s1/workspace/files/download?path=generated_images/a.jpg"
    raw = [
        (
            '{"execution_status":"succeeded","artifacts":{'
            f'"output":"{url}","download_url":"{url}"'
            "}}"
        )
    ]

    out = gc.append_workspace_image_preview_markdown("已生成图片。", raw)

    assert f"![生成图片1]({url})" in out
    assert '\",' not in out


def test_has_auto_continue_signal_detects_continue_intent():
    gc = _get_context_module()
    assert gc.has_auto_continue_signal("接下来我会继续执行下一步。") is True
    assert gc.has_auto_continue_signal("[[AUTO_CONTINUE]] proceeding.") is True


def test_has_auto_continue_signal_defaults_to_handoff_user():
    gc = _get_context_module()
    assert gc.has_auto_continue_signal("这是当前结论，请你确认是否继续。") is False
    assert gc.has_auto_continue_signal("想接项目就别上来问这种空话。") is False
    assert gc.has_auto_continue_signal("你先挑一块具体的，别泛泛而谈。") is False
