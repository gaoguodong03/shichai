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

候选 Skill：
{skill_directories}

本轮任务：
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
