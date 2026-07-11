"""Strict structured-output contracts defined by docs/contracts.

This module owns LLM/tool control JSON parsing only. It accepts a single JSON
object, validates the current contract shape, and rejects legacy control fields
instead of normalizing them into the new protocol.
"""
from __future__ import annotations

import json
import re
from typing import Any, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.agent.workspace_visibility import WorkspacePathError, normalize_public_workspace_path


class StructuredOutputProtocolError(ValueError):
    """Report a strict structured-output protocol violation with raw evidence."""

    def __init__(self, message: str, *, schema_name: str = "", raw_output: str = "", details: Any = None):
        super().__init__(message)
        self.schema_name = schema_name
        self.raw_output = raw_output
        self.details = details


_T = TypeVar("_T", bound=BaseModel)
_JSON_FENCE_RE = re.compile(r"\A```json\s*\n?(?P<body>.*?)\n?```\s*\Z", re.S | re.I)


def strict_json_object_from_text(text: str, *, schema_name: str = "") -> dict[str, Any]:
    """Parse exactly one JSON object, optionally wrapped in a single json fence."""
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
        raise StructuredOutputProtocolError(f"invalid JSON object: {exc}", schema_name=schema_name, raw_output=raw) from exc
    if not isinstance(payload, dict):
        raise StructuredOutputProtocolError("structured output JSON must be an object", schema_name=schema_name, raw_output=raw)
    return payload


def parse_strict_pydantic_object(text: str, model: type[_T]) -> _T:
    """Validate a strict JSON object with the provided Pydantic model."""
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


def _dedupe_nonempty_strings(values: list[str]) -> list[str]:
    out: list[str] = []
    for item in values or []:
        if not isinstance(item, str):
            raise ValueError("items must be strings")
        value = item.strip()
        if not value:
            raise ValueError("items must be non-empty")
        if value not in out:
            out.append(value)
    return out


class HostSchedulerDecisionPayload(StrictModel):
    current_phase: str = Field(min_length=1)
    next_speaker: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    suggested_add_agent_names: list[str] = Field(default_factory=list)

    @field_validator("current_phase", "next_speaker", "next_action", mode="before")
    @classmethod
    def _string_fields_must_be_strings(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value

    @field_validator("suggested_add_agent_names")
    @classmethod
    def _suggested_names_are_nonempty_strings(cls, value: list[str]) -> list[str]:
        return _dedupe_nonempty_strings(value)

    @model_validator(mode="after")
    def _validate_invite_shape(self) -> "HostSchedulerDecisionPayload":
        if self.next_speaker == "invite":
            raise ValueError("invite is not a legal host next_speaker")
        if self.suggested_add_agent_names and self.next_speaker != "user":
            raise ValueError("suggested_add_agent_names requires next_speaker=user")
        return self


class ExpertSkillSelectionPayload(StrictModel):
    selected_skill: str = Field(min_length=1)


class ArtifactRef(StrictModel):
    type: Literal["file", "directory", "image", "table", "json", "markdown", "other"]
    name: str = Field(min_length=1)
    path: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _validate_public_workspace_path(cls, value: str) -> str:
        try:
            return normalize_public_workspace_path(value)
        except WorkspacePathError as exc:
            raise ValueError(str(exc)) from exc


class SkillNextAction(StrictModel):
    agent_turn: Literal["respond", "continue"]
    skill_session: Literal["keep", "release"]


class SkillScriptStdoutPayload(StrictModel):
    execution_status: Literal["succeeded", "blocked", "failed"]
    content: str = Field(min_length=1)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    next_action: SkillNextAction


class ToolExecutionLogPayload(StrictModel):
    source: Literal["mcp", "script", "workspace", "api"]
    message_id: str = Field(min_length=1)
    agent_name: str | None = Field(default=None, min_length=1)
    skill: str | None = Field(default=None, min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    provider_tool: str | None = Field(default=None, min_length=1)
    output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
