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
        {"current_phase": "补充信息", "next_speaker": "用户", "speaker_task": "请补充年级"},
        [],
    )

    assert out["next_speaker"] == "user"
    assert out["next_prompt"] == "请补充年级"
    assert out["decision_source"] == "host_scheduler_state"
