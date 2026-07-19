import inspect

from app.agent.expert_completion_contract import (
    ExpertExecutionOutcome,
    ExpertOutputSubmission,
)
from app.agent.expert_output_publisher import build_expert_message_record
from app.agent.structured_output_contracts import ExpertFinalMessageBody


def test_build_expert_message_record_uses_output_and_execution_only():
    published = build_expert_message_record(
        submission=ExpertOutputSubmission(
            message=ExpertFinalMessageBody(
                content="已完成本轮结果。",
                artifacts=[{"type": "markdown", "name": "结果", "path": "result.md"}],
            )
        ),
        execution=ExpertExecutionOutcome(status="succeeded"),
        agent_name="信息检索专家",
        skill="research",
        message_id="msg-expert-1",
        created_at="2026071900000000",
    )

    assert published is not None
    assert published.record["message"]["content"] == "已完成本轮结果。"
    assert published.record["skill_result"] == {"execution_status": "succeeded"}


def test_output_publisher_does_not_import_control_directives():
    source = inspect.getsource(__import__("app.agent.expert_output_publisher", fromlist=["*"]))

    assert "AgentTurnDirective" not in source
    assert "SkillSessionDirective" not in source
    assert "next_action" not in source
