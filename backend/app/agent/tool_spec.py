"""Project-local tool objects used by the agent runtime.

The agent only needs three things from a tool: a name/description for prompts,
a JSON schema for model tool binding, and a callable for execution. Keeping
that shape local avoids depending on third-party agent framework tool classes.
"""
from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable


def _normalize_tool_input(tool_input: Any = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = dict(extra or {})
    if tool_input is None:
        return extra
    if isinstance(tool_input, dict):
        return {**tool_input, **extra}
    if isinstance(tool_input, str) and tool_input.strip().startswith("{"):
        try:
            parsed = json.loads(tool_input)
            if isinstance(parsed, dict):
                return {**parsed, **extra}
        except json.JSONDecodeError:
            pass
    return {"__arg1": tool_input, **extra}


def _schema_from_model(schema_source: Any) -> dict[str, Any]:
    if schema_source is None:
        return {"type": "object", "properties": {}}
    if isinstance(schema_source, dict):
        schema = dict(schema_source)
    elif hasattr(schema_source, "model_json_schema"):
        schema = dict(schema_source.model_json_schema())
    elif hasattr(schema_source, "schema"):
        schema = dict(schema_source.schema())
    else:
        schema = {"type": "object", "properties": {}}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


@dataclass
class ToolSpec:
    """Small runtime-neutral tool descriptor."""

    name: str
    description: str = ""
    func: Callable[..., Any] | None = None
    coroutine: Callable[..., Any] | None = None
    args_schema: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_function(
        cls,
        *,
        name: str,
        description: str,
        func: Callable[..., Any] | None = None,
        coroutine: Callable[..., Any] | None = None,
        args_schema: Any = None,
    ) -> "ToolSpec":
        return cls(
            name=name,
            description=description,
            func=func,
            coroutine=coroutine,
            args_schema=args_schema,
        )

    async def ainvoke(self, tool_input: Any = None, **kwargs: Any) -> Any:
        call_kwargs = _normalize_tool_input(tool_input, kwargs)
        return await self.acall(**call_kwargs)

    def invoke(self, tool_input: Any = None, **kwargs: Any) -> Any:
        call_kwargs = _normalize_tool_input(tool_input, kwargs)
        result = self._call_raw(**call_kwargs)
        if inspect.isawaitable(result):
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                return asyncio.run(result)
            raise RuntimeError("async tool invoked synchronously inside a running event loop")
        return result

    async def acall(self, **kwargs: Any) -> Any:
        result = self._call_raw(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    def _call_raw(self, **kwargs: Any) -> Any:
        if callable(self.func):
            return self.func(**kwargs)
        if callable(self.coroutine):
            return self.coroutine(**kwargs)
        raise RuntimeError(f"工具 {self.name} 无可执行函数")

    def to_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or "",
                "parameters": _schema_from_model(self.args_schema),
            },
        }


def tool_to_openai_tool(tool: Any) -> Any:
    if isinstance(tool, ToolSpec):
        return tool.to_openai_tool()
    return tool


def tools_to_openai_tools(tools: list[Any]) -> list[Any]:
    return [tool_to_openai_tool(t) for t in tools]
