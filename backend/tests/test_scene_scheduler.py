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
    agent_profiles = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        agent_profiles=agent_profiles,
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
        agent_profiles=[],
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
        agent_profiles=[],
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
    agent_profiles = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        agent_profiles=agent_profiles,
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
    agent_profiles = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        agent_profiles=agent_profiles,
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
    agent_profiles = [{"agent_id": "agent-a", "name": "写作", "role": "文字"}]
    available = [{"agent_id": "agent-outside-1", "name": "外", "role": "x"}]
    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-a"],
        agent_profiles=agent_profiles,
        available_to_add=available,
        last_speaker_agent_id=None,
        user_message="继续",
        explicit_requested_agent_ids=[],
        orchestration_profile="scene",
    )
    assert out.get("suggested_add_agent_ids") == []
    assert out.get("next_speaker") == "user"
    assert out.get("interrupt_reason") == "conflict_detected"


def test_finalize_scene_keeps_host_decision_without_banter_specific_material_advance():
    """通用主流程不硬编码伴学研讨阶段推进，场景流转由场景 Skill 自己表达。"""
    raw = {
        "task_done": True,
        "next_speaker": "agent-material",
        "reason": "主持人已输出调度状态，平台已保存为后台状态（阶段2：材料包）",
        "announcement": "下面由 伴学研讨——材料搜索与研究 发言。",
        "next_prompt": "请材料研究员继续整理材料包。",
    }
    agent_profiles = [
        {
            "agent_id": "agent-teacher",
            "name": "伴学研讨——引导教学的教师",
            "role": "伴学研讨中的教师，负责选题、材料引导、教师追问与最终点评。",
        },
        {
            "agent_id": "agent-material",
            "name": "伴学研讨——材料搜索与研究",
            "role": "在伴学研讨前搜索、研究材料",
        },
    ]

    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-teacher", "agent-material"],
        agent_profiles=agent_profiles,
        available_to_add=[],
        last_speaker_agent_id="agent-material",
        user_message="我了解这三个材料了",
        explicit_requested_agent_ids=[],
        orchestration_profile="scene",
    )

    assert out.get("next_speaker") == "agent-material"
    assert out.get("phase") == "executing"
    assert out.get("reason") == raw["reason"]
    assert out.get("next_prompt") == raw["next_prompt"]


def test_finalize_scene_keeps_user_pause_without_banter_specific_material_advance():
    raw = {
        "task_done": True,
        "next_speaker": "user",
        "reason": "主持人已输出调度状态，平台已保存为后台状态（阶段2：材料包）",
        "announcement": "请用户继续发言。",
    }
    agent_profiles = [
        {
            "agent_id": "agent-teacher",
            "name": "伴学研讨——引导教学的教师",
            "role": "伴学研讨中的教师，负责选题、材料引导、教师追问与最终点评。",
        },
        {
            "agent_id": "agent-material",
            "name": "伴学研讨——材料搜索与研究",
            "role": "在伴学研讨前搜索、研究材料",
        },
    ]

    out = finalize_host_scheduler_decision(
        raw,
        agent_ids=["agent-teacher", "agent-material"],
        agent_profiles=agent_profiles,
        available_to_add=[],
        last_speaker_agent_id="agent-material",
        user_message="",
        explicit_requested_agent_ids=[],
        orchestration_profile="scene",
    )

    assert out.get("next_speaker") == "user"
    assert out.get("reason") == raw["reason"]
