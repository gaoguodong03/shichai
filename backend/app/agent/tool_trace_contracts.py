"""Tool execution trace contracts kept outside chat message facts.

These records are for runtime traces/logs only. They must not be embedded in
`history.json` messages or SSE message payloads.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictTraceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ToolCallRecord(StrictTraceModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["mcp", "script", "workspace", "api"]
    provider: str | None = Field(default=None, min_length=1)
    provider_tool: str | None = Field(default=None, min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolOutput(StrictTraceModel):
    text: str = ""
    json_data: dict[str, Any] | list[Any] | None = None
    stdout: str = ""
    stderr: str = ""


class ToolErrorLog(StrictTraceModel):
    message: str = Field(min_length=1)
    detail: str = ""
    stdout: str = ""
    stderr: str = ""
    raw_output: str = ""
    retryable: bool = False


class ToolResultRecord(StrictTraceModel):
    tool_call: ToolCallRecord
    execution_status: Literal["succeeded", "blocked", "failed"]
    message: str
    output: ToolOutput = Field(default_factory=ToolOutput)
    error_log: ToolErrorLog | None = None
