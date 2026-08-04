from app.agent import group_context


def test_messages_to_expert_context_filters_repeated_technical_errors():
    messages = [
        {"speaker": {"type": "user"}, "message": {"content": "请分析数据"}},
        {"speaker": {"type": "expert", "agent_name": "专家A"}, "message": {"content": "Error code: 400 context length is only"}},
        {"speaker": {"type": "expert", "agent_name": "专家A"}, "message": {"content": "有效业务结论"}},
        {"speaker": {"type": "expert", "agent_name": "专家A"}, "message": {"content": "有效业务结论"}},
    ]

    text = group_context.messages_to_expert_context(messages)

    assert "请分析数据" in text
    assert "有效业务结论" in text
    assert "Error code: 400" not in text
    assert text.count("有效业务结论") == 1


def test_messages_to_expert_context_marks_history_as_reference_not_repeat_task():
    messages = [
        {"speaker": {"type": "expert", "agent_name": "专家A"}, "message": {"content": "上一轮已经给出的完整结论"}},
        {"speaker": {"type": "user"}, "message": {"content": "这里再补充一个新的约束"}},
    ]

    text = group_context.messages_to_expert_context(messages)

    assert "本轮用户输入" in text
    assert "优先" in text
    assert "仅供承接" in text
    assert "不要复述" in text
    assert "上一轮已经给出的完整结论" in text
    assert "这里再补充一个新的约束" in text


def test_messages_to_context_preserves_tail_when_truncating_long_messages():
    long_material = (
        "材料包开头：" + ("案例事实。" * 80) + "\n"
        "覆盖摘要：材料覆盖规则、案例和争议。\n"
        "张力摘要：公平与工具素养之间存在冲突。\n"
        "材料包已整理到这里，交给教师做材料引导。"
    )

    text = group_context.messages_to_context(
        [{"speaker": {"type": "expert", "agent_name": "材料专家"}, "message": {"content": long_material}}],
        max_chars_per_message=180,
    )

    assert "材料包开头" in text
    assert "中间内容已截断" in text
    assert "材料包已整理到这里，交给教师做材料引导" in text


def test_scheduler_memory_prompt_keeps_only_latest_host_message():
    messages = [
        {"speaker": {"type": "user"}, "message": {"content": "请开始梳理事实"}},
        {"speaker": {"type": "host", "agent_name": "主持人"}, "message": {"content": "旧的主持人问题"}},
        {"speaker": {"type": "expert", "agent_name": "事实专家"}, "message": {"content": "请确认状态推断"}},
        {"speaker": {"type": "user"}, "message": {"content": "确认"}},
        {"speaker": {"type": "host", "agent_name": "主持人"}, "message": {"content": "请回答当前事实问题"}},
        {"speaker": {"type": "user"}, "message": {"content": "再次确认"}},
    ]

    text = group_context.scheduler_memory_prompt("session-1", messages)

    assert "旧的主持人问题" not in text
    assert "【主持人】请回答当前事实问题" in text
    assert "【事实专家】请确认状态推断" in text
    assert text.count("【主持人】") == 1


def test_normalize_discussion_goal_removes_frontend_prefix():
    assert group_context.normalize_discussion_goal("【讨论目标】\n写一份方案") == "写一份方案"


def test_title_from_first_message_limits_text():
    assert group_context.title_from_first_message("【讨论目标】\n这是一个很长很长的标题", max_chars=6) == "这是一个很长"


def test_messages_to_context_ignores_legacy_top_level_content():
    text = group_context.messages_to_context(
        [
            {
                "role": "user",
                "content": "旧顶层正文不应进入上下文",
                "speaker": {"type": "user"},
                "message": {"content": "标准正文"},
            },
            {
                "role": "assistant",
                "content": "旧助手正文不应进入上下文",
                "speaker": {"type": "expert", "agent_name": "专家A"},
                "message": {"content": ""},
            },
            {
                "role": "assistant",
                "agent_name": "旧专家",
                "content": "只有旧字段的正文不应进入上下文",
            },
        ]
    )

    assert "标准正文" in text
    assert "旧顶层正文不应进入上下文" not in text
    assert "旧助手正文不应进入上下文" not in text
    assert "只有旧字段的正文不应进入上下文" not in text
    assert "旧专家" not in text
    assert "【助手】" not in text
