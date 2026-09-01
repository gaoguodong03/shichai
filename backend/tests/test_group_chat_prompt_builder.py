"""群聊上下文组装边界测试。"""


def test_request_user_text_keeps_structured_target_out_of_user_body():
    from app.agent.group_chat_request_inputs import request_user_text
    from app.agent.session_contracts import GroupChatRequest
    from app.agent.message_contracts import WorkspaceAttachment

    request = GroupChatRequest(
        message_id="msg-user-1",
        message="请汇总这份材料",
        attachments=[WorkspaceAttachment(type="workspace_file", path="docs/input.md", name="input.md")],
        target_agent_name="资料专家",
    )

    text = request_user_text(request)

    assert "请汇总这份材料" in text
    assert "【工作区附件】" in text
    assert "docs/input.md" in text
    assert "资料专家" not in text
    assert "本轮指定专家" not in text


def test_expert_turn_prompt_keeps_host_task_and_user_input_without_memory(monkeypatch):
    from app.agent import group_chat_memory_prompt
    from app.agent.group_chat_prompt_builder import build_expert_turn_prompt

    def _fake_dispatch_context(*args, **kwargs):
        return {"has_memory": False, "rendered": ""}

    monkeypatch.setattr(group_chat_memory_prompt, "build_dispatch_context", _fake_dispatch_context)

    bundle = build_expert_turn_prompt(
        session_id="group-test",
        target_agent_name="文档合著专家v1.1",
        discussion_goal="开始写报告",
        user_message="开始写报告",
        memory_prompt="以下最近讨论仅供承接上下文；本轮用户输入优先。\n\n【用户】开始写报告",
        app_settings={"group_memory": {"enabled": True, "dispatch_top_k": 3, "max_facts": 20}},
        next_action="请基于用户目标“智能软件工程及伦理”报告，按文档合著v1.1流程推进写作。",
    )

    assert "【主持人本轮指派" in bundle.user_content
    assert "智能软件工程及伦理" in bundle.user_content
    assert "【本轮用户输入】\n开始写报告" in bundle.user_content
    assert "【输入依据】" in bundle.user_content
    assert "【最近讨论】" not in bundle.user_content
    assert bundle.user_content.count("以下最近讨论仅供承接上下文") == 1
    assert bundle.debug["has_next_action"] is True
    assert bundle.debug["has_user_message"] is True


def test_expert_turn_prompt_promotes_current_host_task_even_when_same_text_is_in_history(monkeypatch):
    from app.agent import group_chat_memory_prompt
    from app.agent.group_chat_prompt_builder import build_expert_turn_prompt

    monkeypatch.setattr(
        group_chat_memory_prompt,
        "build_dispatch_context",
        lambda *args, **kwargs: {"has_memory": False, "rendered": ""},
    )
    host_task = "请资源管理专家处理用户发布 operation.md 的需求。"
    recent = (
        "以下最近讨论仅供承接上下文；本轮用户输入优先。\n\n"
        "【用户】我希望发布以下文件。\n\n"
        f"【主持人】{host_task}\n\n"
        "【资源管理专家】请确认发布形式。\n\n"
        "【用户】渲染为网页正文（富文本）"
    )

    bundle = build_expert_turn_prompt(
        session_id="group-resource",
        target_agent_name="资源管理专家",
        discussion_goal="渲染为网页正文（富文本）",
        user_message="渲染为网页正文（富文本）",
        memory_prompt=recent,
        app_settings={"group_memory": {"enabled": True}},
        next_action=host_task,
    )

    assert bundle.user_content.startswith("【主持人本轮指派")
    assert bundle.user_content.count(host_task) == 2
    assert bundle.user_content.count("以下最近讨论仅供承接上下文") == 1
    assert "【最近讨论】" not in bundle.user_content


def test_expert_turn_prompt_marks_absent_new_user_input_explicitly(monkeypatch):
    from app.agent import group_chat_memory_prompt
    from app.agent.group_chat_prompt_builder import build_expert_turn_prompt

    monkeypatch.setattr(
        group_chat_memory_prompt,
        "build_dispatch_context",
        lambda *args, **kwargs: {"has_memory": False, "rendered": ""},
    )

    bundle = build_expert_turn_prompt(
        session_id="group-resource",
        target_agent_name="资源管理专家",
        discussion_goal="发布文档",
        user_message="",
        memory_prompt="【资源管理专家】上一步已经完成。",
        app_settings={"group_memory": {"enabled": True}},
        next_action="继续处理主持人明确分配的下一阶段任务。",
    )

    assert "【本轮用户输入】\n（无）" in bundle.user_content


def test_expert_turn_prompt_direct_user_branch_uses_same_builder():
    from app.agent.group_chat_prompt_builder import build_expert_turn_prompt

    bundle = build_expert_turn_prompt(
        session_id="group-test",
        target_agent_name="资料专家",
        discussion_goal="查资料",
        user_message="帮我找三篇论文",
        memory_prompt="【用户】帮我找三篇论文",
        app_settings={"group_memory": {"enabled": False}},
        next_action="",
    )

    assert "【群聊讨论目标】\n查资料" in bundle.user_content
    assert "【本轮用户输入】\n帮我找三篇论文" in bundle.user_content
    assert "【最近讨论】" in bundle.user_content
    assert "请紧扣讨论目标发言" in bundle.user_content
    assert bundle.task_text == "请紧扣讨论目标发言，不要偏离主题。"
