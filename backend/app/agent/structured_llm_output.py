"""Shared gateway for LLM calls that must return machine-readable JSON."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.agent.structured_output_contracts import StructuredOutputProtocolError, parse_strict_pydantic_object
from app.agent.tool_spec import ToolSpec, tools_to_openai_tools


_T = TypeVar("_T", bound=BaseModel)


def response_content_to_text(response: Any) -> str:
    """Normalize common LLM response shapes before strict JSON parsing."""
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):
        return "".join(str(item) for item in raw)
    return str(raw or "")


def _parse_and_validate(
    raw: str,
    model: type[_T],
    *,
    post_validate: Callable[[_T], None] | None = None,
) -> _T:
    payload = parse_strict_pydantic_object(raw, model)
    if post_validate:
        post_validate(payload)
    return payload


async def invoke_pydantic_llm_output(
    client: Any,
    messages: Sequence[Any],
    model: type[_T],
    *,
    retry_messages: Sequence[Any] | None = None,
    post_validate: Callable[[_T], None] | None = None,
) -> _T:
    """Invoke an LLM and validate its machine-readable response with Pydantic.

    This is the only runtime path for LLM calls whose output fields drive
    platform routing, state, tools, persistence, or frontend structure.
    """
    response = await client.ainvoke(list(messages))
    raw = response_content_to_text(response)
    try:
        return _parse_and_validate(raw, model, post_validate=post_validate)
    except StructuredOutputProtocolError:
        if retry_messages is None:
            raise
    retry_response = await client.ainvoke(list(retry_messages))
    retry_raw = response_content_to_text(retry_response)
    return _parse_and_validate(retry_raw, model, post_validate=post_validate)


def _parse_pydantic_tool_submission(response: Any, model: type[_T], *, tool_name: str) -> _T:
    tool_calls = getattr(response, "tool_calls", None) or []
    matching = [
        item
        for item in tool_calls
        if isinstance(item, dict) and str(item.get("name") or "").strip() == tool_name
    ]
    if len(matching) != 1:
        raise StructuredOutputProtocolError(
            f"structured output must call {tool_name} exactly once",
            schema_name=model.__name__,
            details={"tool_calls": tool_calls},
        )
    arguments = matching[0].get("args")
    if not isinstance(arguments, dict):
        raise StructuredOutputProtocolError(
            "structured output tool arguments must be an object",
            schema_name=model.__name__,
            details={"arguments": arguments},
        )
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        raise StructuredOutputProtocolError(
            "structured output tool arguments failed schema validation",
            schema_name=model.__name__,
            details=exc.errors(),
        ) from exc


async def invoke_pydantic_tool_output(
    client: Any,
    messages: Sequence[Any],
    model: type[_T],
    *,
    tool_name: str,
    retry_messages: Sequence[Any] | None = None,
) -> _T:
    """Collect strict structured output through one non-executed submission tool."""
    tool = ToolSpec(
        name=tool_name,
        description=f"Submit the final {model.__name__} payload to the platform.",
        args_schema=model,
    )
    bound_client = client.bind_tools(tools_to_openai_tools([tool]), tool_choice="required")
    response = await bound_client.ainvoke(list(messages))
    try:
        return _parse_pydantic_tool_submission(response, model, tool_name=tool_name)
    except StructuredOutputProtocolError:
        if retry_messages is None:
            raise
    retry_response = await bound_client.ainvoke(list(retry_messages))
    return _parse_pydantic_tool_submission(retry_response, model, tool_name=tool_name)
