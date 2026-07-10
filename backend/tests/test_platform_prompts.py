import ast
import pytest
from pathlib import Path

from app.agent.platform_prompts import PLATFORM_PROMPTS, get_platform_prompt, render_platform_prompt


ROOT = Path(__file__).resolve().parents[2]
PROMPT_TEMPLATE_FILE = ROOT / "backend/app/agent/platform_prompt_templates.json"


def test_platform_prompts_are_registered_by_prompt_id():
    assert "host.select_next_speaker.v1" in PLATFORM_PROMPTS
    assert get_platform_prompt("host.select_next_speaker.v1").prompt_id == "host.select_next_speaker.v1"


def test_platform_prompt_templates_live_in_standalone_file():
    """Platform prompt text belongs in one template file, not in the Python registry."""
    assert PROMPT_TEMPLATE_FILE.exists()
    registry_text = (ROOT / "backend/app/agent/platform_prompts.py").read_text(encoding="utf-8")
    template_text = PROMPT_TEMPLATE_FILE.read_text(encoding="utf-8")

    for phrase in [
        "你是书童四九平台的会话主持人",
        "你是当前专家的 Skill 选择器",
        "请基于用户第一条有效输入生成一个简短会话标题",
    ]:
        assert phrase in template_text
        assert phrase not in registry_text


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
        ROOT / "backend/app/agent/expert_runtime.py",
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
        "检测到重复工具调用，已停止继续重试",
        "重复的工作区写入已忽略",
        "以下最近讨论仅供承接上下文；本轮用户输入优先。",
        "上一位专家：",
        "请按系统提示选择本轮唯一 Skill。",
    ]:
        assert phrase not in combined
    for prompt_id in [
        "host.system.boundary.v1",
        "expert.select_skill.user_prompt.v1",
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
        "agent.repeated_tool_guard.v1",
        "agent.duplicate_workspace_write_guard.v1",
        "expert.context.reference_notice.v1",
        "host.previous_speaker.v1",
        "expert.action.goal_section.v1",
        "expert.action.input_section.v1",
        "title.group_topic.user_messages.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_expert_action_repair_sections_use_platform_prompt_registry():
    runtime_text = (ROOT / "backend/app/agent/group_chat_memory_prompt.py").read_text(encoding="utf-8")

    for phrase in [
        'parts.append(f"【群聊讨论目标】\\n{discussion_goal}")',
        'parts.append(f"【输入依据】\\n{context_excerpt}")',
    ]:
        assert phrase not in runtime_text

    for prompt_id in [
        "expert.action.goal_section.v1",
        "expert.action.input_section.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_expert_action_prompt_builders_do_not_name_llm_inputs_as_context():
    """LLM-visible prompt inputs should use prompt terminology, not generic context naming."""
    module_text = (ROOT / "backend/app/agent/group_chat_memory_prompt.py").read_text(encoding="utf-8")
    tree = ast.parse(module_text)
    prompt_builder_names = {
        "_build_default_action_prompt",
        "_build_action_prompt_with_memory",
        "_ensure_structured_action_prompt",
        "build_checked_expert_action_prompt",
    }

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name not in prompt_builder_names:
            continue
        arg_names = {arg.arg for arg in node.args.args + node.args.kwonlyargs}
        local_names = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)}
        assert "context" not in arg_names, node.name
        assert "context_excerpt" not in local_names, node.name


def test_group_title_user_messages_use_platform_prompt_registry():
    runtime_text = (ROOT / "backend/app/agent/group_chat_title_meta.py").read_text(encoding="utf-8")

    assert '"最近用户发言：\\n"' not in runtime_text
    assert "title.group_topic.user_messages.v1" in PLATFORM_PROMPTS


def test_host_agent_catalog_sections_use_platform_prompt_registry():
    """Host scheduler catalog labels belong in platform prompt templates."""
    runtime_text = (ROOT / "backend/app/agent/group_chat_host_runtime.py").read_text(encoding="utf-8")

    for phrase in [
        "当前会话成员：",
        "可建议邀请的专家：",
    ]:
        assert phrase not in runtime_text

    rendered_members = render_platform_prompt("host.agent_catalog.members.v1", {"member_lines": "- 写作专家: 写作"})
    rendered_invitable = render_platform_prompt("host.agent_catalog.invitable.v1", {"invitable_lines": "- 检索专家: 检索"})

    assert "当前会话成员：" in rendered_members
    assert "可建议邀请的专家：" in rendered_invitable


