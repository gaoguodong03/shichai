"""Host-on-demand routing tests."""
import os

import pytest

os.environ.setdefault("QWEN_API_KEY", "test-key-for-unit-test")


def _get_group_chat_module():
    from app.agent import group_chat_runtime as group_chat

    return group_chat


def _get_host_decision_module():
    from app.agent import group_host_decision

    return group_host_decision


def _get_host_runtime_module():
    from app.agent import group_chat_host_runtime

    return group_chat_host_runtime


def _get_expert_resolution_module():
    from app.agent import group_chat_expert_resolution

    return group_chat_expert_resolution


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


def test_parse_host_response_migrates_legacy_next_prompt_to_speaker_task():
    gc = _get_host_decision_module()
    raw = """开场白
```json
{"task_done": false, "next_speaker": "agent-a", "next_prompt": "请结合上文补充要点", "reason": "继续"}
```
"""
    out = gc.parse_host_response(raw)
    assert out is not None
    assert out.get("speaker_task") == "请结合上文补充要点"
    assert out.get("next_prompt") is None
    assert out.get("next_speaker") == "agent-a"


def test_parse_host_response_without_next_prompt():
    gc = _get_host_decision_module()
    raw = """说明
```json
{"task_done": true, "next_speaker": "user"}
```
"""
    out = gc.parse_host_response(raw)
    assert out is not None
    assert out.get("next_prompt") is None


def test_host_pause_message_prefers_speaker_task_over_generic_user_announcement():
    from app.agent.group_chat_host_messages import _build_host_pause_message

    msg = _build_host_pause_message(
        skill_id="group-host-webnovel",
        next_speaker="user",
        current_phase="阶段1：入口分流",
        announcement="请用户继续发言。",
        speaker_task="请用户明确报告目标受众和篇幅。",
    )

    assert msg is not None
    assert "请用户明确报告目标受众和篇幅。" in msg["content"]
    assert "current_phase" not in msg["content"]
    assert msg["meta"]["scheduler_state"] == {
        "current_phase": "阶段1：入口分流",
        "next_speaker": "user",
        "speaker_task": "请用户明确报告目标受众和篇幅。",
    }


def test_host_next_speaker_message_includes_scheduler_state_json():
    from app.agent.group_chat_host_messages import _build_host_next_speaker_message

    msg = _build_host_next_speaker_message(
        skill_id="group-host-webnovel",
        next_speaker="agent-writer",
        current_phase="阶段2：撰写",
        speaker_task="请根据确认后的目标受众撰写报告。",
        agent_map={"agent-writer": {"name": "文字创作专家"}},
    )

    assert "下面由 文字创作专家 发言。" in msg["content"]
    assert "current_phase" not in msg["content"]
    assert msg["meta"]["scheduler_state"] == {
        "current_phase": "阶段2：撰写",
        "next_speaker": "agent-writer",
        "speaker_task": "请根据确认后的目标受众撰写报告。",
    }


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


def test_preferred_agent_id_map_generates_agent_id_for_legacy_expert_only():
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
    gc = _get_expert_resolution_module()
    pick = gc._pick_resolved_host_skill_id
    assert pick(["group-host", "group-host-webnovel"]) == "group-host-webnovel"
    assert pick(["group-host-webnovel", "group-host"]) == "group-host-webnovel"
    assert pick(["group-host"]) == "group-host"
    assert pick([]) == ""


