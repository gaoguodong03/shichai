from app.agent import group_host_decision as hd


def test_extract_host_scheduler_state_from_json_block():
    text = """安排如下：
```json
{"current_phase":"阶段1","next_speaker":"教师","speaker_task":"给出主题"}
```"""

    out = hd.extract_host_scheduler_state(text)

    assert out == {
        "current_phase": "阶段1",
        "next_speaker": "教师",
        "speaker_task": "给出主题",
    }


def test_forced_at_mention_matches_agent_name():
    agents = [{"agent_id": "agent-teacher", "name": "教师", "role": "出题"}]

    assert hd.extract_forced_at_mention_agent_id("@教师 请继续", agents) == "agent-teacher"


def test_host_decision_from_scheduler_state_maps_user():
    out = hd.host_decision_from_scheduler_state(
        {"current_phase": "补充信息", "next_speaker": "user", "speaker_task": "请补充信息"},
        [],
    )

    assert out["next_speaker"] == "user"
    assert out["current_phase"] == "补充信息"
    assert out["speaker_task"] == "请补充信息"
    assert out.get("next_prompt") is None
    assert out["decision_source"] == "host_scheduler_state"


def test_host_decision_from_scheduler_state_maps_end():
    out = hd.host_decision_from_scheduler_state(
        {
            "current_phase": "收尾",
            "next_speaker": "end",
            "speaker_task": "任务已完成，本轮会话结束。",
        },
        [],
    )

    assert out["next_speaker"] == "end"
    from app.agent.group_chat_host_messages import HOST_END_MESSAGE

    assert out["announcement"] == HOST_END_MESSAGE
    assert out["decision_source"] == "host_scheduler_state"


def test_host_decision_from_scheduler_state_rejects_noncanonical_user_and_end_values():
    assert hd.host_decision_from_scheduler_state(
        {"current_phase": "", "next_speaker": "用户", "speaker_task": "请补充信息"},
        [],
    ) is None
    assert hd.host_decision_from_scheduler_state(
        {"current_phase": "", "next_speaker": "结束研讨", "speaker_task": ""},
        [],
    ) is None


def test_host_decision_from_scheduler_state_end_default_is_generic():
    out = hd.host_decision_from_scheduler_state(
        {"current_phase": "", "next_speaker": "end", "speaker_task": ""},
        [],
    )

    assert out["next_speaker"] == "end"
    from app.agent.group_chat_host_messages import HOST_END_MESSAGE

    assert out["announcement"] == HOST_END_MESSAGE
    assert "教师" not in out["announcement"]
    assert "研讨" not in out["announcement"]


def test_host_decision_from_scheduler_state_maps_name_with_agent_id():
    out = hd.host_decision_from_scheduler_state(
        {
            "current_phase": "阶段1：选题",
            "next_speaker": "伴学研讨——引导教学的教师 (agent-6ffb9536)",
            "speaker_task": "请教师给出本轮讨论主题。",
        },
        [
            {
                "agent_id": "agent-6ffb9536",
                "name": "伴学研讨——引导教学的教师",
                "role": "伴学研讨中的教师，负责选题、材料引导、教师追问与最终点评。",
            }
        ],
    )

    assert out is not None
    assert out["next_speaker"] == "agent-6ffb9536"
    assert out["current_phase"] == "阶段1：选题"
    assert out["speaker_task"] == "请教师给出本轮讨论主题。"
    assert out.get("next_prompt") is None