def test_user_attachment_prompt_section_uses_platform_prompt_registry():
    """Attachment labels are part of the expert-visible user prompt."""
    runtime_text = (ROOT / "backend/app/agent/group_chat_runtime.py").read_text(encoding="utf-8")

    assert "【工作区附件】" not in runtime_text

    rendered = render_platform_prompt("user.attachments.section.v1", {"attachment_lines": "- input.md: docs/input.md"})

    assert "【工作区附件】" in rendered
    assert "- input.md: docs/input.md" in rendered


def test_workspace_rename_prompt_uses_current_target_path_schema():
    """The workspace rename prompt must name the current tool argument."""
    rendered = render_platform_prompt("skill.execution.workspace_tool.rename.v1", {})

    assert "target_path" in rendered
    assert "new_name" not in rendered


def test_platform_prompt_templates_do_not_depend_on_raw_tool_stream_fields():
    """Prompt templates must not ask the model to reason from raw tool stdout/stderr fields."""
    template_text = PROMPT_TEMPLATE_FILE.read_text(encoding="utf-8")

    for phrase in [
        "基于上方工具结果中的 stdout",
        "stdout/stderr",
        "returncode",
        "stdout_block",
        "stderr_block",
    ]:
        assert phrase not in template_text


def test_runtime_does_not_pass_removed_tool_stream_prompt_variables():
    """Runtime call sites must not preserve removed stdout/stderr prompt variables."""
    runtime_text = (ROOT / "backend/app/agent/simple_agent_finalization.py").read_text(encoding="utf-8")

    assert "stdout_block" not in runtime_text
    assert "stderr_block" not in runtime_text


