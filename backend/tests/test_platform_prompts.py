import pytest
from pathlib import Path

from app.agent.platform_prompts import PLATFORM_PROMPTS, get_platform_prompt, render_platform_prompt


ROOT = Path(__file__).resolve().parents[2]


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
    assert "只允许输出上述字段" in rendered


def test_prompt_render_rejects_missing_variables():
    with pytest.raises(KeyError):
        render_platform_prompt("title.generate.v1", {})


def test_platform_owned_llm_prompt_text_is_not_embedded_in_runtime_modules():
    runtime_files = [
        ROOT / "backend/app/agent/group_chat_host_runtime.py",
        ROOT / "backend/app/agent/group_context.py",
        ROOT / "backend/app/agent/group_chat_memory_prompt.py",
        ROOT / "backend/app/agent/group_chat_prompt_builder.py",
        ROOT / "backend/app/agent/group_chat_presentation_rewriter.py",
        ROOT / "backend/app/agent/expert_self_awareness.py",
        ROOT / "backend/app/agent/simple_agent_messages.py",
        ROOT / "backend/app/agent/skill_agent_runtime.py",
        ROOT / "backend/app/agent/simple_agent.py",
        ROOT / "backend/app/agent/simple_agent_finalization.py",
        ROOT / "backend/app/agent/skill_session_contract.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files)
    for phrase in [
        "【你这一轮的任务】",
        "【你本轮要完成的事情】",
        "请紧扣讨论目标发言",
        "请按系统规则输出前端最终展示文案",
        "若用户询问你有哪些 skill",
        "上一条回复因为输出长度限制中断了",
        "## 多步任务规则",
        "请直接基于上方工具结果中的 stdout",
        "## 技能脚本工具",
        "工具已经执行完成。请基于最近的工具返回",
        "你是书童四九平台主持人，只负责调度，不代替专家回答业务内容。",
        "非脚本 Skill、MCP / HTTP / workspace 工具后的流程判断",
        "上一步没有产生可执行的工具调用，平台未执行任何文件操作。",
        "本轮工具调用格式不符合要求，平台未执行文件操作；",
        "以下最近讨论仅供承接上下文；本轮用户输入优先。",
        "上一位专家：",
    ]:
        assert phrase not in combined
    for prompt_id in [
        "host.system.boundary.v1",
        "expert.action.default.v1",
        "expert.action.memory.v1",
        "expert.action.structured_missing.v1",
        "skill.execution.extra_instructions.v1",
        "skill.execution.multi_step_preface.v1",
        "skill.execution.script_done_instruction.v1",
        "skill.execution.tool_message_content.v1",
        "agent.final_synthesis.after_tool_success.v1",
        "agent.final_synthesis.after_tool_outputs.v1",
        "agent.continuation.after_output_limit.v1",
        "expert.self_awareness.v1",
        "expert.turn.default_task.v1",
        "expert.turn.user_content.v1",
        "presentation.rewrite.user_prompt.v1",
        "skill.session.state_instruction.v1",
        "agent.text_tool_protocol.retry.v1",
        "agent.text_tool_protocol.failure.v1",
        "expert.context.reference_notice.v1",
        "host.previous_speaker.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_backend_prompts_do_not_teach_legacy_file_ref_protocol():
    files = [
        ROOT / "backend/app/agent/platform_prompts.py",
        ROOT / "backend/app/mcp/stdio/file_reader_mcp.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "【文件引用" not in combined
    assert not (ROOT / "backend/app/agent/file_ref_resolver.py").exists()
