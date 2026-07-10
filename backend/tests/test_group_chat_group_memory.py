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
        context="最近讨论内容",
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
        context="ignored",
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
        context="学生正在讨论 AI 是否替代了本来该被考察的能力。",
        target_agent_name="同伴专家",
    )

    assert "先用 1-2 句确认你理解的子任务" not in out
    assert "复述" not in out
    assert "不要先说明你理解的子任务" in out


def test_persist_group_memory_turn_updates_only_facts_for_assistant(tmp_path):
    gc = _get_memory_prompt_module()
    ws = tmp_path / "ws"
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

    assert not (ws / "memory" / "facts.md").exists()
    assert not (ws / "memory" / "messages").exists()
    assert not (ws / "memory" / "logs").exists()

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

    facts = (ws / "memory" / "facts.md").read_text(encoding="utf-8")
    assert "- 用户希望输出周报" in facts
    assert "- 需要包含趋势图表" in facts
    assert not (ws / "memory" / "messages").exists()
    assert not (ws / "memory" / "logs").exists()


def test_persist_group_memory_turn_updates_index_from_skill_result_artifacts(tmp_path):
    gc = _get_memory_prompt_module()
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)

    assistant_msg = {
        "message_id": "expert-1",
        "speaker": {"type": "expert", "agent_name": "写作专家", "skill": "weekly-report"},
        "message": {"content": "已完成周报初稿，并保存到工作区。"},
        "created_at": "2026-05-13T12:31:50+00:00",
        "skill_result": {
            "execution_status": "succeeded",
            "content": "已完成周报初稿，并保存到工作区。",
            "artifacts": [{"type": "markdown", "name": "周报", "path": "reports/weekly.md"}],
            "next_action": {"agent_turn": "respond", "skill_session": "release"},
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

    index = (ws / "memory" / "index.md").read_text(encoding="utf-8")
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
    raw = ['下载链接：/api/workspaces/s1/files/download?path=generated_images/a.jpg']
    out = gc.append_workspace_image_preview_markdown(base, raw)
    assert "![生成图片1](/api/workspaces/s1/files/download?path=generated_images/a.jpg)" in out


def test_append_workspace_image_preview_markdown_skips_image_already_in_content_from_json_artifact():
    gc = _get_tool_trace_module()
    url = "/api/workspaces/s1/files/download?path=generated_images/a.jpg"
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
    url = "/api/workspaces/s1/files/download?path=generated_images/a.jpg"
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


def test_guard_delivery_claims_replaces_unverified_generation_claim():
    gc = _get_tool_trace_module()
    content = "已生成「板面美食推广图」。\n\n图片链接：generated_images/missing.jpg"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[],
        tool_output_texts=[],
    )

    assert "本轮没有确认文件生成成功" in out
    assert "已生成「板面美食推广图」" not in out
    assert "generated_images/missing.jpg" in out


def test_guard_delivery_claims_replaces_unverified_web_crawler_candidate_claim():
    gc = _get_tool_trace_module()
    content = "候选清单已保存：`web-crawler/候选清单-20250414155900.md`"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[],
        tool_output_texts=[],
    )

    assert "本轮没有确认文件生成成功" in out
    assert "web-crawler/候选清单-20250414155900.md" in out
    assert "候选清单已保存" not in out


def test_guard_delivery_claims_replaces_unverified_root_workspace_file_claim():
    gc = _get_tool_trace_module()
    content = "已生成报告，并保存到工作区：`report.md`"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[],
        tool_output_texts=[],
    )

    assert "本轮没有确认文件生成成功" in out
    assert "report.md" in out
    assert "已生成报告" not in out


def test_guard_delivery_claims_replaces_unverified_saved_root_file_claim():
    gc = _get_tool_trace_module()
    content = "候选清单已保存：`report.md`"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[],
        tool_output_texts=[],
    )

    assert "本轮没有确认文件生成成功" in out
    assert "report.md" in out
    assert "候选清单已保存" not in out


def test_guard_delivery_claims_keeps_successful_workspace_write_claim():
    gc = _get_tool_trace_module()
    content = "已生成周报，并保存到工作区：reports/weekly.md"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "write_workspace_file", "arguments": {"path": "reports/weekly.md"}}],
        tool_output_texts=["已写入当前 Chat 工作区文件：reports/weekly.md"],
    )

    assert out == content


def test_guard_delivery_claims_keeps_successful_root_workspace_write_claim(tmp_path):
    gc = _get_tool_trace_module()
    content = "已生成报告，并保存到工作区：report.md"
    raw_results = ["已写入当前 Chat 工作区文件：report.md"]
    (tmp_path / "report.md").write_text("report", encoding="utf-8")

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "write_workspace_file", "arguments": {"path": "report.md"}}],
        tool_output_texts=raw_results,
        workspace_root=tmp_path,
    )

    assert out == content


def test_guard_delivery_claims_keeps_successful_root_payload_file_claim(tmp_path):
    gc = _get_tool_trace_module()
    content = "已生成文档，并保存到工作区：report.docx"
    raw_results = ['{"execution_status":"succeeded","artifacts":[{"type":"file","name":"报告","path":"report.docx"}]}']
    (tmp_path / "report.docx").write_text("doc", encoding="utf-8")

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "run_skill_script", "arguments": {"path": "report.docx"}}],
        tool_output_texts=raw_results,
        workspace_root=tmp_path,
    )

    assert out == content


