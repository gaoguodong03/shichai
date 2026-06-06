"""场景调度：首轮误招募抑制与决策归一。"""
from app.core.scene_scheduler import finalize_host_scheduler_decision


def test_finalize_clears_recruit_on_first_turn_when_experts_in_room():
    raw = {
        "task_done": True,
        "next_speaker": "user",
        "announcement": "需要补人",
        "suggested_add_agent_ids": ["agent-outside-1"],
        "next_prompt": None,
    }
    dha_list = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        dha_list=dha_list,
        available_to_add=available,
        last_speaker_agent_id=None,
        user_message="我要写一篇关于张雪峰的博客",
        explicit_requested_agent_ids=[],
    )
    assert out.get("suggested_add_agent_ids") == []
    assert out.get("next_speaker") == "user"


def test_finalize_clears_recruit_when_session_has_stale_agent_ids_but_no_resolved_experts():
    """meta 里仍有 agent_id，专家库已删：不应展示「邀请更匹配专家」。"""
    raw = {
        "task_done": True,
        "next_speaker": "user",
        "announcement": "建议邀请写作专家",
        "suggested_add_agent_ids": ["agent-outside-1"],
    }
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-deleted-stale"],
        dha_list=[],
        available_to_add=available,
        last_speaker_agent_id=None,
        user_message="我要写一篇关于张雪峰的博客",
        explicit_requested_agent_ids=[],
    )
    assert out.get("suggested_add_agent_ids") == []
    assert out.get("next_speaker") == "user"


def test_finalize_keeps_recruit_when_zero_members_true_room():
    """真实 0 成员：保留 LLM 的 suggested_add。"""
    raw = {
        "task_done": True,
        "next_speaker": "user",
        "suggested_add_agent_ids": ["agent-outside-1"],
    }
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=[],
        dha_list=[],
        available_to_add=available,
        last_speaker_agent_id=None,
        user_message="帮我写个东西",
        explicit_requested_agent_ids=[],
    )
    assert out.get("suggested_add_agent_ids") == ["agent-outside-1"]


def test_finalize_clears_recruit_after_expert_already_spoke():
    """专家已发言后仍应抑制误招募（旧逻辑在 last_speaker 有值时不再抑制，导致反复邀请）。"""
    raw = {
        "task_done": False,
        "next_speaker": "user",
        "suggested_add_agent_ids": ["agent-outside-1"],
    }
    dha_list = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        dha_list=dha_list,
        available_to_add=available,
        last_speaker_agent_id="agent-a",
        user_message="再润色一下第二段",
        explicit_requested_agent_ids=[],
    )
    assert out.get("suggested_add_agent_ids") == []
    assert out.get("next_speaker") == "user"


def test_finalize_scene_profile_strips_suggested_add():
    raw = {
        "task_done": True,
        "next_speaker": "user",
        "suggested_add_agent_ids": ["agent-outside-1"],
    }
    dha_list = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        dha_list=dha_list,
        available_to_add=available,
        last_speaker_agent_id="agent-a",
        user_message="继续",
        explicit_requested_agent_ids=[],
        orchestration_profile="scene",
    )
    assert out.get("suggested_add_agent_ids") == []


def test_finalize_scene_profile_rejects_outside_next_speaker():
    """场景会话参与者固定：主持人不能把下一发言人指向场景外专家。"""
    raw = {
        "task_done": False,
        "next_speaker": "agent-outside-1",
        "next_prompt": "请场外专家继续。",
        "suggested_add_agent_ids": ["agent-outside-1"],
    }
    dha_list = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        dha_list=dha_list,
        available_to_add=available,
        last_speaker_agent_id=None,
        user_message="继续",
        explicit_requested_agent_ids=[],
        orchestration_profile="scene",
    )
    assert out.get("suggested_add_agent_ids") == []
    assert out.get("next_speaker") == "user"
    assert out.get("interrupt_reason") == "conflict_detected"