async def test_host_decide_loads_resolved_scene_host_skill(monkeypatch, tmp_path):
    gc = _get_host_runtime_module()
    calls = {}
    meta_item = {}

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
    monkeypatch.setattr(gc, "create_skill_execution_agent", fake_agent_factory)

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "agent_id": "agent-scene-host",
            "name": "四九场景主持",
            "role": "群聊场景主持人",
            "skill_ids": ["group-host", "group-host-webnovel"],
        },
        agent_profiles=[{"agent_id": "agent-a", "name": "写作专家", "role": "写作"}],
        discussion_goal="写网文",
        recent_messages="",
        last_speaker_agent_id=None,
        extra_system_prompt="",
        group_session_id="group-1",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="scene",
        meta_item=meta_item,
    )

    assert out is not None
    assert out["next_speaker"] == "agent-a"
    assert "网文专用主持 Skill 正文" in calls["agent_factory"]["skill_content"]
    assert "通用主持 Skill 正文" not in calls["agent_factory"]["skill_content"]
    assert calls["agent_factory"]["tools"] == []
    assert calls["agent_factory"]["kwargs"]["synthesize_after_tools"] is False
    assert '"current_phase": "阶段1：入口分流"' in calls["agent_factory"]["skill_content"]
    assert "本场景也必须同时输出 `current_phase`" in calls["agent_factory"]["skill_content"]
    assert "先判断任务目标是否已经完成" in calls["agent_factory"]["skill_content"]
    assert "不要再安排专家做“总结答复”" in calls["agent_factory"]["skill_content"]
    assert "后台调度状态是上一轮主持人保存的状态，可能滞后于刚发言专家的正文" in calls["agent_factory"]["skill_content"]
    assert "教师" not in calls["agent_factory"]["skill_content"]
    assert "研讨" not in calls["agent_factory"]["skill_content"]
    assert "不要在主持人 Skill 中硬编码 agent_id" in calls["agent_factory"]["skill_content"]
    assert "`speaker_task` 是唯一任务交接字段" in calls["agent_factory"]["skill_content"]
    assert "next_prompt" not in calls["agent_factory"]["skill_content"]
    assert '"reason"' not in calls["agent_factory"]["skill_content"]
    assert "`next_speaker` 可以写参与者 agent_id" not in calls["agent_factory"]["skill_content"]
    assert "专家发言完成后，平台会先交回主持人调度" in calls["agent_factory"]["skill_content"]
    assert "这里的 `next_speaker` 是主持人本次调度出的下一步目标" in calls["agent_factory"]["skill_content"]
    assert "不要把 `next_speaker` 写成主持人自身" in calls["agent_factory"]["skill_content"]
    assert "也可以写主持人 Skill 中的角色名" not in calls["agent_factory"]["skill_content"]
    assert '`next_speaker` 写 `"user"` 表示等待用户继续' in calls["agent_factory"]["skill_content"]
    assert '写 `"end"` 表示本轮会话结束' in calls["agent_factory"]["skill_content"]
    assert '`next_speaker` 写 `"user"`/`"用户"`' not in calls["agent_factory"]["skill_content"]
    assert '写 `"end"`/`"结束研讨"`' not in calls["agent_factory"]["skill_content"]
    assert meta_item["scheduler_state"]["next_speaker"] == "agent-a"


async def test_host_decide_uses_scheduler_state_without_workspace_files(monkeypatch, tmp_path):
    gc = _get_host_runtime_module()
    calls = {}
    meta_item = {}

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
    monkeypatch.setattr(gc, "create_skill_execution_agent", fake_agent_factory)

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "agent_id": "agent-scene-host",
            "name": "四九场景主持",
            "role": "群聊场景主持人",
            "skill_ids": ["group-host"],
        },
        agent_profiles=[{"agent_id": "agent-teacher", "name": "伴学研讨——引导教学的教师", "role": "教师"}],
        discussion_goal="开始研讨",
        recent_messages="【用户】开始研讨",
        last_speaker_agent_id=None,
        extra_system_prompt="",
        group_session_id="group-fast",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="scene",
        meta_item=meta_item,
    )

    assert out is not None
    assert out["next_speaker"] == "agent-teacher"
    assert out["speaker_task"] == "请提出本轮研讨主题。"
    assert out.get("next_prompt") is None
    assert out["decision_source"] == "host_scheduler_state"
    assert calls["agent_factory"]["tools"] == []
    assert "不要调用 read_file/write_workspace_file" in calls["agent_factory"]["skill_content"]
    assert not (tmp_path / "current_phase.txt").exists()
    assert not (tmp_path / "next_speaker.txt").exists()
    assert not (tmp_path / "speaker_task.txt").exists()
    assert meta_item["scheduler_state"] == {
        "current_phase": "阶段1：选题",
        "next_speaker": "教师",
        "speaker_task": "请提出本轮研讨主题。",
    }


