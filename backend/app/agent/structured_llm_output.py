"""Shared gateway for LLM calls that must return machine-readable JSON."""
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agent.structured_output_contracts import StructuredOutputProtocolError, parse_strict_pydantic_object


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
