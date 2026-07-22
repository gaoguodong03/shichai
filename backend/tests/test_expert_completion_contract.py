import json

from app.agent.expert_completion_contract import (
    parse_expert_completion,
    select_expert_completion,
)


def _payload(
    *,
    content: str = "本轮专家回复已完成。",
    execution_status: str = "succeeded",
    agent_turn: str = "respond",
    skill_session: str = "release",
) -> dict:
    return {
        "execution_status": execution_status,
        "message": {
            "content": content,
            "attachments": [],
            "artifacts": [],
        },
        "next_action": {
            "agent_turn": agent_turn,
            "skill_session": skill_session,
        },
    }


def test_existing_model_json_projects_to_four_internal_objects():
    completion = parse_expert_completion(
        json.dumps(
            _payload(agent_turn="continue", skill_session="keep"),
            ensure_ascii=False,
        )
    )

    assert completion.execution.status == "succeeded"
    assert completion.output.message.content == "本轮专家回复已完成。"
    assert completion.agent_turn.action == "continue"
    assert completion.skill_session.action == "keep"


def test_script_stdout_takes_precedence_over_conflicting_finalizer():
    completion = select_expert_completion(
        final_content=json.dumps(_payload(content="finalizer"), ensure_ascii=False),
        tool_results=[
            {
                "tool_call": {"id": "call-1", "name": "run_skill_script", "kind": "script"},
                "execution_status": "succeeded",
                "output": {
                    "stdout": json.dumps(_payload(content="script"), ensure_ascii=False),
                },
            }
        ],
    )

    assert completion.output.message.content == "script"
