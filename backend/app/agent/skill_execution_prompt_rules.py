"""Skill 执行附加 Prompt 规则。

本文件只根据本轮实际绑定工具生成平台内置 Prompt 片段；模板正文仍由
platform_prompt_templates.json 提供，不在运行时文件中散落大段提示词。
"""
from __future__ import annotations

from datetime import datetime
from typing import List

from app.agent.platform_prompts import render_platform_prompt
from app.agent.skill_tool_result_records import _tool_mcp_identity
from app.agent.tool_spec import ToolSpec


def _current_workspace_file_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S") + "00"


def skill_execution_extra_instructions(tools: List[ToolSpec]) -> str:
    """随实际绑定工具生成多步、工作区、脚本和 MCP 说明，避免未绑定能力误导模型。"""
    names = {getattr(t, "name", "") for t in tools}
    script_names = sorted(n for n in names if n.startswith("run_skill_script_"))
    preface = ""
    if not script_names:
        preface = render_platform_prompt("skill.execution.multi_step_preface.v1", {})
    file_lines: List[str] = []
    if "read_workspace_file" in names:
        file_lines.append(render_platform_prompt("skill.execution.workspace_tool.read.v1", {}))
    if "write_workspace_file" in names:
        file_lines.append(render_platform_prompt("skill.execution.workspace_tool.write.v1", {}))
    if "edit_workspace_file" in names:
        file_lines.append(render_platform_prompt("skill.execution.workspace_tool.edit.v1", {}))
    if "rename_workspace_file" in names:
        file_lines.append(render_platform_prompt("skill.execution.workspace_tool.rename.v1", {}))
    if "mkdir_workspace" in names:
        file_lines.append(render_platform_prompt("skill.execution.workspace_tool.mkdir.v1", {}))
    if "list_workspace_directory" in names:
        file_lines.append(render_platform_prompt("skill.execution.workspace_tool.list.v1", {}))
    workspace_tool_rules = ""
    if file_lines:
        timestamp_rule = ""
        if "write_workspace_file" in names:
            timestamp_rule = render_platform_prompt("skill.execution.timestamp_rule.v1", {"timestamp": _current_workspace_file_timestamp()})
        workspace_tool_rules = render_platform_prompt(
            "skill.execution.workspace_rules.v1",
            {
                "file_tool_lines": "\n".join(file_lines),
                "timestamp_rule": timestamp_rule,
                "read_rule": render_platform_prompt("skill.execution.workspace_read_rule.v1", {}) if "read_workspace_file" in names else "",
                "write_rule": render_platform_prompt("skill.execution.workspace_write_rule.v1", {}) if "write_workspace_file" in names or "edit_workspace_file" in names else "",
                "workspace_task_file_rule": render_platform_prompt("skill.execution.workspace_task_file_rule.v1", {}) if "write_workspace_file" in names else "",
                "material_rule": render_platform_prompt("skill.execution.workspace_material_rule.v1", {}) if "write_workspace_file" in names else "",
            },
        )
    audio_asr_rules = render_platform_prompt("skill.execution.audio_asr_rules.v1", {}) if "audio-asr_transcribe_audio_file" in names else ""
    script_tool_rules = (
        render_platform_prompt("skill.execution.script_tool_rules.v1", {"script_tool_names": "\n".join(f"- `{n}`" for n in script_names)})
        if script_names
        else ""
    )
    mcp_names = sorted({getattr(t, "name", "") for t in tools if any(_tool_mcp_identity(t))})
    mcp_tool_rules = (
        render_platform_prompt("skill.execution.mcp_tool_rules.v1", {"mcp_tool_names": "\n".join(f"- `{n}`" for n in mcp_names)})
        if mcp_names
        else ""
    )
    rendered = render_platform_prompt(
        "skill.execution.extra_instructions.v1",
        {
            "workspace_tool_rules": workspace_tool_rules,
            "audio_asr_rules": audio_asr_rules,
            "script_tool_rules": script_tool_rules,
            "mcp_tool_rules": mcp_tool_rules,
        },
    )
    return (preface + rendered).strip() + ("\n\n" if rendered.strip() or preface else "")
