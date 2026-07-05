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


def test_strict_host_response_rejects_legacy_next_prompt():
    gc = _get_host_decision_module()
    raw = '```json\n{"task_done": false, "next_speaker": "专家甲", "next_prompt": "请结合上文补充要点", "reason": "继续"}\n```'
    out = gc.parse_strict_host_scheduler_output(raw, [{"name": "专家甲"}], orchestration_profile="scene")
    assert out["next_speaker"] == "user"
    assert out["announcement"] == gc.HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == "protocol_error"


def test_strict_host_response_accepts_required_fields():
    gc = _get_host_decision_module()
    raw = '```json\n{"current_phase": "补充信息", "next_speaker": "user", "speaker_task": "请补充信息"}\n```'
    out = gc.parse_strict_host_scheduler_output(raw, [], orchestration_profile="recruitment")
    assert out["next_speaker"] == "user"
    assert out["speaker_task"] == "请补充信息"


def test_host_pause_message_user_shows_speaker_task():
    from app.agent.group_chat_host_messages import _build_host_pause_message

    msg = _build_host_pause_message(
        skill="group-host-webnovel",
        next_speaker="user",
        current_phase="阶段1：入口分流",
        announcement="请用户继续发言。",
        speaker_task="请用户明确报告目标受众和篇幅。",
    )

    assert msg is not None
    assert msg["content"] == "请用户明确报告目标受众和篇幅。"


def test_host_pause_message_end_uses_fixed_copy():
    from app.agent.group_chat_host_messages import HOST_END_MESSAGE, _build_host_pause_message

    msg = _build_host_pause_message(
        skill="group-host-webnovel",
        next_speaker="end",
        current_phase="end",
        speaker_task="",
    )

    assert msg is not None
    assert msg["content"] == HOST_END_MESSAGE
    assert msg["meta"]["scheduler_state"]["next_speaker"] == "end"


def test_host_next_speaker_message_includes_scheduler_state_json():
    from app.agent.group_chat_host_messages import _build_host_next_speaker_message

    msg = _build_host_next_speaker_message(
        skill="group-host-webnovel",
        next_speaker="文字创作专家",
        current_phase="阶段2：撰写",
        speaker_task="请根据确认后的目标受众撰写报告。",
        agent_map={"文字创作专家": {"name": "文字创作专家"}},
    )

    assert "下面由 文字创作专家 发言。" in msg["content"]
    assert "current_phase" not in msg["content"]
    assert msg["meta"]["scheduler_state"] == {
        "current_phase": "阶段2：撰写",
        "next_speaker": "文字创作专家",
        "speaker_task": "请根据确认后的目标受众撰写报告。",
    }


def test_extract_explicit_requested_agent_names_matches_explicit_name_only():
    gc = _get_group_chat_module()
    instances = [
        {"name": "文书专员", "description": "文本创作与报告撰写", "skills": [{"name": "文档合著", "directory_name": "doc-coauthoring"}]},
        {"name": "网页爬取专家", "description": "网页抓取", "skills": [{"name": "网页抓取", "directory_name": "url-fetch"}]},
    ]
    out = gc._extract_explicit_requested_agent_names("请文书专员帮我写报告", instances)
    assert "文书专员" in out


def test_extract_forced_at_mention_agent_name_only_when_prefix_mention():
    gc = _get_group_chat_module()
    instances = [
        {"name": "文书专员", "description": "写作"},
        {"name": "研讨教师", "description": "研究"},
    ]
    assert gc._extract_forced_at_mention_agent_name("@文书专员 请先写提纲", instances) == "文书专员"
    assert gc._extract_forced_at_mention_agent_name("@研讨教师 帮我查资料", instances) == "研讨教师"
    # 非开头 @ 不触发强制路由
    assert gc._extract_forced_at_mention_agent_name("请 @文书专员 接手", instances) is None


def test_extract_forced_at_mention_agent_name_handles_unknown_or_punctuation():
    gc = _get_group_chat_module()
    instances = [{"name": "文书专员", "description": "写作"}]
    assert gc._extract_forced_at_mention_agent_name("@不存在专家 帮忙", instances) is None
    assert gc._extract_forced_at_mention_agent_name("@ 文书专员 帮忙", instances) is None
    assert gc._extract_forced_at_mention_agent_name("  @文书专员：请继续", instances) == "文书专员"


