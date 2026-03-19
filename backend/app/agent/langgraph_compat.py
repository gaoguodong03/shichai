"""
LangGraph 0.0.51 在 Python 3.13 下的兼容修复。

在该组合下，langgraph.checkpoint.base.empty_checkpoint() 返回的
checkpoint["versions_seen"] 为空字典，会在 pregel 执行时触发 KeyError '__start__'。

这里提供一个 checkpointer，保证首次取 checkpoint 时就包含 '__start__' 版本记录，
从而避免 astream/ainvoke 全面崩溃。
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.base import CheckpointTuple, empty_checkpoint
from langgraph.checkpoint.memory import MemorySaver


def _ensure_start_version(checkpoint: dict[str, Any]) -> dict[str, Any]:
    vs = checkpoint.get("versions_seen")
    # langgraph 0.0.51: pregel 会直接做 checkpoint["versions_seen"][name]，
    # 且 copy_checkpoint 会把 versions_seen 转回普通 dict。
    # 因此这里必须预填充至少 '__start__' 以及本项目固定节点名（agent/tool）。
    if not isinstance(vs, dict):
        vs = {}
        checkpoint["versions_seen"] = vs
    vs.setdefault("__start__", {})
    vs.setdefault("agent", {})
    vs.setdefault("tool", {})
    return checkpoint


class CompatInMemorySaver(MemorySaver):
    """InMemorySaver + 初始 checkpoint 兼容补丁。"""

    def get_tuple(self, config):
        t = super().get_tuple(config)
        if t is not None:
            return t
        cp = _ensure_start_version(empty_checkpoint())
        return CheckpointTuple(config=config, checkpoint=cp, metadata={}, parent_config=None, pending_writes=None)

    async def aget_tuple(self, config):
        t = await super().aget_tuple(config)
        if t is not None:
            return t
        cp = _ensure_start_version(empty_checkpoint())
        return CheckpointTuple(config=config, checkpoint=cp, metadata={}, parent_config=None, pending_writes=None)

    # langgraph 0.0.51 的 pregel 在某些路径下会调用 aput/put 时不传 new_versions，
    # 这里给 new_versions 提供默认值，避免 TypeError。
    def put(self, config, checkpoint, metadata, new_versions=None):
        return super().put(config, checkpoint, metadata, new_versions or {})

    async def aput(self, config, checkpoint, metadata, new_versions=None):
        return await super().aput(config, checkpoint, metadata, new_versions or {})

