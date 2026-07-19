"""Shared gateway for LLM calls that must return machine-readable JSON."""
from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agent.messages import HumanMessage
from app.agent.structured_output_contracts import StructuredOutputProtocolError, parse_strict_pydantic_object


_T = TypeVar("_T", bound=BaseModel)


def _bind_json_object_mode(client: Any) -> Any:
    """Enable provider JSON mode when the client exposes the project bind API."""
    bind = getattr(client, "bind", None)
    if not callable(bind):
        return client
    return bind(response_format={"type": "json_object"})


def _pydantic_schema_instruction(model: type[BaseModel]) -> HumanMessage:
    """Tell JSON-mode providers the exact object shape validated at receive time."""
    schema = json.dumps(
        model.model_json_schema(),
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return HumanMessage(
        content=(
            "最终响应必须严格匹配以下 Pydantic JSON Schema；"
            "对象字段不得简写为字符串，数组元素必须符合 items 定义；"
            "只输出一个 JSON 对象，不要输出 Markdown、解释或额外文本。\n"
            f"Pydantic JSON Schema: {schema}"
        )
    )


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
    structured_client = _bind_json_object_mode(client)
    schema_instruction = _pydantic_schema_instruction(model)
    response = await structured_client.ainvoke([*messages, schema_instruction])
    raw = response_content_to_text(response)
    try:
        return _parse_and_validate(raw, model, post_validate=post_validate)
    except StructuredOutputProtocolError:
        if retry_messages is None:
            raise
    retry_response = await structured_client.ainvoke([*retry_messages, schema_instruction])
    retry_raw = response_content_to_text(retry_response)
    return _parse_and_validate(retry_raw, model, post_validate=post_validate)
