import ast
import importlib
import pytest
from pathlib import Path

from app.agent.platform_prompts import PLATFORM_PROMPTS, get_platform_prompt, render_platform_prompt


ROOT = Path(__file__).resolve().parents[2]
PROMPT_TEMPLATE_FILE = ROOT / "backend/app/agent/platform_prompt_templates.json"


def test_platform_prompts_are_registered_by_prompt_id():
    assert "host.select_next_speaker.v1" in PLATFORM_PROMPTS
    assert get_platform_prompt("host.select_next_speaker.v1").prompt_id == "host.select_next_speaker.v1"


def test_shared_session_prompt_orders_project_before_scenario_once():
    session_prompt = importlib.import_module("app.agent.session_prompt")

    rendered = session_prompt.build_shared_session_prompt(
        {"system_prompt": "项目整体规则"},
        {"scenario_prompt": "场景共享任务契约"},
    )

    assert rendered == "项目整体规则\n\n场景共享任务契约"
    assert rendered.count("项目整体规则") == 1
    assert rendered.count("场景共享任务契约") == 1
    assert session_prompt.build_shared_session_prompt({"system_prompt": "项目整体规则"}, {}) == "项目整体规则"


def test_user_owned_host_and_expert_prompts_have_no_backend_default_fallback():
    settings = (ROOT / "backend/app/api/settings_app.py").read_text(encoding="utf-8")
    host_runtime = (ROOT / "backend/app/agent/group_chat_runtime.py").read_text(encoding="utf-8")
    expert_runtime = (ROOT / "backend/app/agent/expert_runtime.py").read_text(encoding="utf-8")

    assert "host.system.default.v1" not in PLATFORM_PROMPTS
    assert "expert.system.default.v1" not in PLATFORM_PROMPTS
    assert not (ROOT / "backend/app/agent/host_prompt.py").exists()
    assert not (ROOT / "backend/app/agent/expert_prompt.py").exists()
    assert "get_default_host_system_prompt" not in settings + host_runtime
    assert "get_expert_system_prompt" not in expert_runtime
    assert 'str(host.get("system_prompt") or "").strip()' in host_runtime
    assert 'str(agent_profile.get("system_prompt") or "").strip()' in expert_runtime


def test_platform_prompt_templates_live_in_standalone_file():
    """Platform prompt text belongs in one template file, not in the Python registry."""
    assert PROMPT_TEMPLATE_FILE.exists()
    registry_text = (ROOT / "backend/app/agent/platform_prompts.py").read_text(encoding="utf-8")
    template_text = PROMPT_TEMPLATE_FILE.read_text(encoding="utf-8")

    for phrase in [
        "你是当前专家的 Skill 选择器",
        "请基于用户第一条有效输入生成一个简短会话标题",
    ]:
        assert phrase in template_text
        assert phrase not in registry_text


def test_host_runtime_prompt_contains_inputs_without_repeating_long_term_contract():
    rendered = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": "写作专家",
            "current_phase": "资料收集",
            "user_message": "写一篇文章",
            "recent_history": "无",
            "skill_sessions": '{"信息检索专家":{"skill":"research"}}',
        },
    )

    for runtime_value in ["写作专家", "资料收集", "写一篇文章", '{"信息检索专家":{"skill":"research"}}']:
        assert runtime_value in rendered
    assert '"message"' not in rendered
    assert '"target_agent_name"' not in rendered
    assert '"next_speaker"' not in rendered
    assert '"next_action"' not in rendered
    assert "只允许输出上述字段" not in rendered
    assert "你是书童四九平台的会话主持人" not in rendered


def test_host_prompts_preserve_confirmation_causality_across_expert_returns():
    runtime_prompt = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": "图片生成专家",
            "current_phase": "图片生成",
            "user_message": "同意",
            "recent_history": "用户同意方案后，专家才生成图片并请求确认",
            "skill_sessions": "（无）",
        },
    )
    retry_prompt = render_platform_prompt("host.select_next_speaker.protocol_retry.v1", {})

    assert "触发本轮请求的用户输入" in runtime_prompt
    assert "不能确认其后才产生的专家成果" in runtime_prompt
    assert "最近讨论仅用于判断任务是否完成" in runtime_prompt
    assert "不得复制、改写或续写任何讨论内容" in runtime_prompt
    assert "只输出主持人自己本轮的自然语言调度指令" in runtime_prompt
    assert "不得再次调度同一专家完成同一任务" in runtime_prompt
    assert "该消息之后才产生的专家成果" in retry_prompt
    assert "必须等待新的用户输入" in retry_prompt


