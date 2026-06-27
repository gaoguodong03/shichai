from app.agent.group_chat_soft_stop import _evaluate_soft_stop


def test_soft_stop_does_not_count_recovered_material_turn_raw_tool_errors():
    state = {
        "prev_content": "",
        "prev_speaker": "",
        "low_increment_streak": 0,
        "repeat_conclusion_streak": 0,
        "tool_failure_streak": 0,
    }

    first_reason = _evaluate_soft_stop(
        state,
        current_speaker="agent-material",
        full_content="当前步骤失败：call_api\n\n错误：无法解析请求的域名（网络或 DNS 异常）。",
        tool_raw_results=["错误：无法解析请求的域名（网络或 DNS 异常）。"],
    )
    assert first_reason is None
    assert state["tool_failure_streak"] == 1

    recovered_reason = _evaluate_soft_stop(
        state,
        current_speaker="agent-material",
        full_content=(
            "# 材料包：AI在学生竞赛中的应用——规则、边界与争议\n\n"
            "因联网检索暂时不可用，以下材料基于模型已知的公开案例、"
            "权威机构规则和学界讨论整理。\n\n"
            "## 材料一：竞赛主办方规则对比\n"
            "ICPC与Kaggle的规则差异揭示了竞赛类型与AI使用政策的关系。\n\n"
            "## 覆盖摘要\n"
            "本材料包覆盖规则层面、实践层面和理念层面的核心冲突。"
        ),
        tool_raw_results=[
            "状态码: 404\n\nError 404 - Oops, the page you're looking for is no longer here",
            "状态码: 404\n\nSorry - we haven't been able to serve the page you asked for.",
        ],
    )

    assert recovered_reason is None
    assert state["tool_failure_streak"] == 0
