import pytest

from app.agent.platform_prompts import PLATFORM_PROMPTS, get_platform_prompt, render_platform_prompt


def test_platform_prompts_are_registered_by_prompt_id():
    assert "host.select_next_speaker.v1" in PLATFORM_PROMPTS
    assert get_platform_prompt("host.select_next_speaker.v1").prompt_id == "host.select_next_speaker.v1"


def test_host_prompt_requires_current_contract_fields():
    rendered = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": "写作专家",
            "current_phase": "资料收集",
            "user_message": "写一篇文章",
            "recent_history": "无",
        },
    )

    assert '"next_action"' in rendered
    assert "speaker_task" in rendered and "不要输出" in rendered


def test_prompt_render_rejects_missing_variables():
    with pytest.raises(KeyError):
        render_platform_prompt("title.generate.v1", {})
