from app.agent import group_host_decision as hd
from app.agent.orchestrator_state import InterruptReason


def test_strict_host_scheduler_rejects_wrapped_json_text():
    text = """安排如下：
```json
{"current_phase":"阶段1","next_speaker":"教师","speaker_task":"给出主题"}
```"""

    out = hd.parse_strict_host_scheduler_output(
        text,
        agent_profiles=[{"name": "教师"}],
        orchestration_profile="scene",
    )

    assert out["next_speaker"] == "user"
    assert out["announcement"] == hd.HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == InterruptReason.PROTOCOL_ERROR.value
    assert out["decision_source"] == "system_guard"


def test_strict_host_scheduler_rejects_legacy_next_prompt():
    text = '```json\n{"current_phase":"阶段1","next_speaker":"教师","next_prompt":"给出主题"}\n```'

    out = hd.parse_strict_host_scheduler_output(
        text,
        agent_profiles=[{"name": "教师"}],
        orchestration_profile="scene",
    )

    assert out["next_speaker"] == "user"
    assert out["announcement"] == hd.HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == InterruptReason.PROTOCOL_ERROR.value


def test_strict_host_scheduler_accepts_valid_scene_decision():
    text = '```json\n{"current_phase":"阶段1","next_speaker":"教师","speaker_task":"给出主题","reason":"开始"}\n```'

    out = hd.parse_strict_host_scheduler_output(
        text,
        agent_profiles=[{"name": "教师"}],
        orchestration_profile="scene",
    )

    assert out["next_speaker"] == "教师"
    assert out["speaker_task"] == "给出主题"
    assert out["decision_source"] == "host_scheduler_state"


def test_strict_host_scheduler_rejects_agent_id_next_speaker():
    text = '```json\n{"current_phase":"阶段1","next_speaker":"agent-teacher","speaker_task":"给出主题","reason":"开始"}\n```'

    out = hd.parse_strict_host_scheduler_output(
        text,
        agent_profiles=[{"name": "教师", "agent_id": "agent-teacher", "id": "agent-teacher"}],
        orchestration_profile="scene",
    )

    assert out["next_speaker"] == "user"
    assert out["announcement"] == hd.HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == InterruptReason.PROTOCOL_ERROR.value


def test_forced_at_mention_matches_agent_name():
    agents = [{"name": "教师", "role": "出题"}]

    assert hd.extract_forced_at_mention_agent_name("@教师 请继续", agents) == "教师"
