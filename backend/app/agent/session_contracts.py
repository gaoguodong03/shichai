"""Strict session, request, and SSE contracts for the public runtime API.

API modules import these models instead of defining ad hoc request shapes. The
models intentionally reject legacy session fields so old controls cannot enter
the new runtime through a thin endpoint.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.message_contracts import WorkspaceAttachment


class StrictApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class HostSnapshot(StrictApiModel):
    name: str = ""
    llm_name: str = ""
    system_prompt: str = ""
    skill_directory: str = ""


class SessionCreateRequest(StrictApiModel):
    title: str = "新对话"
    agent_names: list[str] = Field(default_factory=list)
    host: HostSnapshot | None = None

    @model_validator(mode="after")
    def _dedupe_agent_names(self) -> "SessionCreateRequest":
        self.agent_names = _dedupe_names(self.agent_names)
        return self


class SessionUpdateRequest(StrictApiModel):
    title: str | None = None
    agent_names: list[str] | None = None
    add_agent_names: list[str] = Field(default_factory=list)
    remove_agent_names: list[str] = Field(default_factory=list)
    host: HostSnapshot | None = None

    @model_validator(mode="after")
    def _dedupe_name_lists(self) -> "SessionUpdateRequest":
        if self.agent_names is not None:
            self.agent_names = _dedupe_names(self.agent_names)
        self.add_agent_names = _dedupe_names(self.add_agent_names)
        self.remove_agent_names = _dedupe_names(self.remove_agent_names)
        return self


class GroupChatRequest(StrictApiModel):
    message: str = ""
    client_message_id: str = Field(min_length=1)
    attachments: list[WorkspaceAttachment] = Field(default_factory=list)
    target_agent_name: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _require_user_payload(self) -> "GroupChatRequest":
        if not self.message.strip() and not self.attachments and not self.target_agent_name:
            raise ValueError("message, attachments, or target_agent_name is required")
        return self


class SseRouteEvent(StrictApiModel):
    type: Literal["route"] = "route"
    run_id: str = Field(min_length=1)
    agent_name: str = Field(min_length=1)
    skill: str | None = Field(default=None, min_length=1)


class SseStartEvent(StrictApiModel):
    type: Literal["start"] = "start"
    run_id: str = Field(min_length=1)


class SseProgressEvent(StrictApiModel):
    type: Literal["progress"] = "progress"
    run_id: str = Field(min_length=1)
    phase: str = Field(min_length=1)
    agent_name: str | None = Field(default=None, min_length=1)
    skill: str | None = Field(default=None, min_length=1)
    text: str = ""


class SseEndEvent(StrictApiModel):
    type: Literal["end"] = "end"
    run_id: str = Field(min_length=1)
    phase: Literal["awaiting_user", "completed", "recruiting", "stopped", "failed"]
    waiting_for_user: bool = False
    suggested_next_speaker: str | None = Field(default=None, min_length=1)
    suggested_add_agent_names: list[str] = Field(default_factory=list)


class SseErrorEvent(StrictApiModel):
    type: Literal["error"] = "error"
    run_id: str | None = Field(default=None, min_length=1)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


def _dedupe_names(values: list[str]) -> list[str]:
    out: list[str] = []
    for raw in values or []:
        if not isinstance(raw, str):
            raise ValueError("agent names must be strings")
        name = raw.strip()
        if name and name not in out:
            out.append(name)
    return out
