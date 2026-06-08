"""Streaming helpers shared by group-chat runtime entrypoints."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, AsyncIterator

SSE_AGENT_KEEPALIVE_INTERVAL_SEC = 15.0


async def stream_background_events(source: AsyncIterator[str]) -> AsyncIterator[str]:
    """Forward a run event source to one client without binding the run to that client."""
    done = object()
    queue: asyncio.Queue[Any] = asyncio.Queue()
    client_attached = True

    async def _pump() -> None:
        try:
            async for chunk in source:
                if client_attached:
                    queue.put_nowait(chunk)
        finally:
            if client_attached:
                queue.put_nowait(done)

    def _consume_task_result(task: asyncio.Task[Any]) -> None:
        with suppress(asyncio.CancelledError, Exception):
            task.result()

    pump_task = asyncio.create_task(_pump())
    pump_task.add_done_callback(_consume_task_result)
    try:
        while True:
            item = await queue.get()
            if item is done:
                break
            yield item
    finally:
        client_attached = False


async def iter_with_keepalive(
    source: AsyncIterator[Any],
    *,
    interval_sec: float = SSE_AGENT_KEEPALIVE_INTERVAL_SEC,
) -> AsyncIterator[Any]:
    """Yield upstream items, plus lightweight keepalive markers while the upstream is idle."""
    done = object()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for item in source:
                await queue.put(item)
        except Exception as exc:  # noqa: BLE001
            await queue.put(exc)
        finally:
            await queue.put(done)

    task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=max(0.001, float(interval_sec)))
            except asyncio.TimeoutError:
                yield {"type": "keepalive"}
                continue
            if item is done:
                break
            if isinstance(item, Exception):
                raise item
            yield item
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
