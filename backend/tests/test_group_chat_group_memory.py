"""群聊记忆开关与回退路径测试。"""
import json
import os
from types import SimpleNamespace

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
            "rendered": "【关键事实】\n- 已确认标题",
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


def test_persist_group_memory_turn_updates_only_facts_for_assistant(tmp_path):
    gc = _get_group_chat_module()
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


def test_log_llm_roundtrip_writes_session_workspace_jsonl(tmp_path):
    gc = _get_group_chat_module()
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

    trace_file = ws / "memory" / "llm_roundtrips.jsonl"
    rows = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 1
    assert rows[0]["phase"] == "host_decide"
    assert rows[0]["session_id"] == "group-test"
    assert rows[0]["input_messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户提示"},
    ]
    assert rows[0]["output"] == {"content": "模型输出"}
    assert rows[0]["agent_id"] == "agent-host"
    assert rows[0]["model"] == "qwen3"


def test_expert_turn_model_name_uses_runtime_llm_not_free_variable():
    gc = _get_group_chat_module()
    runtime = SimpleNamespace(llm=SimpleNamespace(model="runtime-model"))

    assert gc._expert_runtime_model_name(runtime) == "runtime-model"


def test_persist_expert_turn_task_files_materializes_speaker_task(tmp_path, monkeypatch):
    gc = _get_group_chat_module()
    monkeypatch.setattr(gc, "get_workspace_root_path", lambda session_id: tmp_path)

    gc._persist_expert_turn_task_files(
        session_id="group-test",
        next_speaker="agent-teacher",
        task_text="请正式开启研讨并提出首个问题。",
        dha_map={"agent-teacher": {"name": "教师"}},
    )

    assert (tmp_path / "speaker_task.txt").read_text(encoding="utf-8") == "请正式开启研讨并提出首个问题。\n"
    assert (tmp_path / "next_speaker.txt").read_text(encoding="utf-8") == "教师\n"


def test_host_decision_from_workspace_files_uses_persisted_state(tmp_path, monkeypatch):
    gc = _get_group_chat_module()
    monkeypatch.setattr(gc, "get_workspace_root_path", lambda session_id: tmp_path)
    (tmp_path / "current_phase.txt").write_text("阶段1：选题\n", encoding="utf-8")
    (tmp_path / "next_speaker.txt").write_text("伴学研讨——引导教学的教师\n", encoding="utf-8")
    (tmp_path / "speaker_task.txt").write_text("请开场并提出引导性问题。\n", encoding="utf-8")

    decision = gc._host_decision_from_workspace_files(
        "group-test",
        [
            {
                "agent_id": "agent-teacher",
                "name": "伴学研讨——引导教学的教师",
                "role": "教师",
            }
        ],
    )

    assert decision is not None
    assert decision["next_speaker"] == "agent-teacher"
    assert decision["next_prompt"] == "请开场并提出引导性问题。"
    assert "阶段1：选题" in decision["reason"]


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
