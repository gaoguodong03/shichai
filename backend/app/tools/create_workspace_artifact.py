"""Create versioned workspace artifacts without exposing path conflict handling to the model."""
from __future__ import annotations

import logging
import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.agent.platform_prompts import render_platform_prompt
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.agent.tool_spec import ToolSpec
from app.agent.workspace_visibility import WorkspacePathError, internal_system_path_error, normalize_public_workspace_path
from app.api.files import get_workspace_root
from app.core.security import get_current_user

logger = logging.getLogger(__name__)


class CreateWorkspaceArtifactInput(BaseModel):
    """Input for creating a new versioned workspace artifact."""

    title: str = Field(description=render_platform_prompt("tool.schema.create_workspace_artifact.title.v1", {}))
    content: str = Field(description=render_platform_prompt("tool.schema.create_workspace_artifact.content.v1", {}))
    kind: str = Field(default="", description=render_platform_prompt("tool.schema.create_workspace_artifact.kind.v1", {}))
    directory: str = Field(default="", description=render_platform_prompt("tool.schema.create_workspace_artifact.directory.v1", {}))
    extension: str = Field(default="md", description=render_platform_prompt("tool.schema.create_workspace_artifact.extension.v1", {}))


def _workspace_artifact_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S") + "00"


def _safe_filename_part(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]+", "-", text)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    return text[:80].strip("-.")


def _safe_extension(value: str) -> str:
    ext = str(value or "md").strip().lstrip(".").lower()
    ext = re.sub(r"[^a-z0-9]+", "", ext)
    return ext or "md"


def _artifact_base_name(title: str, kind: str) -> str:
    title_part = _safe_filename_part(title)
    kind_part = _safe_filename_part(kind)
    if kind_part and kind_part not in title_part:
        return f"{title_part}-{kind_part}"
    return title_part


def _versioned_artifact_path(workspace_root: Path, directory: str, base_name: str, extension: str, timestamp: str) -> str:
    prefix = f"{base_name}-{timestamp}"
    parent = Path(directory) if directory else Path("")
    for index in range(1, 100):
        suffix = "" if index == 1 else f"-{index:02d}"
        candidate = (parent / f"{prefix}{suffix}.{extension}").as_posix()
        if not (workspace_root / candidate).exists():
            return candidate
    raise RuntimeError("同名产物版本过多，请调整 title 或 directory")


def _checkpoint_workspace_artifact(workspace_id: str) -> None:
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(workspace_id, trigger="workspace_changed", force=True)
    except Exception:
        logger.warning("workspace checkpoint failed after create_workspace_artifact: %s", workspace_id, exc_info=True)


def create_workspace_artifact_tool(workspace_id: str) -> ToolSpec:
    """Create a high-level artifact writer for one workspace."""

    async def _create_workspace_artifact(
        title: str,
        content: str,
        kind: str = "",
        directory: str = "",
        extension: str = "md",
        **_kwargs,
    ) -> str:
        title_value = str(title or "").strip()
        content_value = str(content or "")
        if not title_value:
            return render_platform_prompt("workspace.artifact.create.missing_title.v1", {})
        if not content_value.strip():
            return render_platform_prompt("workspace.artifact.create.missing_content.v1", {})
        base_name = _artifact_base_name(title_value, kind)
        if not base_name:
            return render_platform_prompt("workspace.artifact.create.missing_title.v1", {})
        try:
            directory_value = normalize_public_workspace_path(str(directory or "").strip(), allow_empty=True)
        except WorkspacePathError as exc:
            if exc.code == "internal_system_path":
                return internal_system_path_error(str(directory or ""))
            return f"错误：{exc}"
        extension_value = _safe_extension(extension)
        ws_root = get_workspace_root(workspace_id)
        try:
            rel_path = _versioned_artifact_path(
                ws_root,
                directory_value,
                base_name,
                extension_value,
                _workspace_artifact_timestamp(),
            )
            target = (ws_root / rel_path).resolve()
            target.relative_to(ws_root.resolve())
            user_id = get_current_user().user_id
            await get_shared_sandbox_service().write_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel_path,
                content=content_value,
            )
        except Exception as exc:
            return render_platform_prompt("workspace.artifact.create.failed.v1", {"error": exc})
        _checkpoint_workspace_artifact(workspace_id)
        message = render_platform_prompt("workspace.artifact.create.success.v1", {"path": rel_path})
        return json.dumps(
            {
                "message": message,
                "path": rel_path,
                "artifacts": [
                    {
                        "type": "file",
                        "name": Path(rel_path).name,
                        "path": rel_path,
                    }
                ],
            },
            ensure_ascii=False,
        )

    return ToolSpec.from_function(
        name="create_workspace_artifact",
        description=render_platform_prompt("tool.description.create_workspace_artifact.v1", {}),
        coroutine=_create_workspace_artifact,
        args_schema=CreateWorkspaceArtifactInput,
    )