def test_guard_delivery_claims_does_not_trust_success_payload_free_text_path(tmp_path):
    gc = _get_tool_trace_module()
    content = "已生成文档，并保存到工作区：report.docx"
    raw_results = ['{"execution_status":"succeeded","output":"report.docx","artifacts":[]}']
    (tmp_path / "report.docx").write_text("doc", encoding="utf-8")

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "run_skill_script", "arguments": {"path": "report.docx"}}],
        tool_output_texts=raw_results,
        workspace_root=tmp_path,
    )

    assert "本轮没有确认文件生成成功" in out
    assert out != content


def test_guard_delivery_claims_rejects_legacy_success_code_payload(tmp_path):
    gc = _get_tool_trace_module()
    content = "已生成文档，并保存到工作区：report.docx"
    raw_results = ['{"result_code":"file.generated","artifacts":{"workspace_path":"report.docx"}}']
    (tmp_path / "report.docx").write_text("doc", encoding="utf-8")

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "run_skill_script", "arguments": {"path": "report.docx"}}],
        tool_output_texts=raw_results,
        workspace_root=tmp_path,
    )

    assert "本轮没有确认文件生成成功" in out
    assert out != content


def test_guard_delivery_claims_requires_existing_file_when_workspace_root_is_available(tmp_path):
    gc = _get_tool_trace_module()
    content = "已生成周报，并保存到工作区：reports/weekly.md"
    raw_results = ["已写入当前 Chat 工作区文件：reports/weekly.md"]

    missing = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "write_workspace_file", "arguments": {"path": "reports/weekly.md"}}],
        tool_output_texts=raw_results,
        workspace_root=tmp_path,
    )
    assert "本轮没有确认文件生成成功" in missing

    target = tmp_path / "reports" / "weekly.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("weekly", encoding="utf-8")

    existing = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "write_workspace_file", "arguments": {"path": "reports/weekly.md"}}],
        tool_output_texts=raw_results,
        workspace_root=tmp_path,
    )
    assert existing == content


def test_guard_delivery_claims_summary_omits_successful_read_file_content():
    gc = _get_tool_trace_module()
    content = "全文已生成完毕，已保存到工作区：蒙太奇是什么-完整草稿-2026062817141600.md"
    raw_results = [
        "错误：文件不存在：蒙太奇是什么-完整草稿-2026062817270900.md。不要继续猜测文件名；请先调用 list_workspace_directory 查看真实路径。",
        "# 《蒙太奇是什么？——从叙事剪辑看懂电影语言》大纲\n\n## 标题建议\n旧大纲内容",
        "# 蒙太奇理論 Montage - 認識電影\n\n资料正文",
    ]

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "read_workspace_file", "arguments": {"path": "蒙太奇是什么-完整草稿-2026062817270900.md"}}],
        tool_output_texts=raw_results,
    )

    assert "本轮没有确认文件生成成功" in out
    assert "错误：文件不存在：蒙太奇是什么-完整草稿-2026062817270900.md" in out
    assert "- 蒙太奇是什么-完整草稿-2026062817141600.md" in out
    assert "已保存到工作区：蒙太奇是什么-完整草稿-2026062817141600.md" not in out
    assert "《蒙太奇是什么？——从叙事剪辑看懂电影语言》大纲" not in out
    assert "蒙太奇理論 Montage" not in out


def test_guard_delivery_claims_ignores_plain_non_file_generation_text():
    gc = _get_tool_trace_module()
    content = "已生成一版讨论思路，下面是正文内容。"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[],
        tool_output_texts=[],
    )

    assert out == content


def test_guard_delivery_claims_ignores_plain_root_filename_reference():
    gc = _get_tool_trace_module()
    content = "已生成一版讨论思路，可以参考 report.md 的结构继续展开。"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[],
        tool_output_texts=[],
    )

    assert out == content


def test_guard_delivery_claims_ignores_writing_plan_after_workspace_read():
    gc = _get_tool_trace_module()
    content = "已生成一版方向确认卡。请确认后我再生成完整正文。"

    out = gc.guard_unverified_delivery_claims(
        content,
        tool_calls=[{"tool": "list_workspace_directory", "arguments": {"path": "web-crawler/materials"}}],
        tool_output_texts=["目录 web-crawler/materials 下的内容（含子目录）：\n方向确认卡"],
    )

    assert out == content


def test_has_auto_continue_signal_detects_continue_intent():
    gc = _get_context_module()
    assert gc.has_auto_continue_signal("接下来我会继续执行下一步。") is True
    assert gc.has_auto_continue_signal("[[AUTO_CONTINUE]] proceeding.") is True


def test_has_auto_continue_signal_defaults_to_handoff_user():
    gc = _get_context_module()
    assert gc.has_auto_continue_signal("这是当前结论，请你确认是否继续。") is False
    assert gc.has_auto_continue_signal("想接项目就别上来问这种空话。") is False
    assert gc.has_auto_continue_signal("你先挑一块具体的，别泛泛而谈。") is False