async def test_host_decide_preserves_current_phase_when_scheduler_omits_it(monkeypatch):
    gc = _get_host_runtime_module()
    calls = {}
    meta_item = {
        "scheduler_state": {
            "current_phase": "阶段2：材料支撑",
            "next_speaker": "agent-research",
            "speaker_task": "请补充可支撑讨论的材料。",
        }
    }

    class FakeSkillsLoader:
        def get_skill_full_content(self, _skill_id):
            return "主持人 Skill 正文"

    class FakeAgent:
        async def ainvoke(self, initial_state, **_kwargs):
            calls["user_prompt"] = initial_state["messages"][0].content
            return {
                "messages": [
                    gc.AIMessage(
                        content=(
                            '```json\n{"next_speaker": "agent-teacher", '
                            '"speaker_task": "请教师收窄成可讨论的问题。", '
                            '"reason": "继续交给教师"}\n```'
                        )
                    )
                ]
            }

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "create_skill_execution_agent", lambda *_args, **_kwargs: FakeAgent())

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "agent_id": "agent-scene-host",
            "name": "四九场景主持",
            "role": "群聊场景主持人",
            "skill_ids": ["group-host"],
        },
        agent_profiles=[
            {"agent_id": "agent-teacher", "name": "伴学研讨——引导教学的教师", "role": "教师"},
        ],
        discussion_goal="AI 在学生竞赛中的应用",
        recent_messages="【用户】请收窄讨论题",
        last_speaker_agent_id="agent-research",
        extra_system_prompt="",
        group_session_id="group-phase-preserve",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="scene",
        meta_item=meta_item,
    )

    assert "【后台调度状态】" in calls["user_prompt"]
    assert "current_phase: 阶段2：材料支撑" in calls["user_prompt"]
    assert out["next_speaker"] == "agent-teacher"
    assert meta_item["scheduler_state"] == {
        "current_phase": "阶段2：材料支撑",
        "next_speaker": "agent-teacher",
        "speaker_task": "请教师收窄成可讨论的问题。",
    }


@pytest.mark.asyncio
async def test_host_decide_ignores_scheduler_state_in_recruitment_mode(monkeypatch):
    from app.agent import group_chat_host_runtime as gc

    meta_item = {
        "scheduler_state": {
            "current_phase": "阶段1：选题与需求确认",
            "next_speaker": "用户",
            "speaker_task": "建议您先邀请【网页爬取专家】和【文字创作专家】加入会话。",
        }
    }
    calls = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, _sid):
            return "主持人 Skill 正文"

    class FakeAgent:
        async def ainvoke(self, initial_state, **_kwargs):
            calls["user_prompt"] = initial_state["messages"][0].content
            return {
                "messages": [
                    gc.AIMessage(
                        content=(
                            "请用户确认新建 Skill 的用途。\n"
                            '```json\n{"task_done": true, "next_speaker": "user", '
                            '"reason": "需要确认 Skill 需求"}\n```'
                        )
                    )
                ]
            }

    def fake_agent_factory(*_args, **_kwargs):
        return FakeAgent()

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "create_skill_execution_agent", fake_agent_factory)

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "agent_id": "agent-host",
            "name": "四九",
            "role": "群聊主持人",
            "skill_ids": ["group-host"],
        },
        agent_profiles=[],
        discussion_goal="新建一个 Skill",
        recent_messages="【用户】帮我新建一个 Skill",
        last_speaker_agent_id=None,
        extra_system_prompt="",
        group_session_id="group-recruitment",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="recruitment",
        meta_item=meta_item,
    )

    assert "【后台调度状态】" not in calls["user_prompt"]
    assert "网页爬取专家" not in calls["user_prompt"]
    assert out["decision_source"] == "legacy"
    assert out["next_speaker"] == "user"
    assert meta_item["scheduler_state"]["speaker_task"] == "建议您先邀请【网页爬取专家】和【文字创作专家】加入会话。"


