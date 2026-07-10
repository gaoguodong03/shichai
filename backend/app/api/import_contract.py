"""Resource import request guards."""
from __future__ import annotations

from fastapi import HTTPException, Request


LEGACY_IMPORT_STRATEGY_FIELDS = frozenset({
    "name_conflict",
    "overwrite_experts",
    "overwrite_skills",
    "mcp_skip_existing",
})


async def reject_legacy_import_strategy_fields(request: Request) -> None:
    """Reject removed caller-selected import strategy fields at the HTTP boundary."""
    form = await request.form()
    legacy_fields = sorted(name for name in form.keys() if name in LEGACY_IMPORT_STRATEGY_FIELDS)
    if legacy_fields:
        raise HTTPException(status_code=400, detail=f"旧导入策略字段已删除：{', '.join(legacy_fields)}")
