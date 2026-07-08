from __future__ import annotations

from typing import Any, Dict

from app.agent.hook_pipeline import HookPriority, HookResult
from app.agent.orchestrator_state import InterruptReason


class _NeedUserInputHeuristicHook:
    name = "need_user_input_heuristic"
    priority = HookPriority.ORCHESTRATOR_GUARD

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        req = payload.get("required_user_fields")
        if isinstance(req, list) and req:
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.NEED_USER_INPUT,
                message="expert_requires_user_confirmation",
                metadata={"required_user_fields": req},
            )
        text = str(payload.get("full_content") or "")
        if not text.strip():
            return HookResult(allow=True)
        markers = (
            "请提供",
            "请补充",
            "还需要你",
            "需要你提供",
            "请确认",
            "请上传",
            "请给我",
            "请告诉我",
        )
        if any(m in text for m in markers):
            fields = payload.get("required_user_fields")
            if not isinstance(fields, list):
                fields = [{"key": "user_input", "label": "请补充必要信息", "required": True}]
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.NEED_USER_INPUT,
                message="expert_need_user_input",
                metadata={"required_user_fields": fields},
            )
        return HookResult(allow=True)


class _ToolFailureHeuristicHook:
    name = "tool_failure_heuristic"
    priority = HookPriority.POLICY_GUARD

    async def run(self, payload: Dict[str, Any]) -> HookResult:
        results = payload.get("tool_results") or []
        if not isinstance(results, list):
            results = []
        has_failure = any(
            isinstance(item, dict)
            and str(item.get("execution_status") or "").strip().lower() == "failed"
            for item in results
        )
        if has_failure:
            return HookResult(
                allow=False,
                interrupt_reason=InterruptReason.TOOL_UNAVAILABLE,
                message="tool_execution_failed",
                metadata={},
            )
        return HookResult(allow=True)