def test_prioritize_suggested_add_names_prefers_user_requested_experts():
    from app.core.recruitment_helpers import prioritize_suggested_add_names

    out = prioritize_suggested_add_names(
        ["专家A", "专家B"],
        explicit_requested_agent_names=["专家X", "专家A"],
        recruitable_names={"专家A", "专家B", "专家X"},
        max_n=3,
    )
    assert out == ["专家X", "专家A", "专家B"]


def test_pick_resolved_host_skill_prefers_specialized_over_generic():
    gc = _get_expert_resolution_module()
    pick = gc._pick_resolved_host_skill
    assert pick(["group-host", "group-host-webnovel"]) == "group-host-webnovel"
    assert pick(["group-host-webnovel", "group-host"]) == "group-host-webnovel"
    assert pick(["group-host"]) == "group-host"
    assert pick([]) == ""


async def test_host_decide_uses_platform_scheduler_prompt(monkeypatch, tmp_path):
    gc = _get_host_runtime_module()
    calls = {}
    session_item = {}

    class FakeSkillsLoader:
        def get_skill_full_content(self, skill_id):
            assert skill_id == "group-host-webnovel"
            return "网文专用主持 Skill 正文：文字创作完成后应进入图片生成阶段。"

    class FakeAgent:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "messages": [
                    gc.AIMessage(
                        content='```json\n{"current_phase": "阶段：撰写", "next_speaker": "写作专家", "speaker_task": "请写大纲"}\n```'
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
            "name": "五九",
            "description": "群聊主持人",
            "skills": [{"name": "通用主持", "directory_name": "group-host"}, {"name": "网文主持", "directory_name": "group-host-webnovel"}],
        },
        agent_profiles=[{"name": "写作专家", "description": "写作"}],
        discussion_goal="写网文",
        recent_messages="",
        last_speaker_agent_name=None,
        extra_system_prompt="",
        group_session_id="group-1",
        app_settings={"host_profile": {"leader_agent_name": "五九"}},
        orchestration_profile="scene",
        session_item=session_item,
    )

    assert out is not None
    assert out["next_speaker"] == "写作专家"
    content = calls["agent_factory"]["skill_content"]
    assert "你是 五九，担任本群主持人。你的职责：群聊主持人。" in content
    assert "平台会根据调度结果生成固定主持话术" in content
    assert '"next_speaker": "专家名称"' in content
    assert '`"invite"`' in content
    assert "网文专用主持 Skill 正文：文字创作完成后应进入图片生成阶段。" in content
    assert calls["agent_factory"]["tools"] == []
    assert calls["agent_factory"]["kwargs"]["synthesize_after_tools"] is False
    assert session_item["scheduler_state"]["next_speaker"] == "写作专家"


async def test_host_decide_uses_scheduler_state_without_workspace_files(monkeypatch, tmp_path):
    gc = _get_host_runtime_module()
    calls = {}
    session_item = {}

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
                            '```json\n{"current_phase": "阶段1：选题", '
                            '"next_speaker": "伴学研讨——引导教学的教师", '
                            '"speaker_task": "请提出本轮研讨主题。", '
                            '"reason": "进入选题"}\n```'
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
            "name": "四九场景主持",
            "description": "群聊场景主持人",
            "skills": [{"name": "群聊主持", "directory_name": "group-host"}],
        },
        agent_profiles=[{"name": "伴学研讨——引导教学的教师", "description": "教师"}],
        discussion_goal="开始研讨",
        recent_messages="【用户】开始研讨",
        last_speaker_agent_name=None,
        extra_system_prompt="",
        group_session_id="group-fast",
        app_settings={"host_profile": {"leader_agent_name": "四九"}},
        orchestration_profile="scene",
        session_item=session_item,
    )

    assert out is not None
    assert out["next_speaker"] == "伴学研讨——引导教学的教师"
    assert out["speaker_task"] == "请提出本轮研讨主题。"
    assert "next_prompt" not in out
    assert out["decision_source"] == "host_scheduler_state"
    assert calls["agent_factory"]["tools"] == []
    assert "平台会根据调度结果生成固定主持话术" in calls["agent_factory"]["skill_content"]
    assert "next_speaker 写 Agent 名称" in calls["initial_state"]["messages"][0].content
    assert not (tmp_path / "current_phase.txt").exists()
    assert not (tmp_path / "next_speaker.txt").exists()
    assert not (tmp_path / "speaker_task.txt").exists()
    assert session_item["scheduler_state"] == {
        "current_phase": "阶段1：选题",
        "next_speaker": "伴学研讨——引导教学的教师",
        "speaker_task": "请提出本轮研讨主题。",
    }


