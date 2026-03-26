"""Host-on-demand routing tests."""
import os

os.environ.setdefault("QWEN_API_KEY", "test-key-for-unit-test")


def _get_group_chat_module():
    from app.api import group_chat

    return group_chat


def test_user_requests_host_takeover_with_at_syntax():
    gc = _get_group_chat_module()
    assert gc._user_requests_host_takeover("@主持人 请接管", explicit_flag=None, host_display_name="四九")
    assert gc._user_requests_host_takeover("@四九 帮我分配一下", explicit_flag=None, host_display_name="四九")


def test_user_requests_host_takeover_with_natural_language():
    gc = _get_group_chat_module()
    assert gc._user_requests_host_takeover("请主持人来安排下一位", explicit_flag=None, host_display_name="四九")
    assert gc._user_requests_host_takeover("四九你来接管", explicit_flag=None, host_display_name="四九")


def test_user_requests_host_takeover_false_when_not_mentioned():
    gc = _get_group_chat_module()
    assert not gc._user_requests_host_takeover("请文书专员继续完善报告", explicit_flag=None, host_display_name="四九")
    assert not gc._user_requests_host_takeover("【主持人补充指令】请撰写报告", explicit_flag=None, host_display_name="四九")


def test_select_next_speaker_without_host_prefers_last_speaker():
    gc = _get_group_chat_module()
    out = gc._select_next_speaker_without_host(
        dha_ids=["a", "b", "c"],
        last_speaker_dha_id="b",
        explicit_requested_dha_ids=["a"],
    )
    assert out == "b"


def test_select_next_speaker_without_host_fallback_rules():
    gc = _get_group_chat_module()
    out_explicit = gc._select_next_speaker_without_host(
        dha_ids=["a", "b", "c"],
        last_speaker_dha_id=None,
        explicit_requested_dha_ids=["x", "c"],
    )
    assert out_explicit == "c"
    out_single = gc._select_next_speaker_without_host(
        dha_ids=["solo"],
        last_speaker_dha_id=None,
        explicit_requested_dha_ids=[],
    )
    assert out_single == "solo"
    out_none = gc._select_next_speaker_without_host(
        dha_ids=["a", "b"],
        last_speaker_dha_id=None,
        explicit_requested_dha_ids=[],
    )
    assert out_none is None
