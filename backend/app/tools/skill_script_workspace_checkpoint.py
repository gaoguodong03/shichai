"""Workspace checkpoint helpers for Skill script execution."""
from __future__ import annotations

import hashlib
import logging

from app.agent.structured_output_contracts import strict_json_object_from_text
from app.api.files import get_workspace_root_path

logger = logging.getLogger(__name__)


def workspace_fingerprint(workspace_id: str) -> str:
    """Return a stable fingerprint for the current visible workspace file tree."""
    root = get_workspace_root_path(workspace_id).resolve()
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    files = sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: str(p.relative_to(root)).replace("\\", "/"),
    )
    for item in files:
        rel = str(item.relative_to(root)).replace("\\", "/")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(item.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def stdout_declares_artifacts(stdout: str) -> bool:
    """Return whether valid script stdout declares user-visible artifacts."""
    try:
        payload = strict_json_object_from_text(str(stdout or ""), schema_name="SkillScriptStdoutPayload")
    except Exception:
        return False
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    return bool(artifacts) if isinstance(artifacts, list) else False


def checkpoint_workspace_script_write(workspace_id: str, *, before_fingerprint: str, stdout: str) -> None:
    """Create a workspace_changed checkpoint only when script execution produced workspace output."""
    try:
        after_fingerprint = workspace_fingerprint(workspace_id)
        if after_fingerprint == before_fingerprint and not stdout_declares_artifacts(stdout):
            return
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skill_script_workspace_change_detection_failed workspace_id=%s err=%s",
            workspace_id,
            exc,
        )
        return
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(workspace_id, trigger="workspace_changed", force=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "skill_script_workspace_checkpoint_failed workspace_id=%s err=%s",
            workspace_id,
            exc,
        )