async def test_host_decide_does_not_resolve_stale_host_skill_ref_by_name(monkeypatch):
    gc = _get_host_runtime_module()
    calls = {}

    class FakeSkill:
        name = "网文协同写作主持人v1.0"

    class FakeSkillsLoader:
        skills = {"v10-2": FakeSkill()}

        def get_skill_full_content(self, skill_id):
            if skill_id == "v10-2":
                return "网文协同写作主持人v1.0 正文：完整协同任务默认进入图片生成。"
            return None

    class FakeAgent:
        async def ainvoke(self, *_args, **_kwargs):
            return {
                "messages": [
                    gc.AIMessage(
                        content='```json\n{"current_phase": "阶段4：配图", "next_speaker": "图片生成专家", "speaker_task": "请生成配图"}\n```'
                    )
                ]
            }

    def fake_agent_factory(_llm, _tools, skill_content, *_args, **_kwargs):
        calls["skill_content"] = skill_content
        return FakeAgent()

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "create_skill_execution_agent", fake_agent_factory)

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "name": "四九",
            "description": "群聊场景主持人",
            "skills": [{"name": "网文协同写作主持人", "directory_name": "group-host-webnovel"}],
            "skill_refs": [{"name": "网文协同写作主持人"}],
        },
        agent_profiles=[{"name": "图片生成专家", "description": "图片生成"}],
        discussion_goal="写网文并配图",
        recent_messages="【文字创作专家】文章已保存到 逆光工程师-第1章-2026061115500000.md",
        last_speaker_agent_name="文字创作专家",
        extra_system_prompt="",
        app_settings={"host_profile": {"leader_agent_name": "四九"}},
        orchestration_profile="scene",
        session_item={},
    )

    assert out["next_speaker"] == "图片生成专家"
    assert "网文协同写作主持人v1.0 正文：完整协同任务默认进入图片生成。" not in calls["skill_content"]
    assert "群聊主持人" in calls["skill_content"]


async def test_host_decide_preserves_current_phase_when_scheduler_omits_it(monkeypatch):
    gc = _get_host_runtime_module()
    calls = {}
    session_item = {
        "scheduler_state": {
            "current_phase": "阶段2：材料支撑",
            "next_speaker": "信息检索专家",
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
                            '```json\n{"current_phase": "阶段2：材料支撑", '
                            '"next_speaker": "伴学研讨——引导教学的教师", '
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
            "name": "四九场景主持",
            "description": "群聊场景主持人",
            "skills": [{"name": "群聊主持", "directory_name": "group-host"}],
        },
        agent_profiles=[
            {"name": "伴学研讨——引导教学的教师", "description": "教师"},
        ],
        discussion_goal="AI 在学生竞赛中的应用",
        recent_messages="【用户】请收窄讨论题",
        last_speaker_agent_name="信息检索专家",
        extra_system_prompt="",
        group_session_id="group-phase-preserve",
        app_settings={"host_profile": {"leader_agent_name": "四九"}},
        orchestration_profile="scene",
        session_item=session_item,
    )

    assert "【后台调度状态】" in calls["user_prompt"]
    assert "current_phase: 阶段2：材料支撑" in calls["user_prompt"]
    assert out["next_speaker"] == "伴学研讨——引导教学的教师"
    assert session_item["scheduler_state"] == {
        "current_phase": "阶段2：材料支撑",
        "next_speaker": "伴学研讨——引导教学的教师",
        "speaker_task": "请教师收窄成可讨论的问题。",
    }


