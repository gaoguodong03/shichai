"""Strict message and tool result contracts for group chat history."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ExecutionStatus = Literal["succeeded", "failed", "needs_input"]


class StrictContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class MessageSpeaker(StrictContractModel):
    type: Literal["user", "host", "expert", "system"]
    agent_name: str | None = Field(default=None, min_length=1)
    skill: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_identity_shape(self) -> "MessageSpeaker":
        if self.type == "user":
            if self.agent_name is not None or self.skill is not None:
                raise ValueError("user speaker must not include agent_name or skill")
        elif self.type == "host":
            if self.skill is not None:
                raise ValueError("host speaker must not include skill")
        elif self.type == "expert":
            if not self.agent_name:
                raise ValueError("expert speaker must include agent_name")
        return self


class SchedulerState(StrictContractModel):
    current_phase: str = Field(min_length=1)
    next_speaker: str = Field(min_length=1)
    speaker_task: str = ""
    reason: str = ""


class MessageRouting(StrictContractModel):
    scheduler_state: SchedulerState | None = None
    skill_route_debug: dict[str, Any] = Field(default_factory=dict)
    expert_route_debug: dict[str, Any] = Field(default_factory=dict)


class SkillNextAction(StrictContractModel):
    agent_turn: Literal["respond", "continue", "ask_user", "stop"]
    skill_session: Literal["keep", "release"] | None = None


class SkillTurnResult(StrictContractModel):
    execution_status: ExecutionStatus
    result_code: str = Field(min_length=1)
    message: str = ""
    next_action: SkillNextAction | None = None
    artifacts: dict[str, Any] = Field(default_factory=dict)


class ToolCallRecord(StrictContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["mcp", "script", "workspace", "api", "unknown"]
    provider: str | None = Field(default=None, min_length=1)
    provider_tool: str | None = Field(default=None, min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolOutput(StrictContractModel):
    text: str = ""
    markdown: str = ""
    json_data: dict[str, Any] | list[Any] | None = None
    stdout: str = ""
    stderr: str = ""


class ToolArtifact(StrictContractModel):
    kind: Literal["file", "image", "url", "data", "directory"]
    path: str = ""
    url: str = ""
    title: str = ""
    mime_type: str = ""
    size_bytes: int | None = None


class ToolErrorLog(StrictContractModel):
    message: str = Field(min_length=1)
    detail: str = ""
    stdout: str = ""
    stderr: str = ""
    traceback: str = ""
    raw_output: str = ""
    retryable: bool = False


class RequiredUserField(StrictContractModel):
    key: str = Field(min_length=1)
    label: str = ""
    required: bool = True
    reason: str = ""
    input_type: str = ""
    options: list[str] = Field(default_factory=list)


class ToolResultRecord(StrictContractModel):
    tool_call: ToolCallRecord
    execution_status: ExecutionStatus
    result_code: str = Field(min_length=1)
    message: str
    output: ToolOutput = Field(default_factory=ToolOutput)
    artifacts: list[ToolArtifact] = Field(default_factory=list)
    error_log: ToolErrorLog | None = None
    required_user_fields: list[RequiredUserField] = Field(default_factory=list)


class ToolResultView(ToolResultRecord):
    pass


class ToolTraceDebug(StrictContractModel):
    event: str = Field(min_length=1)
    tool_call_id: str = ""
    tool_name: str = ""
    provider: str = ""
    provider_tool: str = ""
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class MessageDebug(StrictContractModel):
    tool_trace: list[ToolTraceDebug] = Field(default_factory=list)


class ChatMessageRecord(StrictContractModel):
    message_id: str = Field(min_length=1)
    speaker: MessageSpeaker
    content: str
    created_at: str = Field(min_length=1)
    client_message_id: str | None = None
    turn_id: str | None = None
    routing: MessageRouting | None = None
    skill_result: SkillTurnResult | None = None
    tool_results: list[ToolResultRecord] = Field(default_factory=list)
    required_user_fields: list[RequiredUserField] = Field(default_factory=list)
    debug: MessageDebug | None = None


class ChatMessageView(StrictContractModel):
    message_id: str = Field(min_length=1)
    speaker: MessageSpeaker
    content: str
    created_at: str = Field(min_length=1)
    client_message_id: str | None = None
    turn_id: str | None = None
    routing: MessageRouting | None = None
    skill_result: SkillTurnResult | None = None
    tool_results: list[ToolResultView] = Field(default_factory=list)
    required_user_fields: list[RequiredUserField] = Field(default_factory=list)
    debug: MessageDebug | None = None
