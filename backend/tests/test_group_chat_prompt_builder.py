"""群聊上下文组装边界测试。"""


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
        recent_context="以下最近讨论仅供承接上下文；本轮用户输入优先。\n\n【用户】开始写报告",
        app_settings={"group_memory": {"enabled": True, "dispatch_top_k": 3, "max_facts": 20}},
        speaker_task="请基于用户目标“智能软件工程及伦理”报告，按文档合著v1.1流程推进写作。",
    )

    assert "【主持人本轮指派" in bundle.user_content
    assert "智能软件工程及伦理" in bundle.user_content
    assert "【本轮用户输入】\n开始写报告" in bundle.user_content
    assert "【最近讨论】" in bundle.user_content
    assert bundle.debug["has_speaker_task"] is True
    assert bundle.debug["has_user_message"] is True


def test_expert_turn_prompt_direct_user_branch_uses_same_builder():
    from app.agent.group_chat_prompt_builder import build_expert_turn_prompt

    bundle = build_expert_turn_prompt(
        session_id="group-test",
        target_agent_name="资料专家",
        discussion_goal="查资料",
        user_message="帮我找三篇论文",
        recent_context="【用户】帮我找三篇论文",
        app_settings={"group_memory": {"enabled": False}},
        speaker_task="",
    )

    assert "【群聊讨论目标】\n查资料" in bundle.user_content
    assert "【本轮用户输入】\n帮我找三篇论文" in bundle.user_content
    assert "【最近讨论】" in bundle.user_content
    assert "请紧扣讨论目标发言" in bundle.user_content
    assert bundle.task_text == "请紧扣讨论目标发言，不要偏离主题。"
