"""Host-on-demand routing tests."""
import os
from types import SimpleNamespace

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


def test_extract_forced_at_mention_agent_id_only_when_prefix_mention():
    gc = _get_group_chat_module()
    instances = [
        {"agent_id": "agent-writer", "name": "文书专员", "role": "写作"},
        {"agent_id": "agent-research", "name": "研讨教师", "role": "研究"},
    ]
    assert gc._extract_forced_at_mention_agent_id("@文书专员 请先写提纲", instances) == "agent-writer"
    assert gc._extract_forced_at_mention_agent_id("@agent-research 帮我查资料", instances) == "agent-research"
    # 非开头 @ 不触发强制路由
    assert gc._extract_forced_at_mention_agent_id("请 @文书专员 接手", instances) is None


def test_extract_forced_at_mention_agent_id_handles_unknown_or_punctuation():
    gc = _get_group_chat_module()
    instances = [{"agent_id": "agent-writer", "name": "文书专员", "role": "写作"}]
    assert gc._extract_forced_at_mention_agent_id("@不存在专家 帮忙", instances) is None
    assert gc._extract_forced_at_mention_agent_id("@ 文书专员 帮忙", instances) is None
    assert gc._extract_forced_at_mention_agent_id("  @文书专员：请继续", instances) == "agent-writer"


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
    assert pick([]) == ""


async def test_host_decide_loads_resolved_scene_host_skill(monkeypatch, tmp_path):
    gc = _get_group_chat_module()
    calls = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, skill_id):
            return {
                "group-host": "通用主持 Skill 正文",
                "group-host-webnovel": "网文专用主持 Skill 正文",
            }.get(skill_id)

    async def fake_tool_builder(*_args, **_kwargs):
        raise AssertionError("host scheduler should not use workspace tools for scheduler-state persistence")

    class FakeAgent:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "messages": [
                    gc.AIMessage(
                        content='```json\n{"task_done": false, "next_speaker": "agent-a", "next_prompt": "请写大纲", "reason": "按场景专用主持流程"}\n```'
                    )
                ]
            }

    def fake_agent_factory(llm, tools, skill_content, extra_system_prompt="", **kwargs):
        calls["agent_factory"] = {
            "llm": llm,
            "tools": tools,
            "skill_content": skill_content,
            "extra_system_prompt": extra_system_prompt,
            "kwargs": kwargs,
        }
        return FakeAgent()

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "build_tools_for_group_chat", fake_tool_builder)
    monkeypatch.setattr(gc, "create_skill_execution_agent", fake_agent_factory)
    monkeypatch.setattr(gc, "get_workspace_root_path", lambda session_id: tmp_path)

    out = await gc._host_decide_by_dha(
        llm=object(),
        host_dha={
            "agent_id": "agent-scene-host",
            "name": "四九场景主持",
            "role": "群聊场景主持人",
            "skill_ids": ["group-host", "group-host-webnovel"],
        },
        dha_list=[{"agent_id": "agent-a", "name": "写作专家", "role": "写作"}],
        discussion_goal="写网文",
        recent_messages="",
        last_speaker_agent_id=None,
        extra_system_prompt="",
        group_session_id="group-1",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="scene",
    )

    assert out is not None
    assert out["next_speaker"] == "agent-a"
    assert "网文专用主持 Skill 正文" in calls["agent_factory"]["skill_content"]
    assert "通用主持 Skill 正文" not in calls["agent_factory"]["skill_content"]
    assert calls["agent_factory"]["tools"] == []
    assert calls["agent_factory"]["kwargs"]["synthesize_after_tools"] is False


async def test_host_decide_persists_scheduler_files_from_model_text_without_tool_round(monkeypatch, tmp_path):
    gc = _get_group_chat_module()
    calls = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, skill_id):
            return "主持人 Skill 正文"

    async def fake_tool_builder(*_args, **_kwargs):
        raise AssertionError("host scheduler should not construct workspace tools")

    class FakeAgent:
        async def ainvoke(self, initial_state, **_kwargs):
            calls["initial_state"] = initial_state
            return {
                "messages": [
                    gc.AIMessage(
                        content=(
                            "current_phase.txt: 阶段1：选题\n"
                            "next_speaker.txt: 教师\n"
                            "speaker_task.txt: 请提出本轮研讨主题。"
                        )
                    )
                ]
            }

    def fake_agent_factory(llm, tools, skill_content, extra_system_prompt="", **kwargs):
        calls["agent_factory"] = {
            "tools": tools,
            "skill_content": skill_content,
            "kwargs": kwargs,
        }
        return FakeAgent()

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "build_tools_for_group_chat", fake_tool_builder)
    monkeypatch.setattr(gc, "create_skill_execution_agent", fake_agent_factory)
    monkeypatch.setattr(gc, "get_workspace_root_path", lambda session_id: tmp_path)

    out = await gc._host_decide_by_dha(
        llm=object(),
        host_dha={
            "agent_id": "agent-scene-host",
            "name": "四九场景主持",
            "role": "群聊场景主持人",
            "skill_ids": ["group-host"],
        },
        dha_list=[{"agent_id": "agent-teacher", "name": "伴学研讨——引导教学的教师", "role": "教师"}],
        discussion_goal="开始研讨",
        recent_messages="【用户】开始研讨",
        last_speaker_agent_id=None,
        extra_system_prompt="",
        group_session_id="group-fast",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="scene",
    )

    assert out is not None
    assert out["next_speaker"] == "agent-teacher"
    assert out["next_prompt"] == "请提出本轮研讨主题。"
    assert out["decision_source"] == "host_scheduler_state"
    assert calls["agent_factory"]["tools"] == []
    assert "不要调用 read_file/write_workspace_file" in calls["agent_factory"]["skill_content"]
    assert (tmp_path / "current_phase.txt").read_text(encoding="utf-8") == "阶段1：选题\n"
    assert (tmp_path / "next_speaker.txt").read_text(encoding="utf-8") == "教师\n"
    assert (tmp_path / "speaker_task.txt").read_text(encoding="utf-8") == "请提出本轮研讨主题。\n"


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
