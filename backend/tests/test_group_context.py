from app.agent import group_context


def test_messages_to_expert_context_filters_repeated_technical_errors():
    messages = [
        {"role": "user", "content": "请分析数据"},
        {"role": "assistant", "agent_id": "agent-a", "content": "Error code: 400 context length is only"},
        {"role": "assistant", "agent_id": "agent-a", "content": "有效业务结论"},
        {"role": "assistant", "agent_id": "agent-a", "content": "有效业务结论"},
    ]

    text = group_context.messages_to_expert_context(messages)

    assert "请分析数据" in text
    assert "有效业务结论" in text
    assert "Error code: 400" not in text
    assert text.count("有效业务结论") == 1


def test_messages_to_context_preserves_tail_when_truncating_long_messages():
    long_material = (
        "材料包开头：" + ("案例事实。" * 80) + "\n"
        "覆盖摘要：材料覆盖规则、案例和争议。\n"
        "张力摘要：公平与工具素养之间存在冲突。\n"
        "材料包已整理到这里，交给教师做材料引导。"
    )

    text = group_context.messages_to_context(
        [{"role": "assistant", "agent_id": "agent-material", "content": long_material}],
        max_chars_per_message=180,
    )

    assert "材料包开头" in text
    assert "中间内容已截断" in text
    assert "材料包已整理到这里，交给教师做材料引导" in text


def test_normalize_discussion_goal_removes_frontend_prefix():
    assert group_context.normalize_discussion_goal("【讨论目标】\n写一份方案") == "写一份方案"


def test_title_from_first_message_limits_text():
    assert group_context.title_from_first_message("【讨论目标】\n这是一个很长很长的标题", max_chars=6) == "这是一个很长"
