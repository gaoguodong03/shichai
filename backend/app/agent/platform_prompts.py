"""Central registry for platform-owned LLM prompt templates.

Runtime modules may request templates by `prompt_id` and pass structured
variables, but they must not embed multi-line platform prompts directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from string import Formatter
from typing import Mapping


@dataclass(frozen=True)
class PlatformPrompt:
    prompt_id: str
    template: str
    required_variables: tuple[str, ...]

    def render(self, variables: Mapping[str, object]) -> str:
        """Render one registered prompt after verifying all declared variables."""
        missing = [name for name in self.required_variables if name not in variables]
        if missing:
            raise KeyError(f"missing prompt variables for {self.prompt_id}: {', '.join(missing)}")
        return self.template.format(**{key: str(value) for key, value in variables.items()})


def _template_variables(template: str) -> tuple[str, ...]:
    names: list[str] = []
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name and field_name not in names:
            names.append(field_name)
    return tuple(names)


def _prompt(prompt_id: str, template: str) -> PlatformPrompt:
    return PlatformPrompt(prompt_id=prompt_id, template=template.strip(), required_variables=_template_variables(template))


PLATFORM_PROMPTS: dict[str, PlatformPrompt] = {
    "host.select_next_speaker.v1": _prompt(
        "host.select_next_speaker.v1",
        """
你是书童四九平台的会话主持人。请只根据当前会话成员、用户输入、历史摘要和当前阶段决定下一位发言者。

可选专家：
{agent_names}

当前阶段：
{current_phase}

用户输入：
{user_message}

最近讨论：
{recent_history}

必须输出单个 JSON 对象，字段只能是：
{{
  "current_phase": "阶段",
  "next_speaker": "专家名称|user|end",
  "next_action": "下一步动作说明",
  "suggested_add_agent_names": ["可邀请专家名称"]
}}
只允许输出上述字段；不要输出任何额外字段或解释文本。
        """,
    ),
    "expert.select_skill.v1": _prompt(
        "expert.select_skill.v1",
        """
你是当前专家的 Skill 选择器。请只从候选 Skill 目录名中选择一个最适合本轮任务的 Skill。

专家名称：
{agent_name}

专家职责：
{agent_description}

讨论目标：
{discussion_goal}

本轮用户输入：
{user_prompt}

候选 Skill：
{skill_directories}

主持人下一步动作：
{next_action}

必须输出单个 JSON 对象，字段只能是：
{{
  "selected_skill": "skill-directory"
}}
        """,
    ),
    "title.generate.v1": _prompt(
        "title.generate.v1",
        """
请基于用户第一条有效输入生成一个简短会话标题，最多 18 个中文字符，不要解释。

用户输入：
{user_message}
        """,
    ),
    "title.group_topic.v1": _prompt(
        "title.group_topic.v1",
        """
你是中文会议主题提取器。根据下面用户在群聊中的发言，提取当前讨论的核心主题。

输出要求：
- 只输出“主题本身”，不要输出任何前缀（如：主题/讨论主题/群聊/标题/：）
- 中文主题，长度约 15 字，最多 {max_chars} 字
- 不要使用引号或括号，不要以句号、感叹号或问号结尾
        """,
    ),
    "presentation.rewrite.v1": _prompt(
        "presentation.rewrite.v1",
        """
你是群聊前端展示层的表达整理器。

你的任务只是在不改变业务结果的前提下，把专家本轮原始回复整理成用户可读的 Markdown。

硬性规则：
- 只改变表达、排版、结构和语气，不新增事实、链接、路径、数量、状态或结论。
- 不删除用户判断任务所必需的信息；可以合并重复内容、压缩冗长正文。
- 不继续检索、不调用工具、不分析下一步执行方案。
- 不改变成功、失败、等待用户补充、需要确认等状态。
- 如果原文是 JSON、工具结果、Title/URL/Highlights 列表或混杂格式，整理成自然的中文说明、列表或表格。
- 只输出整理后的 Markdown 正文，不要解释你的改写过程。
        """,
    ),
    "skill.execution.tools_header.v1": _prompt(
        "skill.execution.tools_header.v1",
        """
你可以使用以下工具：
{tool_lines}
        """,
    ),
    "skill.execution.exa_search.v1": _prompt(
        "skill.execution.exa_search.v1",
        """
## Exa 搜索工具使用说明
调用 {tool_name} 时必须使用参数名 query（必需）传递搜索关键词，不要使用 __arg1。示例：{{"query": "北京 烟花 燃放", "numResults": 10}}。
可选参数：numResults（数量）、livecrawl（'fallback'|'preferred'|'always'|'never'）、type（'auto'|'fast'）。type 不要用 'news' 等无效值。
        """,
    ),
    "skill.execution.response_policy.v1": _prompt(
        "skill.execution.response_policy.v1",
        """
当你需要使用工具时，选择当前运行环境提供的可用工具并填写参数。

当你不需要使用工具时，直接回复用户的问题。
        """,
    ),
}


def get_platform_prompt(prompt_id: str) -> PlatformPrompt:
    """Return one platform prompt by stable id and fail loudly when missing."""
    try:
        return PLATFORM_PROMPTS[prompt_id]
    except KeyError as exc:
        raise KeyError(f"unknown platform prompt_id: {prompt_id}") from exc


def render_platform_prompt(prompt_id: str, variables: Mapping[str, object]) -> str:
    """Render a platform prompt without exposing template storage to callers."""
    return get_platform_prompt(prompt_id).render(variables)
