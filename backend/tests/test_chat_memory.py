"""测试聊天记忆窗口（最近 10 轮）"""
import pytest
from langchain_core.messages import HumanMessage, AIMessage

# 需在导入 chat 前 mock 或设置 env，避免 QWEN_API_KEY 等依赖
import os
os.environ.setdefault("QWEN_API_KEY", "test-key-for-unit-test")


def _get_chat_module():
    """延迟导入 chat 模块，避免启动时加载 MCP 等"""
    from app.api import chat
    return chat


@pytest.fixture(autouse=True)
def reset_turn_summaries():
    """每个测试前清空 TURN_SUMMARIES，避免跨测试污染"""
    chat = _get_chat_module()
    chat._TURN_SUMMARIES.clear()
    yield
    chat._TURN_SUMMARIES.clear()


class TestAppendTurnSummary:
    """测试 _append_turn_summary：只保留最近 10 轮"""

    def test_append_first_summary(self):
        chat = _get_chat_module()
        chat._append_turn_summary("s1", "第一轮摘要")
        assert chat._TURN_SUMMARIES["s1"] == ["第一轮摘要"]

    def test_append_empty_ignored(self):
        chat = _get_chat_module()
        chat._append_turn_summary("s1", "")
        chat._append_turn_summary("s1", "   ")
        assert "s1" not in chat._TURN_SUMMARIES or chat._TURN_SUMMARIES["s1"] == []

    def test_append_truncates_to_10(self):
        chat = _get_chat_module()
        for i in range(15):
            chat._append_turn_summary("s1", f"第{i+1}轮")
        assert len(chat._TURN_SUMMARIES["s1"]) == 10
        assert chat._TURN_SUMMARIES["s1"][0] == "第6轮"
        assert chat._TURN_SUMMARIES["s1"][-1] == "第15轮"


class TestBuildHistorySummary:
    """测试 _build_history_summary：只取最近 10 轮"""

    def test_empty_history(self):
        chat = _get_chat_module()
        result = chat._build_history_summary("s1", [])
        assert result == ""

    def test_uses_turn_summaries_when_available(self):
        chat = _get_chat_module()
        chat._TURN_SUMMARIES["s1"] = ["摘要A", "摘要B"]
        result = chat._build_history_summary("s1", [HumanMessage(content="x"), AIMessage(content="y")])
        assert "第1轮：摘要A" in result
        assert "第2轮：摘要B" in result

    def test_turn_summaries_truncated_to_10(self):
        chat = _get_chat_module()
        chat._TURN_SUMMARIES["s1"] = [f"摘要{i}" for i in range(15)]
        # 传非空 history 才能进入函数体（ empty 会直接 return ""）
        history = [HumanMessage(content="x"), AIMessage(content="y")]
        result = chat._build_history_summary("s1", history)
        # 应只含最近 10 轮（摘要5～14）
        assert "第1轮：摘要5" in result
        assert "第10轮：摘要14" in result
        assert "摘要0" not in result
        assert "摘要4" not in result

    def test_fallback_from_history_truncated_to_10(self):
        chat = _get_chat_module()
        # 无 TURN_SUMMARIES，走回退路径
        history = []
        for i in range(22):
            history.append(HumanMessage(content=f"用户第{i+1}条"))
            history.append(AIMessage(content=f"助手第{i+1}条"))
        result = chat._build_history_summary("s1", history)
        # 应只含最近 10 轮
        assert "第10轮：" in result
        assert "第11轮：" not in result
        assert "用户第13条" in result  # 第 13 轮在最近 10 轮内（第13～22轮）
        assert "用户第3条" not in result  # 第 3 轮超出窗口

    def test_fallback_single_turn(self):
        chat = _get_chat_module()
        history = [HumanMessage(content="你好"), AIMessage(content="你好！")]
        result = chat._build_history_summary("s1", history)
        assert "第1轮：" in result
        assert "用户：你好" in result
        assert "助手：你好！" in result


class TestHistoryWindowConstant:
    """测试 _HISTORY_WINDOW_TURNS 常量"""

    def test_window_is_10(self):
        chat = _get_chat_module()
        assert chat._HISTORY_WINDOW_TURNS == 10