@pytest.mark.asyncio
async def test_host_decide_hides_invitable_list_when_room_has_participants(monkeypatch):
    from app.agent import group_chat_host_runtime as gc

    calls = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, _sid):
            return "主持人 Skill 正文"

    class FakeAgent:
        async def ainvoke(self, initial_state, **_kwargs):
            calls["user_prompt"] = initial_state["messages"][0].content
            return {
                "messages": [
                    gc.AIMessage(
                        content='```json\n{"task_done": false, "next_speaker": "agent-a", "next_prompt": "请继续", "reason": "继续交给场内专家"}\n```'
                    )
                ]
            }

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "create_skill_execution_agent", lambda *_args, **_kwargs: FakeAgent())

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "agent_id": "agent-host",
            "name": "四九",
            "role": "群聊主持人",
            "skill_ids": ["group-host"],
        },
        agent_profiles=[{"agent_id": "agent-a", "name": "写作专家", "role": "写作"}],
        discussion_goal="继续写作",
        recent_messages="【用户】继续",
        last_speaker_agent_id=None,
        extra_system_prompt="",
        available_to_add=[{"agent_id": "agent-b", "name": "检索专家", "role": "检索"}],
        group_session_id="group-recruitment-with-member",
        app_settings={"host_profile": {"display_name": "四九", "skill_ids": []}},
        orchestration_profile="recruitment",
        meta_item={},
    )

    assert out["next_speaker"] == "agent-a"
    assert "【可邀请专家列表】" not in calls["user_prompt"]
    assert "检索专家" not in calls["user_prompt"]


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
    assert "先判断任务目标是否已经完成" in prompt
    assert "不要再安排专家做“总结答复”" in prompt
    assert "speaker_task" in prompt
    assert "next_prompt" not in prompt


def test_leader_prompt_hides_invitable_list_when_room_has_participants():
    from app.agent.leader_scheduler import _build_leader_prompt

    prompt = _build_leader_prompt(
        [{"agent_id": "agent-a", "name": "专家A", "role": "文案"}],
        "完成文案任务",
        "最近对话",
        [{"agent_id": "agent-b", "name": "专家B", "role": "检索"}],
        allow_recruitment=True,
    )

    assert "可邀请的新成员" not in prompt
    assert "专家B" not in prompt


def test_leader_prompt_shows_invitable_list_only_for_empty_room():
    from app.agent.leader_scheduler import _build_leader_prompt

    prompt = _build_leader_prompt(
        [],
        "需要组队",
        "最近对话",
        [{"agent_id": "agent-b", "name": "专家B", "role": "检索"}],
        allow_recruitment=True,
    )

    assert "可邀请的新成员" in prompt
    assert "专家B" in prompt


async def test_leader_decide_migrates_legacy_next_prompt_to_speaker_task():
    from app.agent.leader_scheduler import leader_decide

    class FakeClient:
        async def ainvoke(self, _messages):
            return type(
                "Resp",
                (),
                {
                    "content": (
                        '```json\n{"task_done": false, "next_speaker": "agent-a", '
                        '"next_prompt": "请继续写大纲", "reason": "继续"}\n```'
                    )
                },
            )()

    class FakeLLM:
        def get_client(self):
            return FakeClient()

    out = await leader_decide(
        FakeLLM(),
        [{"agent_id": "agent-a", "name": "专家A", "role": "写作"}],
        "写网文",
        "最近对话",
    )

    assert out["next_speaker"] == "agent-a"
    assert out["speaker_task"] == "请继续写大纲"
    assert out.get("next_prompt") is None
