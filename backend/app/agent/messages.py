from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


@dataclass
class BaseMessage:
    content: Any = ""
    additional_kwargs: dict[str, Any] = field(default_factory=dict)
    response_metadata: dict[str, Any] = field(default_factory=dict)
    name: str | None = None

    type: ClassVar[str] = "base"

    def model_dump(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "type": self.type,
            "content": self.content,
        }
        if self.additional_kwargs:
            data["additional_kwargs"] = self.additional_kwargs
        if self.response_metadata:
            data["response_metadata"] = self.response_metadata
        if self.name:
            data["name"] = self.name
        return data


@dataclass
class HumanMessage(BaseMessage):
    type: ClassVar[str] = "human"


@dataclass
class SystemMessage(BaseMessage):
    type: ClassVar[str] = "system"


@dataclass
class AIMessage(BaseMessage):
    tool_calls: list[Any] = field(default_factory=list)

    type: ClassVar[str] = "ai"

    def __add__(self, other: Any) -> "AIMessage":
        if not isinstance(other, AIMessage):
            return NotImplemented
        return AIMessage(
            content=f"{self.content or ''}{other.content or ''}",
            additional_kwargs={**self.additional_kwargs, **other.additional_kwargs},
            response_metadata={**other.response_metadata, **self.response_metadata},
            name=self.name or other.name,
            tool_calls=[*self.tool_calls, *other.tool_calls],
        )

    def model_dump(self) -> dict[str, Any]:
        data = super().model_dump()
        if self.tool_calls:
            data["tool_calls"] = self.tool_calls
        return data


@dataclass
class ToolMessage(BaseMessage):
    tool_call_id: str = ""

    type: ClassVar[str] = "tool"

    def model_dump(self) -> dict[str, Any]:
        data = super().model_dump()
        data["tool_call_id"] = self.tool_call_id
        return data