def test_expert_turn_missing_sections_use_platform_prompt_registry():
    builder_text = (ROOT / "backend/app/agent/group_chat_prompt_builder.py").read_text(encoding="utf-8")

    for phrase in [
        "主持人本轮指派（必须按此执行；与下方模板冲突时以本段为准）",
        "【本轮用户输入】\\n{current_user_input}",
        "【最近讨论】\\n{recent_context}",
    ]:
        assert phrase not in builder_text

    for prompt_id in [
        "expert.turn.host_instruction_section.v1",
        "expert.turn.user_input_section.v1",
        "expert.turn.recent_context_section.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_default_expert_turn_text_uses_platform_prompt_registry():
    """Fallback text that enters LLM prompts must come from the platform prompt registry."""
    runtime_text = (ROOT / "backend/app/agent/group_chat_runtime.py").read_text(encoding="utf-8")
    builder_text = (ROOT / "backend/app/agent/group_chat_prompt_builder.py").read_text(encoding="utf-8")

    assert "请根据用户输入完成任务。" not in runtime_text
    assert "待用户提出讨论主题" not in runtime_text
    assert "待用户提出讨论主题" not in builder_text

    for prompt_id in [
        "expert.turn.default_next_action.v1",
        "session.discussion_goal.default.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_workspace_visibility_tool_messages_use_platform_prompt_registry():
    """LLM-visible workspace tool guidance belongs in the central prompt registry."""
    visibility_text = (ROOT / "backend/app/agent/workspace_visibility.py").read_text(encoding="utf-8")

    assert "请读取用户明确提供的工作区文件" not in visibility_text
    assert "调度任务会由平台直接放在本轮提示词中" not in visibility_text
    assert "不能通过工作区文件工具访问" not in visibility_text

    rendered = render_platform_prompt(
        "workspace.visibility.internal_diagnostic_path_error.v1",
        {"path": "memory/messages/trace.jsonl"},
    )

    assert "memory/messages/trace.jsonl" in rendered
    assert "请读取用户明确提供的工作区文件" in rendered

    rendered = render_platform_prompt(
        "workspace.visibility.internal_system_path_error.v1",
        {"path": "memory"},
    )

    assert "memory" in rendered
    assert "内部系统目录" in rendered


def test_backend_prompts_do_not_teach_legacy_file_ref_protocol():
    files = [
        ROOT / "backend/app/agent/platform_prompts.py",
        ROOT / "backend/app/mcp/stdio/file_reader_mcp.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    assert "【文件引用" not in combined
    assert not (ROOT / "backend/app/agent/file_ref_resolver.py").exists()


def test_backend_prompts_do_not_teach_generic_call_api_tool():
    runtime_text = (ROOT / "backend/app/agent/skill_agent_runtime.py").read_text(encoding="utf-8")
    prompt_text = (ROOT / "backend/app/agent/platform_prompts.py").read_text(encoding="utf-8")

    assert "call_api_rules" not in runtime_text
    assert "skill.execution.call_api_rules.v1" not in PLATFORM_PROMPTS
    assert "## 外部 HTTP（call_api）" not in prompt_text
    assert "使用 `call_api`" not in prompt_text


def test_call_api_module_does_not_export_generic_llm_tool():
    """Saved HTTP API execution may reuse the helper, but generic call_api is not an LLM tool."""
    module_text = (ROOT / "backend/app/tools/call_api.py").read_text(encoding="utf-8")

    assert "def _call_api_impl" in module_text
    assert "call_api = ToolSpec.from_function" not in module_text
    assert 'name="call_api"' not in module_text


def test_skill_runtime_tool_error_messages_use_platform_prompt_registry():
    runtime_text = (ROOT / "backend/app/agent/skill_agent_runtime.py").read_text(encoding="utf-8")
    result_records_text = (ROOT / "backend/app/agent/skill_tool_result_records.py").read_text(encoding="utf-8")
    combined = runtime_text + "\n" + result_records_text

    forbidden_runtime_prompt_fragments = [
        "工具 {tool_name} 执行错误:",
        "工具 {tool_name} 不存在",
        "工具调用解析错误:",
        "当前专家未启用 read_workspace_file",
    ]
    for phrase in forbidden_runtime_prompt_fragments:
        assert phrase not in combined

    for prompt_id in [
        "skill.execution.tool_error_message.v1",
        "skill.execution.tool_missing_message.v1",
        "skill.execution.tool_parse_error_message.v1",
        "skill.execution.read_workspace_unavailable.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_read_workspace_file_tool_messages_use_platform_prompt_registry():
    """LLM-visible read_workspace_file tool guidance belongs in the shared prompt registry."""
    tool_text = (ROOT / "backend/app/tools/read_file.py").read_text(encoding="utf-8")

    for phrase in [
        "请根据最近工具结果生成最终答复，不要调用 read_workspace_file。",
        "不要继续猜测文件名；请先调用 list_workspace_directory 查看真实路径。",
    ]:
        assert phrase not in tool_text

    for prompt_id in [
        "workspace.read_file.pseudo_field_error.v1",
        "workspace.read_file.not_found.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_simple_agent_missing_tool_response_uses_platform_prompt_registry():
    """ToolMessage content returned to the LLM belongs in the shared prompt registry."""
    module_text = (ROOT / "backend/app/agent/simple_agent_tool_ids.py").read_text(encoding="utf-8")

    assert "未继续执行" not in module_text
    assert "agent.tool_call.missing_response.v1" in PLATFORM_PROMPTS


def test_skill_workspace_tool_lines_use_platform_prompt_registry():
    """LLM-visible workspace tool descriptions belong in the shared prompt registry."""
    runtime_text = (ROOT / "backend/app/agent/skill_agent_runtime.py").read_text(encoding="utf-8")

    for phrase in [
        "读取工作区内相对路径对应的文件内容",
        "将文本写入工作区文件",
        "对工作区内文件做增量修改",
        "重命名工作区内文件或目录",
        "在工作区内新建目录",
        "递归列出目录中文件",
    ]:
        assert phrase not in runtime_text

    for prompt_id in [
        "skill.execution.workspace_tool.read.v1",
        "skill.execution.workspace_tool.write.v1",
        "skill.execution.workspace_tool.edit.v1",
        "skill.execution.workspace_tool.rename.v1",
        "skill.execution.workspace_tool.mkdir.v1",
        "skill.execution.workspace_tool.list.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_unverified_delivery_guard_messages_use_platform_prompt_registry():
    """Platform-authored delivery guard messages belong in the shared prompt registry."""
    module_text = (ROOT / "backend/app/agent/group_chat_tool_trace.py").read_text(encoding="utf-8")

    for phrase in [
        "本轮没有确认文件生成成功。",
        "平台没有捕获到成功的文件、图片或工作区写入工具结果，因此不能把专家回复中的生成/保存声明视为已完成。",
        "原回复提到的路径或链接：",
        "本轮工具返回摘要：",
        "请重新发起生成，或让专家先完成真实工具调用后再交付文件链接。",
        "请重新发起生成，或启用对应专家的文件/图片生成工具后再试。",
    ]:
        assert phrase not in module_text

    for prompt_id in [
        "delivery.guard.unverified_title.v1",
        "delivery.guard.unverified_reason.v1",
        "delivery.guard.mentioned_paths_header.v1",
        "delivery.guard.tool_summary_header.v1",
        "delivery.guard.retry_after_tool_call.v1",
        "delivery.guard.retry_after_missing_tool.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_builtin_workspace_tool_schema_descriptions_use_platform_prompt_registry():
    """ToolSpec descriptions and field schema text are LLM-visible prompt material."""
    files = [
        ROOT / "backend/app/tools/read_file.py",
        ROOT / "backend/app/tools/write_workspace_file.py",
        ROOT / "backend/app/agent/tools_for_skill.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)

    for phrase in [
        "读取用户引用的文件内容。path 为工作区内相对路径",
        "将文本内容写入当前 Chat 对应的工作区",
        "在当前工作区对文本文件做增量编辑",
        "重命名或移动当前工作区内的文件/目录。",
        "在当前工作区新建目录。",
        "递归列出当前工作区目录内容（含子目录）。",
        "工作区内相对路径，如 notes/report.md",
        "要保存的完整文本内容；若为空则工具会报错并提示重新传入。",
        "是否允许覆盖同名文件。",
        "要替换的旧文本",
        "替换后的新文本",
        "目标相对路径，例如 notes/key.md",
        "目录相对路径，留空表示工作区根目录",
        "查看本轮 Skill 声明但未可用的 MCP 配置问题。",
    ]:
        assert phrase not in combined

    for prompt_id in [
        "tool.description.read_workspace_file.v1",
        "tool.description.write_workspace_file.v1",
        "tool.description.edit_workspace_file.v1",
        "tool.description.rename_workspace_file.v1",
        "tool.description.mkdir_workspace.v1",
        "tool.description.list_workspace_directory.v1",
        "tool.schema.read_workspace_file.path.v1",
        "tool.schema.write_workspace_file.path.v1",
        "tool.schema.write_workspace_file.content.v1",
        "tool.schema.write_workspace_file.overwrite.v1",
        "tool.schema.edit_workspace_file.path.v1",
        "tool.schema.edit_workspace_file.old_text.v1",
        "tool.schema.edit_workspace_file.new_text.v1",
        "tool.schema.rename_workspace_file.path.v1",
        "tool.schema.rename_workspace_file.target_path.v1",
        "tool.schema.mkdir_workspace.path.v1",
        "tool.schema.list_workspace_directory.path.v1",
        "tool.description.mcp_configuration_status.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_saved_http_api_tool_schema_descriptions_use_platform_prompt_registry():
    """Saved HTTP API tool schema text is LLM-visible platform prompt material."""
    module_text = (ROOT / "backend/app/tools/http_api_tool.py").read_text(encoding="utf-8")

    for phrase in [
        "调用已保存的 HTTP API 工具",
        "追加或覆盖默认查询参数。",
        "追加或覆盖默认请求头。",
        "覆盖默认请求体；对象会自动序列化为 JSON。",
    ]:
        assert phrase not in module_text

    for prompt_id in [
        "tool.description.saved_http_api.v1",
        "tool.schema.saved_http_api.query.v1",
        "tool.schema.saved_http_api.headers.v1",
        "tool.schema.saved_http_api.body.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_image_generation_default_user_prompt_uses_platform_prompt_registry():
    """Image tool default user prompt text belongs in the shared prompt registry."""
    tool_text = (ROOT / "backend/app/tools/chatanywhere_image_cli_lib.py").read_text(encoding="utf-8")

    assert "请生成尺寸约为" not in tool_text
    assert "image_generation.default_user_prompt.v1" in PLATFORM_PROMPTS

    rendered = render_platform_prompt(
        "image_generation.default_user_prompt.v1",
        {"description": "河南烩面", "pic_size": "1024x1792"},
    )

    assert rendered == "河南烩面\n\n请生成尺寸约为 1024x1792 的图片，输出图像内容。"
