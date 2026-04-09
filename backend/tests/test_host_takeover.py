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


def test_parse_host_response_extracts_next_prompt():
    gc = _get_group_chat_module()
    raw = """开场白
```json
{"task_done": false, "next_speaker": "agent-a", "next_prompt": "请结合上文补充要点", "reason": "继续"}
```
"""
    out = gc._parse_host_response(raw)
    assert out is not None
    assert out.get("next_prompt") == "请结合上文补充要点"
    assert out.get("next_speaker") == "agent-a"


def test_parse_host_response_without_next_prompt():
    gc = _get_group_chat_module()
    raw = """说明
```json
{"task_done": true, "next_speaker": "user"}
```
"""
    out = gc._parse_host_response(raw)
    assert out is not None
    assert out.get("next_prompt") is None


def test_preferred_agent_id_map_prefers_agent_namespace():
    gc = _get_group_chat_module()
    instances = [
        {"agent_id": "agent-seminar-guide", "name": "内容引导与发散专家"},
        {"agent_id": "agent-123", "name": "内容引导与发散专家"},
        {"agent_id": "agent-d92e733e", "name": "文书专员"},
    ]
    id_map = gc._build_preferred_agent_id_map(instances)
    assert id_map["agent-seminar-guide"] == "agent-seminar-guide"
    assert id_map["agent-123"] == "agent-seminar-guide"
    out = gc._normalize_to_preferred_agent_ids(
        ["agent-seminar-guide", "agent-123", "agent-d92e733e"],
        id_to_preferred=id_map,
    )
    assert out == ["agent-seminar-guide", "agent-d92e733e"]


def test_preferred_agent_id_map_generates_agent_id_for_dha_only():
    gc = _get_group_chat_module()
    instances = [
        {"agent_id": "agent-web-fetch", "name": "网页爬取专家"},
    ]
    id_map = gc._build_preferred_agent_id_map(instances)
    assert id_map["agent-web-fetch"] == "agent-web-fetch"
    preferred_rows = gc._build_preferred_instances(instances, id_to_preferred=id_map)
    assert preferred_rows[0]["agent_id"] == "agent-web-fetch"


def test_extract_explicit_requested_agent_ids_matches_explicit_name_only():
    gc = _get_group_chat_module()
    instances = [
        {"agent_id": "agent-d92e733e", "name": "文书专员", "role": "文本创作与报告撰写", "skill_ids": ["doc-coauthoring"]},
        {"agent_id": "agent-other", "name": "网页爬取专家", "role": "网页抓取", "skill_ids": ["url-fetch"]},
    ]
    out = gc._extract_explicit_requested_agent_ids("请文书专员帮我写报告", instances)
    assert "agent-d92e733e" in out


def test_prioritize_suggested_add_ids_prefers_user_requested_experts():
    from app.core.recruitment_helpers import prioritize_suggested_add_ids

    out = prioritize_suggested_add_ids(
        ["agent-a", "agent-b"],
        explicit_requested_agent_ids=["agent-x", "agent-a"],
        recruitable_ids={"agent-a", "agent-b", "agent-x"},
        max_n=3,
    )
    assert out == ["agent-x", "agent-a", "agent-b"]


def test_pick_resolved_host_skill_id_prefers_specialized_over_generic():
    gc = _get_group_chat_module()
    pick = gc._pick_resolved_host_skill_id
    assert pick(["group-host", "group-host-webnovel"]) == "group-host-webnovel"
    assert pick(["group-host-webnovel", "group-host"]) == "group-host-webnovel"
    assert pick(["group-host"]) == "group-host"
    assert pick([]) == "group-host"


def test_leader_prompt_hides_skill_details_from_host():
    from app.agent.leader_scheduler import _build_leader_prompt

    prompt = _build_leader_prompt(
        [{"agent_id": "agent-a", "name": "专家A", "role": "文案"}],
        "完成文案任务",
        "最近对话",
        [{"agent_id": "agent-b", "name": "专家B", "role": "检索", "skill_ids": ["skill-x", "skill-y"]}],
        allow_recruitment=True,
    )
    assert "skills=" not in prompt
    assert "skill-x" not in prompt
