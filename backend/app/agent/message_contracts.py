"""Canonical history and SSE message contracts.

Messages follow docs/contracts/runtime-interface-contract.md: message facts live
under `speaker`, `message`, `created_at`, optional `client_message_id`, and
optional `skill_result`. Tool execution detail belongs to traces/logs, not here.
"""
from __future__ import annotations

from typing import Literal

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.agent.structured_output_contracts import ArtifactRef, SkillNextAction


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MessageSpeaker(StrictContractModel):
    type: Literal["user", "host", "expert"]
    agent_name: str | None = Field(default=None, min_length=1)
    skill: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_identity_shape(self) -> "MessageSpeaker":
        if self.type == "user":
            if self.agent_name is not None or self.skill is not None:
                raise ValueError("user speaker must not include agent_name or skill")
        elif self.type in {"host", "expert"} and not self.agent_name:
            raise ValueError("host and expert speakers must include agent_name")
        return self


class WorkspaceAttachment(StrictContractModel):
    type: Literal["workspace_file"]
    path: str = Field(min_length=1)
    name: str | None = Field(default=None, min_length=1)


class MessageBody(StrictContractModel):
    content: str = ""
    attachments: list[WorkspaceAttachment] | None = None
    target_agent_name: str | None = Field(default=None, min_length=1)


class SkillResult(StrictContractModel):
    execution_status: Literal["succeeded", "blocked", "failed"]
    content: str = Field(min_length=1)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    next_action: SkillNextAction


class ChatMessageRecord(StrictContractModel):
    message_id: str = Field(min_length=1)
    speaker: MessageSpeaker
    message: MessageBody
    created_at: str = Field(min_length=1)
    client_message_id: str | None = Field(default=None, min_length=1)
    skill_result: SkillResult | None = None

    @field_validator("created_at")
    @classmethod
    def _validate_created_at_format(cls, value: str) -> str:
        text = str(value or "").strip()
        if not re.fullmatch(r"\d{16}", text):
            raise ValueError("created_at must use YYYYMMDDHHmmssSS")
        try:
            datetime.strptime(text[:14], "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise ValueError("created_at must use YYYYMMDDHHmmssSS") from exc
        return text

    @model_validator(mode="after")
    def _validate_message_shape(self) -> "ChatMessageRecord":
        if self.client_message_id is not None and self.speaker.type != "user":
            raise ValueError("client_message_id is only valid for user messages")
        if self.skill_result is not None and self.speaker.type == "user":
            raise ValueError("user messages must not include skill_result")
        if (self.message.attachments or self.message.target_agent_name) and self.speaker.type != "user":
            raise ValueError("attachments and target_agent_name are only valid for user messages")
        return self


class ChatMessageView(ChatMessageRecord):
    pass