def test_host_prompt_receives_skill_sessions_as_context_not_route_instruction():
    rendered = render_platform_prompt(
        "host.select_next_speaker.v1",
        {
            "agent_names": "信息检索专家",
            "current_phase": "等待用户确认",
            "user_message": "用户可以用任意方式表达当前意图",
            "recent_history": "信息检索专家已经整理过资料",
            "skill_sessions": '{"信息检索专家":{"skill":"research"}}',
        },
    )

    assert "当前 Skill Session" in rendered
    assert '{"信息检索专家":{"skill":"research"}}' in rendered


def test_collaboration_runtime_uses_shared_session_prompt_for_host_and_expert():
    group_runtime = (ROOT / "backend/app/agent/group_chat_runtime.py").read_text(encoding="utf-8")
    expert_turn = (ROOT / "backend/app/agent/group_chat_expert_turn.py").read_text(encoding="utf-8")

    assert "from app.agent.session_prompt import build_shared_session_prompt" in group_runtime
    assert group_runtime.count("build_shared_session_prompt(app_settings, session_item)") >= 2
    assert "from app.agent.session_prompt import build_shared_session_prompt" in expert_turn
    assert "extra_system_prompt=build_shared_session_prompt(app_settings, session_item)" in expert_turn


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
        "host.select_next_speaker.protocol_retry.v1",
        "expert.select_skill.user_prompt.v1",
        "expert.select_skill.protocol_retry.v1",
        "expert.action.default.v1",
        "expert.action.memory.v1",
        "expert.action.structured_missing.v1",
        "skill.execution.extra_instructions.v1",
        "skill.execution.multi_step_preface.v1",
        "skill.execution.script_done_instruction.v1",
        "skill.execution.tool_message_content.v1",
        "agent.after_tool_result.decision.v1",
        "agent.continuation.after_output_limit.v1",
        "expert.self_awareness.v1",
        "expert.turn.default_task.v1",
        "expert.turn.user_content.v1",
        "presentation.rewrite.user_prompt.v1",
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
    runtime_text = (ROOT / "backend/app/agent/group_chat_runtime.py").read_text(encoding="utf-8")
    template_text = PROMPT_TEMPLATE_FILE.read_text(encoding="utf-8")

    for phrase in [
        "主持人本轮指派（必须按此执行；与下方模板冲突时以本段为准）",
        "【本轮用户输入】\\n{current_user_input}",
        "【最近讨论】\\n{recent_context}",
    ]:
        assert phrase not in builder_text
        assert phrase not in runtime_text

    assert "recent_context" not in builder_text
    assert "recent_context" not in runtime_text
    assert "recent_context" not in template_text
    assert "memory_prompt" in builder_text
    assert "memory_prompt" in runtime_text
    assert "{memory_prompt}" in template_text

    for prompt_id in [
        "expert.turn.host_instruction_section.v1",
        "expert.turn.user_input_section.v1",
        "expert.turn.memory_prompt_section.v1",
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
        "path 不能是 JSON 包装字符串；请按工具 schema 传 path 参数。",
        "错误：未提供文件路径。",
        "read_workspace_file 只能读取当前工作区内的相对路径文件。",
        "read_workspace_file 需要会话上下文",
        "仅允许读取当前会话工作区内的文件",
        "不是 UTF-8 文本。",
        "读取文件失败",
    ]:
        assert phrase not in tool_text

    for prompt_id in [
        "workspace.read_file.pseudo_field_error.v1",
        "workspace.read_file.not_found.v1",
        "workspace.read_file.json_wrapped_path_error.v1",
        "workspace.read_file.missing_path.v1",
        "workspace.read_file.remote_path_error.v1",
        "workspace.read_file.missing_session.v1",
        "workspace.read_file.outside_workspace.v1",
        "workspace.read_file.non_utf8.v1",
        "workspace.read_file.read_failed.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_write_workspace_file_tool_messages_use_platform_prompt_registry():
    """LLM-visible write_workspace_file tool results belong in the shared prompt registry."""
    tool_text = (ROOT / "backend/app/tools/write_workspace_file.py").read_text(encoding="utf-8")

    for phrase in [
        "path 不能是 JSON 包装字符串；请按工具 schema 传 path 参数。",
        "write_workspace_file 需要提供 path",
        "错误：content 为空。",
        "content 不是可保存的最终正文",
        "请把要保存的完整正文传给 content。",
        "不在当前工作区内",
        "write_workspace_file 默认不覆盖同名文件",
        "写入工作区文件失败",
        "已写入当前 Chat 工作区文件",
    ]:
        assert phrase not in tool_text

    for prompt_id in [
        "workspace.write_file.json_wrapped_path_error.v1",
        "workspace.write_file.missing_path.v1",
        "workspace.write_file.missing_content.v1",
        "workspace.write_file.tool_call_payload_content_error.v1",
        "workspace.write_file.outside_workspace.v1",
        "workspace.write_file.exists_no_overwrite.v1",
        "workspace.write_file.write_failed.v1",
        "workspace.write_file.success.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_builtin_workspace_mutation_tool_messages_use_platform_prompt_registry():
    """Edit, rename, mkdir, and list tool results are LLM-visible ToolMessage content."""
    module_text = (ROOT / "backend/app/agent/builtin_workspace_tools.py").read_text(encoding="utf-8")

    for phrase in [
        "错误：文件不存在或是目录。",
        "错误：读取失败",
        "错误：未找到要替换的文本。",
        "错误：写入失败",
        "已编辑文件：",
        "错误：target_path 不能为空。",
        "错误：target_path 非法。",
        "错误：重命名失败",
        "已重命名文件：",
        "错误：path 不能为空。",
        "错误：path 非法。",
        "错误：新建目录失败",
        "已新建目录：",
        "错误：列出目录失败",
        "下：（空）",
        "下的内容（含子目录）",
    ]:
        assert phrase not in module_text

    for prompt_id in [
        "workspace.edit_file.not_found_or_directory.v1",
        "workspace.edit_file.read_failed.v1",
        "workspace.edit_file.old_text_not_found.v1",
        "workspace.edit_file.write_failed.v1",
        "workspace.edit_file.success.v1",
        "workspace.rename_file.missing_target_path.v1",
        "workspace.rename_file.invalid_target_path.v1",
        "workspace.rename_file.rename_failed.v1",
        "workspace.rename_file.success.v1",
        "workspace.mkdir.missing_path.v1",
        "workspace.mkdir.invalid_path.v1",
        "workspace.mkdir.failed.v1",
        "workspace.mkdir.success.v1",
        "workspace.list_dir.failed.v1",
        "workspace.list_dir.empty.v1",
        "workspace.list_dir.contents.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_simple_agent_missing_tool_response_uses_platform_prompt_registry():
    """ToolMessage content returned to the LLM belongs in the shared prompt registry."""
    module_text = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in [
            "backend/app/agent/simple_agent_tool_ids.py",
            "backend/app/agent/simple_agent.py",
            "backend/app/agent/simple_agent_streaming.py",
        ]
    )

    assert "未继续执行" not in module_text
    assert "工具执行器未返回结果消息" not in module_text
    assert "agent.tool_call.missing_response.v1" in PLATFORM_PROMPTS
    assert "agent.tool_call.missing_response.default_reason.v1" in PLATFORM_PROMPTS


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
        ROOT / "backend/app/agent/builtin_workspace_tools.py",
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
        "tool.schema.saved_http_api.workspace_file.v1",
    ]:
        assert prompt_id in PLATFORM_PROMPTS


def test_mcp_configuration_status_tool_message_uses_platform_prompt_registry():
    """mcp_configuration_status returns LLM-visible guidance, so its message belongs in the registry."""
    module_text = (ROOT / "backend/app/agent/tools_for_skill.py").read_text(encoding="utf-8")

    assert "本轮 Skill 声明的 MCP 工具未能加载，请先在资源中心配置对应环境变量后重试。" not in module_text
    assert "Skill 声明了该 MCP 工具，但资源中心没有对应配置。" not in module_text
    assert "MCP 配置引用了未设置的环境变量。" not in module_text
    for prompt_id in [
        "tool.result.mcp_configuration_unavailable.v1",
        "tool.result.mcp_config_missing.v1",
        "tool.result.mcp_secret_missing.v1",
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
