"""Request input helpers for group-chat runtime.

This module validates structured workspace attachments and builds the
expert-visible user prompt text from the request body.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from app.agent.platform_prompts import render_platform_prompt
from app.agent.session_contracts import GroupChatRequest


def workspace_root(group_session_id: str, sessions_root: Path) -> Path:
    """Return the workspace directory for a group session under the sessions root."""
    return sessions_root / group_session_id / "workspace"


def validate_attachments(group_session_id: str, request: GroupChatRequest, *, sessions_root: Path) -> None:
    """Reject attachment paths that are not existing files in the session workspace."""
    root = workspace_root(group_session_id, sessions_root).resolve()
    for attachment in request.attachments or []:
        raw_path = str(attachment.path or "").strip()
        if raw_path.startswith("/") or ".." in Path(raw_path).parts:
            raise HTTPException(status_code=400, detail="Attachment path must stay inside the session workspace")
        path = (root / raw_path).resolve()
        if root not in path.parents and path != root:
            raise HTTPException(status_code=400, detail="Attachment path must stay inside the session workspace")
        if not path.is_file():
            raise HTTPException(status_code=400, detail=f"Attachment does not exist: {raw_path}")


def attachment_prompt_lines(request: GroupChatRequest) -> str:
    """Render request attachments as prompt lines without reading file contents."""
    lines: list[str] = []
    for item in request.attachments or []:
        name = item.name or Path(item.path).name
        lines.append(f"- {name}: {item.path}")
    return "\n".join(lines)


def request_user_text(request: GroupChatRequest) -> str:
    """Build the expert-visible user input from structured request fields."""
    text = str(request.message or "").strip()
    attachment_lines = attachment_prompt_lines(request)
    if attachment_lines:
        text = (text + "\n\n" if text else "") + render_platform_prompt(
            "user.attachments.section.v1",
            {"attachment_lines": attachment_lines},
        )
    return text.strip()