@pytest.mark.asyncio
async def test_host_decide_ignores_scheduler_state_in_recruitment_mode(monkeypatch):
    from app.agent import group_chat_host_runtime as gc

    session_item = {
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
                            '```json\n{"current_phase": "需求确认", "next_speaker": "user", '
                            '"speaker_task": "请用户确认新建 Skill 的用途。", '
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
            "name": "四九",
            "description": "群聊主持人",
            "skills": [{"name": "群聊主持", "directory_name": "group-host"}],
        },
        agent_profiles=[],
        discussion_goal="新建一个 Skill",
        recent_messages="【用户】帮我新建一个 Skill",
        last_speaker_agent_name=None,
        extra_system_prompt="",
        group_session_id="group-recruitment",
        app_settings={"host_profile": {"leader_agent_name": "四九"}},
        orchestration_profile="recruitment",
        session_item=session_item,
    )

    assert "【后台调度状态】" not in calls["user_prompt"]
    assert "网页爬取专家" not in calls["user_prompt"]
    assert out["decision_source"] == "host_scheduler_state"
    assert out["next_speaker"] == "user"
    assert session_item["scheduler_state"] == {
        "current_phase": "需求确认",
        "next_speaker": "user",
        "speaker_task": "请用户确认新建 Skill 的用途。",
    }


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
                        content='```json\n{"current_phase": "继续写作", "next_speaker": "写作专家", "speaker_task": "请继续", "reason": "继续交给场内专家"}\n```'
                    )
                ]
            }

    monkeypatch.setattr(gc, "_request_skills_loader", lambda: FakeSkillsLoader())
    monkeypatch.setattr(gc, "create_skill_execution_agent", lambda *_args, **_kwargs: FakeAgent())

    out = await gc._host_decide_by_agent(
        llm=object(),
        host_agent={
            "name": "四九",
            "description": "群聊主持人",
            "skills": [{"name": "群聊主持", "directory_name": "group-host"}],
        },
        agent_profiles=[{"name": "写作专家", "description": "写作"}],
        discussion_goal="继续写作",
        recent_messages="【用户】继续",
        last_speaker_agent_name=None,
        extra_system_prompt="",
        available_to_add=[{"name": "检索专家", "description": "检索"}],
        group_session_id="group-recruitment-with-member",
        app_settings={"host_profile": {"leader_agent_name": "四九"}},
        orchestration_profile="recruitment",
        session_item={},
    )

    assert out["next_speaker"] == "写作专家"
    assert "【可邀请专家列表】" not in calls["user_prompt"]
    assert "检索专家" not in calls["user_prompt"]


def test_leader_prompt_hides_skill_details_from_host():
    from app.agent.leader_scheduler import _build_leader_prompt

    prompt = _build_leader_prompt(
        [{"name": "专家A", "description": "文案"}],
        "完成文案任务",
        "最近对话",
        [{"name": "专家B", "description": "检索", "skills": [{"name": "检索", "directory_name": "skill-x"}]}],
        allow_recruitment=True,
    )
    assert "skills=" not in prompt
    assert "skill-x" not in prompt
    assert "先判断任务目标是否已经完成" in prompt
    assert "不要再安排专家做“总结答复”" in prompt
    assert "speaker_task" in prompt
    assert "不要输出 task_done、next_prompt" in prompt


def test_leader_prompt_hides_invitable_list_when_room_has_participants():
    from app.agent.leader_scheduler import _build_leader_prompt

    prompt = _build_leader_prompt(
        [{"name": "专家A", "description": "文案"}],
        "完成文案任务",
        "最近对话",
        [{"name": "专家B", "description": "检索"}],
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
        [{"name": "专家B", "description": "检索"}],
        allow_recruitment=True,
    )

    assert "可邀请的新成员" in prompt
    assert "专家B" in prompt


async def test_leader_decide_rejects_legacy_next_prompt():
    from app.agent.leader_scheduler import leader_decide

    class FakeClient:
        async def ainvoke(self, _messages):
            return type(
                "Resp",
                (),
                {
                    "content": (
                        '```json\n{"task_done": false, "next_speaker": "专家甲", '
                        '"next_prompt": "请继续写大纲", "reason": "继续"}\n```'
                    )
                },
            )()

    class FakeLLM:
        def get_client(self):
            return FakeClient()

    out = await leader_decide(
        FakeLLM(),
        [{"name": "专家甲", "description": "写作"}],
        "写网文",
        "最近对话",
    )

    from app.agent.group_host_decision import HOST_PROTOCOL_ERROR_MESSAGE

    assert out["next_speaker"] == "user"
    assert out["announcement"] == HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == "protocol_error"


@pytest.mark.asyncio
async def test_leader_decide_protocol_error_is_user_visible():
    from app.agent.leader_scheduler import leader_decide
    from app.agent.group_host_decision import HOST_PROTOCOL_ERROR_MESSAGE
    from app.agent.messages import AIMessage

    class FakeClient:
        async def ainvoke(self, _messages):
            return AIMessage(
                content=(
                    "我来安排：\n"
                    '```json\n{"current_phase": "阶段1", "next_speaker": "专家甲", "speaker_task": "请写大纲"}\n```'
                )
            )

    class FakeLLM:
        def get_client(self):
            return FakeClient()

    out = await leader_decide(
        FakeLLM(),
        [{"name": "专家甲", "description": "写作"}],
        "写大纲",
        "【用户】写大纲",
        orchestration_profile="scene",
    )

    assert out["next_speaker"] == "user"
    assert out["announcement"] == HOST_PROTOCOL_ERROR_MESSAGE
    assert out["interrupt_reason"] == "protocol_error"
    assert out["decision_source"] == "system_guard"
