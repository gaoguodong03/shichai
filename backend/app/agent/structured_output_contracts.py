"""Strict Pydantic contracts for LLM/tool control JSON."""
from __future__ import annotations

import json
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class StructuredOutputProtocolError(ValueError):
    """Raised when a model/tool control payload violates the strict protocol."""

    def __init__(self, message: str, *, schema_name: str = "", raw_output: str = "", details: Any = None):
        super().__init__(message)
        self.schema_name = schema_name
        self.raw_output = raw_output
        self.details = details


_T = TypeVar("_T", bound=BaseModel)
_JSON_FENCE_RE = re.compile(r"\A```json\s*\n?(?P<body>.*?)\n?```\s*\Z", re.S | re.I)


def strict_json_object_from_text(text: str, *, schema_name: str = "") -> dict[str, Any]:
    """Accept only a naked JSON object or one json code fence with no surrounding text."""
    raw = str(text or "")
    stripped = raw.strip()
    if not stripped:
        raise StructuredOutputProtocolError("empty structured output", schema_name=schema_name, raw_output=raw)
    match = _JSON_FENCE_RE.match(stripped)
    if match:
        stripped = match.group("body").strip()
    elif not (stripped.startswith("{") and stripped.endswith("}")):
        raise StructuredOutputProtocolError("structured output must be a single JSON object", schema_name=schema_name, raw_output=raw)
    try:
        payload = json.loads(stripped)
    except Exception as exc:
        raise StructuredOutputProtocolError(
            f"invalid JSON object: {exc}",
            schema_name=schema_name,
            raw_output=raw,
        ) from exc
    if not isinstance(payload, dict):
        raise StructuredOutputProtocolError("structured output JSON must be an object", schema_name=schema_name, raw_output=raw)
    return payload


def parse_strict_pydantic_object(text: str, model: type[_T]) -> _T:
    payload = strict_json_object_from_text(text, schema_name=model.__name__)
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise StructuredOutputProtocolError(
            "structured output failed schema validation",
            schema_name=model.__name__,
            raw_output=str(text or ""),
            details=exc.errors(),
        ) from exc


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HostSchedulerDecisionPayload(StrictModel):
    current_phase: str = Field(min_length=1)
    next_speaker: str = Field(min_length=1)
    speaker_task: str = ""
    reason: str | None = None
    suggested_add_agent_names: list[str] = Field(default_factory=list)

    @field_validator("current_phase", "next_speaker", "speaker_task", "reason", mode="before")
    @classmethod
    def _string_fields_must_be_strings(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value

    @field_validator("suggested_add_agent_names")
    @classmethod
    def _suggested_names_are_nonempty_strings(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for item in value or []:
            if not isinstance(item, str):
                raise ValueError("suggested_add_agent_names items must be strings")
            name = item.strip()
            if not name:
                raise ValueError("suggested_add_agent_names items must be non-empty")
            if name not in out:
                out.append(name)
        return out


class ExpertSkillSelectionPayload(StrictModel):
    selected_skill: str = Field(min_length=1)


class SkillNextAction(StrictModel):
    agent_turn: Literal["respond", "continue"]
    skill_session: Literal["keep", "release"]


class SkillScriptStdoutPayload(StrictModel):
    execution_status: Literal["succeeded", "blocked", "failed"]
    result_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    next_action: SkillNextAction


class McpToolResultPayload(StrictModel):
    execution_status: Literal["succeeded", "blocked", "failed"]
    result_code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    next_action: SkillNextAction | None = None
