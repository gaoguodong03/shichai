"""LLM prompt tracing proxy used at the outbound model-call boundary."""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict


logger = logging.getLogger("app.agent.llm_client")


def prompt_log_mode() -> str:
    mode = (os.getenv("PROMPT_LOG_MODE") or "summary").strip().lower()
    if mode in {"0", "false", "off", "none", "disabled"}:
        return "off"
    if mode in {"full", "body", "raw", "debug"}:
        return "full"
    return "summary"


def should_log_full_prompts() -> bool:
    return prompt_log_mode() == "full"


class TracedLLMClient:
    """Read-only proxy that logs prompt payloads without mutating the wrapped client."""

    def __init__(
        self,
        raw_client: Any,
        *,
        provider_base_url: str,
        model_name: str,
        thinking_mode_enabled: bool = False,
    ):
        self._raw_client = raw_client
        self._provider_base_url = provider_base_url
        self._model_name = model_name
        self._thinking_mode_enabled = thinking_mode_enabled

    def __getattr__(self, item: str) -> Any:
        return getattr(self._raw_client, item)

    def bind(self, *args: Any, **kwargs: Any) -> Any:
        bind_fn = getattr(self._raw_client, "bind")
        return instrument_llm_client(
            bind_fn(*args, **kwargs),
            provider_base_url=self._provider_base_url,
            model_name=self._model_name,
            thinking_mode_enabled=self._thinking_mode_enabled,
        )

    def bind_tools(self, *args: Any, **kwargs: Any) -> Any:
        bind_tools_fn = getattr(self._raw_client, "bind_tools")
        bound = bind_tools_fn(*args, **kwargs)
        if not any(hasattr(bound, attr) for attr in ("ainvoke", "invoke", "astream", "bind_tools")):
            return bound
        return instrument_llm_client(
            bound,
            provider_base_url=self._provider_base_url,
            model_name=self._model_name,
            thinking_mode_enabled=self._thinking_mode_enabled,
        )

    async def ainvoke(self, inp: Any, *args: Any, **kwargs: Any) -> Any:
        self._log_prompt("ainvoke", inp)
        return await self._raw_client.ainvoke(inp, *args, **kwargs)

    def invoke(self, inp: Any, *args: Any, **kwargs: Any) -> Any:
        self._log_prompt("invoke", inp)
        return self._raw_client.invoke(inp, *args, **kwargs)

    async def astream(self, inp: Any, *args: Any, **kwargs: Any):
        self._log_prompt("astream", inp)
        async for chunk in self._raw_client.astream(inp, *args, **kwargs):
            yield chunk

    def stream(self, inp: Any, *args: Any, **kwargs: Any):
        self._log_prompt("stream", inp)
        yield from self._raw_client.stream(inp, *args, **kwargs)

    def _log_prompt(self, method: str, inp: Any) -> None:
        mode = prompt_log_mode()
        if mode == "off":
            return
        if mode == "full":
            logger.info(
                "[Prompt] mode=full method=%s model=%s base_url=%s\n%s",
                method,
                self._model_name,
                self._provider_base_url,
                _serialize_prompt_payload(inp),
            )
            return
        stats = _prompt_payload_stats(inp)
        logger.info(
            "[Prompt] mode=summary method=%s model=%s base_url=%s input_messages=%s prompt_chars=%s tool_call_count=%s",
            method,
            self._model_name,
            self._provider_base_url,
            stats["input_messages"],
            stats["prompt_chars"],
            stats["tool_call_count"],
        )


def _prompt_payload_stats(value: Any) -> Dict[str, int]:
    payload = _prompt_to_jsonable(value)

    def _content_chars(item: Any) -> int:
        if isinstance(item, dict):
            total = 0
            if "content" in item:
                total += len(str(item.get("content") or ""))
            for key, val in item.items():
                if key == "content":
                    continue
                total += _content_chars(val)
            return total
        if isinstance(item, list):
            return sum(_content_chars(x) for x in item)
        if isinstance(item, (str, int, float, bool)) or item is None:
            return len(str(item or ""))
        return len(str(item))

    def _tool_call_count(item: Any) -> int:
        if isinstance(item, dict):
            count = 0
            tool_calls = item.get("tool_calls")
            if isinstance(tool_calls, list):
                count += len(tool_calls)
            return count + sum(_tool_call_count(v) for k, v in item.items() if k != "tool_calls")
        if isinstance(item, list):
            return sum(_tool_call_count(x) for x in item)
        return 0

    return {
        "input_messages": len(payload) if isinstance(payload, list) else (0 if payload is None else 1),
        "prompt_chars": _content_chars(payload),
        "tool_call_count": _tool_call_count(payload),
    }


def _serialize_prompt_payload(value: Any) -> str:
    try:
        return json.dumps(_prompt_to_jsonable(value), ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(value)


def _prompt_to_jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_prompt_to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _prompt_to_jsonable(v) for k, v in value.items()}

    content_marker = object()
    content = getattr(value, "content", content_marker)
    if content is not content_marker:
        row: Dict[str, Any] = {
            "type": str(getattr(value, "type", "") or value.__class__.__name__),
            "content": _prompt_to_jsonable(content),
        }
        for attr in ("name", "id", "tool_call_id"):
            attr_value = getattr(value, attr, None)
            if attr_value:
                row[attr] = _prompt_to_jsonable(attr_value)
        additional_kwargs = getattr(value, "additional_kwargs", None)
        if additional_kwargs:
            row["additional_kwargs"] = _prompt_to_jsonable(additional_kwargs)
        tool_calls = getattr(value, "tool_calls", None)
        if tool_calls:
            row["tool_calls"] = _prompt_to_jsonable(tool_calls)
        return row

    if hasattr(value, "model_dump"):
        try:
            return _prompt_to_jsonable(value.model_dump())
        except Exception:
            pass
    return str(value)


def instrument_llm_client(
    client: Any,
    *,
    provider_base_url: str,
    model_name: str,
    thinking_mode_enabled: bool = False,
) -> Any:
    if isinstance(client, TracedLLMClient):
        return client
    return TracedLLMClient(
        client,
        provider_base_url=provider_base_url,
        model_name=model_name,
        thinking_mode_enabled=thinking_mode_enabled,
    )
