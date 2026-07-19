from app.agent.expert_completion_contract import SkillSessionDirective
from app.agent.skill_session_manager import (
    apply_skill_session,
    skill_session_for_expert,
)


def test_keep_preserves_independent_bindings_for_multiple_experts():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}

    changed = apply_skill_session(
        state,
        agent_name="写作专家",
        skill="writer",
        directive=SkillSessionDirective(action="keep"),
    )

    assert changed is True
    assert state["skill_sessions"] == {
        "检索专家": {"skill": "research"},
        "写作专家": {"skill": "writer"},
    }


def test_release_removes_only_current_expert_binding():
    state = {
        "skill_sessions": {
            "检索专家": {"skill": "research"},
            "写作专家": {"skill": "writer"},
        }
    }

    changed = apply_skill_session(
        state,
        agent_name="写作专家",
        skill="writer",
        directive=SkillSessionDirective(action="release"),
    )

    assert changed is True
    assert state == {"skill_sessions": {"检索专家": {"skill": "research"}}}


def test_binding_selects_skill_without_returning_a_route():
    state = {"skill_sessions": {"检索专家": {"skill": "research"}}}

    selected = skill_session_for_expert(
        state,
        expert_agent_name="检索专家",
        expert_skills=["research", "browser"],
    )

    assert selected == "research"


def test_invalid_binding_is_removed_for_only_that_expert():
    state = {
        "skill_sessions": {
            "检索专家": {"skill": "removed-skill"},
            "写作专家": {"skill": "writer"},
        }
    }

    selected = skill_session_for_expert(
        state,
        expert_agent_name="检索专家",
        expert_skills=["research"],
    )

    assert selected is None
    assert state == {"skill_sessions": {"写作专家": {"skill": "writer"}}}
