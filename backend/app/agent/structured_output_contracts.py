"""Strict structured-output contracts defined by docs/contracts.

This module owns LLM/tool control JSON parsing only. It accepts a single JSON
object, validates the current contract shape, and rejects legacy control fields
instead of normalizing them into the new protocol.
"""
from __future__ import annotations

import json
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


def strict_json_object_from_text(text: str, *, schema_name: str = "") -> dict[str, Any]:
    """Parse exactly one bare JSON object without Markdown or explanatory text."""
    raw = str(text or "")
    stripped = raw.strip()
    if not stripped:
        raise StructuredOutputProtocolError("empty structured output", schema_name=schema_name, raw_output=raw)
    if not (stripped.startswith("{") and stripped.endswith("}")):
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


class WorkspaceAttachmentRef(StrictModel):
    type: Literal["workspace_file"]
    path: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1)

    @field_validator("path")
    @classmethod
    def _validate_public_workspace_path(cls, value: str) -> str:
        try:
            return normalize_public_workspace_path(value)
        except WorkspacePathError as exc:
            raise ValueError(str(exc)) from exc


class ExpertFinalMessageBody(StrictModel):
    content: str = ""
    attachments: list[WorkspaceAttachmentRef] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    target_agent_name: str | None = Field(default=None, min_length=1)


class HostSchedulerDecisionPayload(StrictModel):
    current_phase: str = Field(min_length=1)
    message: ExpertFinalMessageBody
    suggested_add_agent_names: list[str] = Field(default_factory=list)

    @field_validator("current_phase", mode="before")
    @classmethod
    def _phase_must_be_string(cls, value: Any) -> Any:
        if not isinstance(value, str):
            raise ValueError("must be a string")
        return value

    @field_validator("suggested_add_agent_names")
    @classmethod
    def _suggested_names_are_nonempty_strings(cls, value: list[str]) -> list[str]:
        return _dedupe_nonempty_strings(value)

    @model_validator(mode="after")
    def _validate_recruitment_shape(self) -> "HostSchedulerDecisionPayload":
        if self.suggested_add_agent_names and self.message.target_agent_name:
            raise ValueError("suggested_add_agent_names requires message.target_agent_name to be empty")
        if not self.message.content.strip():
            raise ValueError("message.content must be non-empty")
        return self


class ToolExecutionLogToolCall(StrictModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    provider: str | None = Field(default=None, min_length=1)
    provider_tool: str | None = Field(default=None, min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecutionLogRecord(StrictModel):
    log_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    source: Literal["mcp", "script", "workspace", "api", "host", "runtime"]
    agent_name: str | None = Field(default=None, min_length=1)
    skill: str | None = Field(default=None, min_length=1)
    status: Literal["succeeded", "blocked", "failed"]
    tool_call: ToolExecutionLogToolCall
    output: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int | None = None
