"""Central registry for platform-owned LLM prompt templates.

Runtime modules may request templates by `prompt_id` and pass structured
variables, but they must not embed multi-line platform prompts directly.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
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


def _load_prompt_templates() -> dict[str, str]:
    """Load platform-owned prompt templates from the standalone registry file."""
    templates_path = Path(__file__).with_name("platform_prompt_templates.json")
    raw = json.loads(templates_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("platform prompt templates must be a JSON object")
    templates: dict[str, str] = {}
    for prompt_id, template in raw.items():
        if not isinstance(prompt_id, str) or not prompt_id.strip():
            raise ValueError("platform prompt_id must be a non-empty string")
        if not isinstance(template, str) or not template.strip():
            raise ValueError(f"platform prompt template is empty: {prompt_id}")
        templates[prompt_id] = template.strip()
    return templates


PLATFORM_PROMPTS: dict[str, PlatformPrompt] = {
    prompt_id: _prompt(prompt_id, template)
    for prompt_id, template in _load_prompt_templates().items()
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
