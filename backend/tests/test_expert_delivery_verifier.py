import json

import pytest

from app.agent.expert_completion_contract import (
    ExpertExecutionOutcome,
    ExpertFinalStatePayload,
    ExpertOutputSubmission,
)
from app.agent.expert_delivery_verifier import verify_expert_message_delivery
from app.agent.expert_output_publisher import publish_expert_output
from app.agent.messages import AIMessage, HumanMessage, ToolMessage
from app.agent.simple_agent import SimpleAgent
from app.agent.structured_output_contracts import ExpertFinalMessageBody
from app.agent.tool_spec import ToolSpec


def _final_state(*, content: str, path: str) -> AIMessage:
    return AIMessage(
        content=json.dumps(
            {
                "execution_status": "succeeded",
                "message": {
                    "content": content,
                    "attachments": [],
                    "artifacts": [{"type": "markdown", "name": path, "path": path}],
                },
                "next_action": {"agent_turn": "respond", "skill_session": "keep"},
            },
            ensure_ascii=False,
        )
    )


def test_verifier_rejects_missing_artifact_and_saved_claim(tmp_path):
    message = ExpertFinalMessageBody(
        content="已按人物传记类文章规划，并保存首版大纲至工作区 `outline-v1.md`。",
        artifacts=[{"type": "markdown", "name": "outline-v1.md", "path": "outline-v1.md"}],
    )

    verified = verify_expert_message_delivery(
        message,
        tool_results=[],
        workspace_root=tmp_path,
    )

    assert verified.is_verified is False
    assert verified.unverified_paths == ("outline-v1.md",)
    assert verified.message.artifacts == []
    assert "本轮没有确认文件生成成功" in verified.message.content
    assert "已按人物传记类文章规划" not in verified.message.content


def test_verifier_keeps_existing_artifact_with_matching_write_fact(tmp_path):
    (tmp_path / "outline-v1.md").write_text("# 大纲", encoding="utf-8")
    message = ExpertFinalMessageBody(
        content="已保存首版大纲至工作区 `outline-v1.md`。",
        artifacts=[{"type": "markdown", "name": "outline-v1.md", "path": "outline-v1.md"}],
    )

    verified = verify_expert_message_delivery(
        message,
        tool_results=[
            {
                "execution_status": "succeeded",
                "tool_call": {
                    "id": "tc-write",
                    "name": "write_workspace_file",
                    "kind": "workspace",
                    "arguments": {"path": "outline-v1.md"},
                },
                "output": {"content": "已写入当前 Chat 工作区文件：outline-v1.md"},
            }
        ],
        workspace_root=tmp_path,
    )

    assert verified.is_verified is True
    assert verified.message == message


class _RetryClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.index = 0

    def bind_tools(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, _messages):
        response = self.responses[self.index]
        self.index += 1
        return response


class _RetryLLM:
    def __init__(self, responses):
        self.client = _RetryClient(responses)

    def get_client(self):
        return self.client


@pytest.mark.asyncio
async def test_simple_agent_retries_fake_delivery_with_real_workspace_write(tmp_path):
    fake_final = _final_state(
        content="已保存首版大纲至工作区 `outline-v1.md`。",
        path="outline-v1.md",
    )
    write_call = AIMessage(
        content="",
        tool_calls=[
            {
                "id": "tc-write",
                "name": "write_workspace_file",
                "args": {"path": "outline-v1.md", "content": "# 沈腾演艺生涯介绍大纲"},
            }
        ],
    )
    real_final = _final_state(
        content="已保存首版大纲至工作区 `outline-v1.md`。",
        path="outline-v1.md",
    )

    async def _tool_runner(state, _tools):
        call = state["messages"][-1].tool_calls[0]
        (tmp_path / call["args"]["path"]).write_text(call["args"]["content"], encoding="utf-8")
        output = "已写入当前 Chat 工作区文件：outline-v1.md"
        return {
            "messages": [ToolMessage(content=output, tool_call_id=call["id"])],
            "tool_calls": [{"tool": call["name"], "arguments": call["args"]}],
            "tool_results": [
                {
                    "execution_status": "succeeded",
                    "tool_call": {
                        "id": call["id"],
                        "name": call["name"],
                        "kind": "workspace",
                        "arguments": call["args"],
                    },
                    "output": {"content": output},
                }
            ],
            "tool_raw_outputs": [output],
        }

    agent = SimpleAgent(
        llm=_RetryLLM([fake_final, write_call, real_final]),
        tools=[ToolSpec(name="write_workspace_file", description="write")],
        system_prompt="输出 expert_final_state.v2。",
        tool_runner=_tool_runner,
        max_steps=4,
        final_output_model=ExpertFinalStatePayload,
    )

    result = await agent.ainvoke(
        {
            "messages": [HumanMessage(content="生成大纲并保存。")],
            "workspace_root": tmp_path,
        }
    )

    assert (tmp_path / "outline-v1.md").read_text(encoding="utf-8") == "# 沈腾演艺生涯介绍大纲"
    assert [call["tool"] for call in result["tool_calls"]] == ["write_workspace_file"]
    final = ExpertFinalStatePayload.model_validate(json.loads(result["messages"][-1].content))
    assert final.execution_status == "succeeded"
    assert final.message.artifacts[0].path == "outline-v1.md"
    assert any(item.get("source") == "unverified_delivery_retry" for item in result["tool_attempt_debug"])


def test_publisher_fails_closed_when_model_artifact_is_missing(tmp_path, monkeypatch):
    from app.agent import expert_output_publisher as publisher

    monkeypatch.setattr(publisher, "get_workspace_root_path", lambda _session_id: tmp_path)
    monkeypatch.setattr(publisher, "record_group_chat_tool_trace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publisher, "save_group_history", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(publisher, "save_session_definitions", lambda *_args, **_kwargs: None)
    messages = []

    published = publish_expert_output(
        submission=ExpertOutputSubmission(
            message=ExpertFinalMessageBody(
                content="已保存首版大纲至工作区 `outline-v1.md`。",
                artifacts=[{"type": "markdown", "name": "outline-v1.md", "path": "outline-v1.md"}],
            )
        ),
        execution=ExpertExecutionOutcome(status="succeeded"),
        agent_name="文档合著专家",
        skill="文档合著",
        message_id="msg-delivery-guard",
        created_at="2026082812000000",
        group_session_id="session-delivery-guard",
        messages=messages,
        session_definitions={"session-delivery-guard": {}},
        session_item={},
        tool_results=[],
    )

    assert published is not None
    assert published.record["skill_result"] == {"execution_status": "failed"}
    assert not published.record["message"].get("artifacts")
    assert "本轮没有确认文件生成成功" in published.record["message"]["content"]
