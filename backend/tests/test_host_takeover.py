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


def test_preferred_agent_id_map_prefers_agent_namespace():
    gc = _get_group_chat_module()
    instances = [
        {"dha_id": "dha-seminar-guide", "name": "内容引导与发散专家"},
        {"dha_id": "agent-123", "name": "内容引导与发散专家"},
        {"dha_id": "agent-d92e733e", "name": "文书专员"},
    ]
    id_map = gc._build_preferred_agent_id_map(instances)
    assert id_map["dha-seminar-guide"] == "agent-123"
    assert id_map["agent-123"] == "agent-123"
    out = gc._normalize_to_preferred_agent_ids(
        ["dha-seminar-guide", "agent-d92e733e"],
        id_to_preferred=id_map,
    )
    assert out == ["agent-123", "agent-d92e733e"]


def test_extract_explicit_requested_dha_ids_matches_writing_intent():
    gc = _get_group_chat_module()
    instances = [
        {"dha_id": "agent-d92e733e", "name": "文书专员", "role": "文本创作与报告撰写", "skill_ids": ["doc-coauthoring"]},
        {"dha_id": "agent-other", "name": "网页爬取专家", "role": "网页抓取", "skill_ids": ["url-fetch"]},
    ]
    out = gc._extract_explicit_requested_dha_ids("请文本创作人员帮我写报告", instances)
    assert "agent-d92e733e" in out


def test_prioritize_suggested_add_ids_prefers_user_requested_experts():
    gc = _get_group_chat_module()
    out = gc._prioritize_suggested_add_ids(
        ["agent-a", "agent-b"],
        explicit_requested_dha_ids=["agent-x", "agent-a"],
        recruitable_ids={"agent-a", "agent-b", "agent-x"},
        max_n=3,
    )
    assert out == ["agent-x", "agent-a", "agent-b"]
