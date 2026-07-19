"""Builtin workspace tool implementations for Skill execution.

This module owns the concrete read/write/edit/rename/mkdir/list workspace
tools. `tools_for_skill.py` only decides whether these tools are included in a
Skill turn.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field

from app.agent.platform_prompts import render_platform_prompt
from app.agent.sandbox_workspace_access import get_shared_sandbox_service
from app.agent.session_workspace_policy import sandbox_session_dir
from app.agent.tool_spec import ToolSpec
from app.agent.workspace_visibility import (
    WorkspacePathError,
    is_internal_diagnostic_workspace_path,
    is_internal_system_workspace_path,
    normalize_public_workspace_path,
)
from app.api.files import get_workspace_root
from app.core.security import get_current_user
from app.tools.read_file import create_read_file_tool
from app.tools.write_workspace_file import create_write_workspace_file_tool

logger = logging.getLogger(__name__)


class EditWorkspaceFileInput(BaseModel):
    path: str = Field(description=render_platform_prompt("tool.schema.edit_workspace_file.path.v1", {}))
    old_text: str = Field(description=render_platform_prompt("tool.schema.edit_workspace_file.old_text.v1", {}))
    new_text: str = Field(description=render_platform_prompt("tool.schema.edit_workspace_file.new_text.v1", {}))


class RenameWorkspaceFileInput(BaseModel):
    path: str = Field(description=render_platform_prompt("tool.schema.rename_workspace_file.path.v1", {}))
    target_path: str = Field(description=render_platform_prompt("tool.schema.rename_workspace_file.target_path.v1", {}))


class MkdirWorkspaceInput(BaseModel):
    path: str = Field(description=render_platform_prompt("tool.schema.mkdir_workspace.path.v1", {}))


class ListWorkspaceDirectoryInput(BaseModel):
    path: str = Field(description=render_platform_prompt("tool.schema.list_workspace_directory.path.v1", {}), default="")


def _checkpoint_workspace_mutation(workspace_id: str) -> None:
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(workspace_id, trigger="workspace_changed", force=True)
    except Exception:
        logger.warning("workspace checkpoint failed after builtin workspace mutation: %s", workspace_id, exc_info=True)


def create_builtin_workspace_tools(workspace_id: str) -> List:
    """Create the default workspace tools for one group-chat workspace."""
    ws_root = get_workspace_root(workspace_id)
    user_id = get_current_user().user_id

    def _rel_safe(path: str) -> str:
        try:
            normalized = normalize_public_workspace_path(path or "", allow_empty=True)
        except WorkspacePathError as exc:
            raise ValueError(str(exc)) from exc
        probe = (ws_root / normalized).resolve()
        try:
            probe.relative_to(ws_root.resolve())
        except ValueError:
            raise ValueError("路径不在当前工作区")
        return normalized

    async def _recover_single_timestamped_source(rel_path: str) -> str | None:
        rel = Path(rel_path)
        name = rel.name
        match = re.match(r"^(?P<prefix>.+-)(?:19|20)\d{12}(?:\d{2})?(?P<suffix>\.[^/.]+)$", name)
        if not match:
            return None
        parent = rel.parent.as_posix()
        rel_prefix = "" if parent == "." else parent
        svc = get_shared_sandbox_service()
        items = await svc.list_workspace_files_flat(
            user_id=user_id,
            session_id=workspace_id,
            workspace_path=ws_root,
            rel_prefix=rel_prefix,
        )
        workspace_root = sandbox_session_dir(workspace_id).rstrip("/")
        pattern = re.compile(
            "^"
            + re.escape(match.group("prefix"))
            + r"(?:19|20)\d{12}(?:\d{2})?"
            + re.escape(match.group("suffix"))
            + "$"
        )
        candidates: list[str] = []
        for item in items or []:
            raw_path = str((item or {}).get("path") or "").replace("\\", "/").rstrip("/")
            if raw_path.startswith(workspace_root + "/"):
                workspace_rel = raw_path[len(workspace_root) + 1 :]
            else:
                workspace_rel = raw_path
            if is_internal_system_workspace_path(workspace_rel):
                continue
            candidate_rel = Path(workspace_rel)
            if candidate_rel.parent.as_posix() == rel_prefix and pattern.match(candidate_rel.name):
                candidates.append(candidate_rel.as_posix())
        unique = sorted(set(candidates))
        return unique[0] if len(unique) == 1 else None

    async def _edit_workspace_file(path: str, old_text: str, new_text: str) -> str:
        rel = _rel_safe(path)
        svc = get_shared_sandbox_service()
        try:
            content = await svc.read_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
            )
        except FileNotFoundError:
            return render_platform_prompt("workspace.edit_file.not_found_or_directory.v1", {})
        except Exception as e:
            return render_platform_prompt("workspace.edit_file.read_failed.v1", {"error": e})
        if old_text not in content:
            return render_platform_prompt("workspace.edit_file.old_text_not_found.v1", {})
        try:
            await svc.write_workspace_text(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
                content=content.replace(old_text, new_text),
            )
        except Exception as e:
            return render_platform_prompt("workspace.edit_file.write_failed.v1", {"error": e})
        _checkpoint_workspace_mutation(workspace_id)
        return render_platform_prompt("workspace.edit_file.success.v1", {"path": path})

    async def _rename_workspace_file(path: str, target_path: str) -> str:
        cleaned = str(target_path or "").strip().replace("\\", "/")
        if not cleaned:
            return render_platform_prompt("workspace.rename_file.missing_target_path.v1", {})
        if ".." in cleaned:
            return render_platform_prompt("workspace.rename_file.invalid_target_path.v1", {})
        src_rel = _rel_safe(path)
        dst_rel = _rel_safe(cleaned)
        svc = get_shared_sandbox_service()
        try:
            await svc.exec_workspace_shell(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                argv=[
                    "mv",
                    f"{sandbox_session_dir(workspace_id)}/{src_rel}".rstrip("/"),
                    f"{sandbox_session_dir(workspace_id)}/{dst_rel}".rstrip("/"),
                ],
                tool_call_id=f"mv:{src_rel}->{dst_rel}",
            )
        except Exception as e:
            recovered_src_rel = None
            try:
                recovered_src_rel = await _recover_single_timestamped_source(src_rel)
            except Exception:
                recovered_src_rel = None
            if not recovered_src_rel or recovered_src_rel == src_rel:
                return render_platform_prompt("workspace.rename_file.rename_failed.v1", {"error": e})
            try:
                await svc.exec_workspace_shell(
                    user_id=user_id,
                    session_id=workspace_id,
                    workspace_path=ws_root,
                    argv=[
                        "mv",
                        f"{sandbox_session_dir(workspace_id)}/{recovered_src_rel}".rstrip("/"),
                        f"{sandbox_session_dir(workspace_id)}/{dst_rel}".rstrip("/"),
                    ],
                    tool_call_id=f"mv:{recovered_src_rel}->{dst_rel}",
                )
            except Exception as fallback_error:
                return render_platform_prompt("workspace.rename_file.rename_failed.v1", {"error": fallback_error})
        _checkpoint_workspace_mutation(workspace_id)
        return render_platform_prompt("workspace.rename_file.success.v1", {"path": dst_rel})

    async def _mkdir_workspace(path: str) -> str:
        cleaned = str(path or "").strip().replace("\\", "/").strip("/")
        if not cleaned:
            return render_platform_prompt("workspace.mkdir.missing_path.v1", {})
        if ".." in cleaned:
            return render_platform_prompt("workspace.mkdir.invalid_path.v1", {})
        rel = _rel_safe(cleaned)
        svc = get_shared_sandbox_service()
        try:
            await svc.mkdir_workspace(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_path=rel,
            )
        except Exception as e:
            return render_platform_prompt("workspace.mkdir.failed.v1", {"error": e})
        _checkpoint_workspace_mutation(workspace_id)
        return render_platform_prompt("workspace.mkdir.success.v1", {"path": rel})

    async def _list_workspace_directory(path: str = "") -> str:
        cleaned = str(path or "").strip().replace("\\", "/").strip("/")
        if cleaned:
            try:
                _rel_safe(cleaned)
            except ValueError as exc:
                return f"错误：{exc}"
        svc = get_shared_sandbox_service()
        try:
            items = await svc.list_workspace_files_flat(
                user_id=user_id,
                session_id=workspace_id,
                workspace_path=ws_root,
                rel_prefix=cleaned,
            )
        except Exception as e:
            return render_platform_prompt("workspace.list_dir.failed.v1", {"error": e})
        prefix = cleaned or "."
        if not items:
            return render_platform_prompt("workspace.list_dir.empty.v1", {"path": prefix})
        root = f"{sandbox_session_dir(workspace_id)}/{cleaned}".rstrip("/")
        workspace_root = sandbox_session_dir(workspace_id).rstrip("/")
        rels: list[str] = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            p = str(it.get("path") or "").replace("\\", "/").rstrip("/")
            if not p:
                continue
            if p == root:
                continue
            workspace_rel = ""
            if p.startswith(workspace_root + "/"):
                workspace_rel = p[len(workspace_root) + 1 :]
            if workspace_rel and is_internal_system_workspace_path(workspace_rel):
                continue
            if workspace_rel and is_internal_diagnostic_workspace_path(workspace_rel):
                continue
            if p.startswith(root + "/"):
                rels.append("./" + p[len(root) + 1 :])
        rels = sorted(set([r for r in rels if r != "./"]))
        if not rels:
            return render_platform_prompt("workspace.list_dir.empty.v1", {"path": prefix})
        return render_platform_prompt("workspace.list_dir.contents.v1", {"path": prefix, "entries": "\n".join(rels)})

    return [
        create_read_file_tool(session_id=workspace_id),
        create_write_workspace_file_tool(workspace_id),
        ToolSpec.from_function(
            name="edit_workspace_file",
            description=render_platform_prompt("tool.description.edit_workspace_file.v1", {}),
            coroutine=_edit_workspace_file,
            args_schema=EditWorkspaceFileInput,
        ),
        ToolSpec.from_function(
            name="rename_workspace_file",
            description=render_platform_prompt("tool.description.rename_workspace_file.v1", {}),
            coroutine=_rename_workspace_file,
            args_schema=RenameWorkspaceFileInput,
        ),
        ToolSpec.from_function(
            name="mkdir_workspace",
            description=render_platform_prompt("tool.description.mkdir_workspace.v1", {}),
            coroutine=_mkdir_workspace,
            args_schema=MkdirWorkspaceInput,
        ),
        ToolSpec.from_function(
            name="list_workspace_directory",
            description=render_platform_prompt("tool.description.list_workspace_directory.v1", {}),
            coroutine=_list_workspace_directory,
            args_schema=ListWorkspaceDirectoryInput,
        ),
    ]
