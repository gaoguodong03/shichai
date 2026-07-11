"""Agent 产出文件 API - 文件系统模块用"""
import shutil
import logging
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends
from fastapi.responses import FileResponse, JSONResponse

from app.api.request_models import StrictRequestModel
from app.core.security import CurrentUser, user_context_dependency
from app.session_state.paths import (
    SessionLayoutPaths,
    ensure_session_layout,
    resolve_workspace_path,
)
from app.agent.workspace_visibility import (
    WorkspacePathError,
    is_internal_system_workspace_path,
    normalize_public_workspace_path,
)

router = APIRouter(tags=["files"])
logger = logging.getLogger(__name__)

UPLOAD_CHUNK_SIZE_BYTES = 1024 * 1024
NO_STORE_HEADERS = {"Cache-Control": "no-store"}


def _auto_checkpoint_workspace(workspace_id: str, trigger: str) -> None:
    try:
        from app.session_state.service import capture_session_checkpoint

        capture_session_checkpoint(workspace_id, trigger=trigger, force=True)
    except Exception:
        logger.warning("workspace checkpoint failed: %s trigger=%s", workspace_id, trigger, exc_info=True)


def _get_agent_outputs_root_for_user(user: CurrentUser) -> Path:
    """返回当前用户的 agent 输出根目录（与群聊/设置使用的用户目录一致）。"""
    root = user.ctx.agent_outputs_dir.resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return root


def get_agent_outputs_root() -> Path:
    """当前请求用户的 agent 输出根目录（与 REST 工作区、多用户分目录规则一致）。"""
    from app.core.security import get_current_user

    return _get_agent_outputs_root_for_user(get_current_user())


def _normalize_workspace_id(workspace_id: str) -> str:
    wid = (workspace_id or "").strip().replace("\\", "/")
    if not wid or wid.startswith("/") or "/" in wid or ".." in wid:
        raise HTTPException(status_code=400, detail="Invalid workspace_id")
    return wid


def get_workspace_root_path(workspace_id: str, user: CurrentUser | None = None) -> Path:
    """
    返回指定会话的工作区根目录（不保证已创建），位于
    data/users/{user_id}/sessions/{session_id}/workspace/ 下。
    """
    wid = _normalize_workspace_id(workspace_id)
    if user is None:
        from app.core.security import get_current_user as _get_user

        user = _get_user()
    ensure_session_layout(user.ctx, wid)
    workspace_root = resolve_workspace_path(user.ctx, wid).resolve()
    sessions_dir = user.ctx.sessions_dir.resolve()
    if workspace_root != sessions_dir and sessions_dir not in workspace_root.parents:
        raise HTTPException(status_code=400, detail="Invalid workspace_id")
    return workspace_root


def _get_workspace_root_path_without_create(workspace_id: str, user: CurrentUser) -> Path:
    """Return the canonical session workspace path without creating a new layout."""
    wid = _normalize_workspace_id(workspace_id)
    workspace_root = SessionLayoutPaths.from_user_ctx(user.ctx, wid).workspace.resolve()
    sessions_dir = user.ctx.sessions_dir.resolve()
    if workspace_root != sessions_dir and sessions_dir not in workspace_root.parents:
        raise HTTPException(status_code=400, detail="Invalid workspace_id")
    return workspace_root


def get_workspace_root(workspace_id: str, user: CurrentUser | None = None) -> Path:
    """
    确保指定 workspace 根目录存在并返回路径。
    供新建 Chat / Workspace 文件操作等场景使用。
    """
    ws_root = get_workspace_root_path(workspace_id, user=user)
    ws_root.mkdir(parents=True, exist_ok=True)
    return ws_root


def _resolve_workspace_path(workspace_id: str, relative_path: str, user: CurrentUser) -> Path:
    """
    将 workspace 内的相对路径解析为绝对路径，并确保落在该 workspace 根目录内。
    workspace 根目录位于 sessions/{workspace_id}/workspace。
    """
    ws_root = get_workspace_root(workspace_id, user=user)
    try:
        normalized = normalize_public_workspace_path(relative_path or "", allow_empty=True)
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    full = (ws_root / normalized).resolve()
    try:
        full.relative_to(ws_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    return full


def _normalize_workspace_filename(filename: str) -> str:
    """Return a single file name accepted by the public workspace file API."""
    raw = str(filename or "").strip().replace("\\", "/")
    if not raw:
        raise HTTPException(status_code=400, detail="filename is required")
    if "/" in raw or raw in {".", ".."} or ".." in raw.split("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        normalize_public_workspace_path(raw)
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return raw


# 以下带子路径的路由（如 /files/mkdir）必须注册在 /files 之前，否则 POST /files 可能先匹配导致 404
class DirCreateBody(StrictRequestModel):
    dirname: str


def _count_files_recursively(root: Path) -> int:
    """统计目录下文件数量（递归）。"""
    if not root.exists() or not root.is_dir():
        return 0
    count = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            rel = str(p.relative_to(root)).replace("\\", "/")
        except ValueError:
            continue
        if is_internal_system_workspace_path(rel):
            continue
        count += 1
    return count


def _workspace_session_ids_with_dirs(current_user: CurrentUser, session_definitions: dict[str, dict]) -> list[str]:
    """Merge indexed sessions with real session dirs that still need migration."""
    session_ids = set(session_definitions)
    sessions_dir = current_user.ctx.sessions_dir
    if sessions_dir.exists() and sessions_dir.is_dir():
        for child in sessions_dir.iterdir():
            if child.is_dir() and (child / "workspace").is_dir():
                session_ids.add(child.name)
    return sorted(session_ids)


@router.get("/workspaces/sessions-with-files")
async def list_sessions_with_workspace_files(
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """返回有工作区文件的会话列表；空工作区会被自动清理。"""
    from app.api.group_chat_state import load_session_definitions

    session_definitions = load_session_definitions()
    sessions = []
    for session_id in _workspace_session_ids_with_dirs(current_user, session_definitions):
        session_item = session_definitions.get(session_id) or {}
        ws_root = _get_workspace_root_path_without_create(session_id, user=current_user)
        file_count = _count_files_recursively(ws_root)
        if file_count == 0:
            try:
                if ws_root.exists() and ws_root.is_dir():
                    shutil.rmtree(ws_root)
            except Exception:
                pass
            continue
        sessions.append({
            "id": session_id,
            "title": session_item.get("title") or session_id,
            "updated_at": session_item.get("updated_at", ""),
            "file_count": file_count,
        })
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "ok", "data": {"sessions": sessions}}


@router.post("/sessions/{session_id}/workspace/files/mkdir")
async def create_workspace_dir(
    session_id: str,
    body: DirCreateBody,
    path: str = "",
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """在指定会话 workspace 内新建子目录。"""
    dirname = _normalize_workspace_filename(body.dirname)
    try:
        parent = _resolve_workspace_path(session_id, path or "", current_user)
    except HTTPException:
        raise
    if not parent.exists():
        raise HTTPException(status_code=404, detail="Parent path not found")
    if not parent.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    new_dir = parent / dirname
    try:
        new_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ws_root = get_workspace_root(session_id, user=current_user)
    rel = str(new_dir.relative_to(ws_root)).replace("\\", "/")
    _auto_checkpoint_workspace(session_id, "workspace_changed")
    return {"status": "ok", "data": {"path": rel}}


@router.get("/sessions/{session_id}/workspace/files")
async def list_workspace_files(
    session_id: str,
    path: str = "",
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """
    列出指定 workspace 下的文件/子目录。
    - session_id 与 Chat / Group Session ID 对应；
    - path 为 workspace 内相对路径，空表示该 workspace 根目录；
    - 工作区根目录未新建时（用户尚未使用过该工作区）直接返回空列表，不新建目录。
    """
    ws_root_path = get_workspace_root_path(session_id, user=current_user)
    if (path or "").strip() == "":
        if not ws_root_path.exists() or not ws_root_path.is_dir():
            return {"status": "ok", "data": {"path": "/", "entries": []}}
    try:
        target = _resolve_workspace_path(session_id, path or "", current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    ws_root = get_workspace_root(session_id, user=current_user)
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            stat = p.stat()
            rel = str(p.relative_to(ws_root)).replace("\\", "/")
            if is_internal_system_workspace_path(rel):
                continue
            entries.append({
                "name": p.name,
                "path": rel,
                "is_dir": p.is_dir(),
                "size": stat.st_size if p.is_file() else None,
                "modified": stat.st_mtime,
            })
        except (ValueError, OSError):
            continue
    return {"status": "ok", "data": {"path": path or "/", "entries": entries}}


@router.get("/sessions/{session_id}/workspace/files/download")
async def download_workspace_file(
    session_id: str,
    path: str,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """下载指定 workspace 中的文件（path 为 workspace 内相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(session_id, path, current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot download a directory")
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/octet-stream",
        headers=NO_STORE_HEADERS,
    )


class FileContentBody(StrictRequestModel):
    content: str = ""


@router.get("/sessions/{session_id}/workspace/files/content")
async def get_workspace_file_content(
    session_id: str,
    path: str,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """读取 workspace 中文本文件内容（path 为 workspace 内相对路径），供插入到提示词等场景使用"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(session_id, path, current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot read directory as text")
    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="文件不是 UTF-8 文本，无法作为提示词插入")
    return JSONResponse(
        {"status": "ok", "data": {"path": path, "content": content}},
        headers=NO_STORE_HEADERS,
    )


class FileCreateBody(StrictRequestModel):
    filename: str
    content: str = ""


class FileRenameBody(StrictRequestModel):
    target_path: str


@router.put("/sessions/{session_id}/workspace/files/content")
async def update_workspace_file_content(
    session_id: str,
    path: str,
    body: FileContentBody,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """更新 workspace 中文件内容（仅限文本文件，path 为 workspace 内相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(session_id, path, current_user)
    except HTTPException:
        raise
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot edit a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content or "", encoding="utf-8")
    _auto_checkpoint_workspace(session_id, "workspace_changed")
    return {"status": "ok", "data": {"path": path}}


@router.delete("/sessions/{session_id}/workspace/files/content")
async def delete_workspace_file(
    session_id: str,
    path: str,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """删除 workspace 中的文件或空目录（path 为 workspace 内相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(session_id, path, current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.is_dir():
        if any(target.iterdir()):
            raise HTTPException(status_code=400, detail="目录非空，请先删除内容")
        try:
            target.rmdir()
        except OSError as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        try:
            target.unlink()
        except OSError as e:
            raise HTTPException(status_code=500, detail=str(e))
    _auto_checkpoint_workspace(session_id, "workspace_changed")
    return {"status": "ok", "data": {"path": path, "deleted": True}}


@router.post("/sessions/{session_id}/workspace/files")
async def create_workspace_file(
    session_id: str,
    body: FileCreateBody,
    path: str = "",
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """在指定 workspace 内新建新文件（path 为 workspace 内目录相对路径，body.filename 为文件名）"""
    fn = _normalize_workspace_filename(body.filename)
    try:
        dir_path = _resolve_workspace_path(session_id, path or "", current_user)
    except HTTPException:
        raise
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    target = (dir_path / fn).resolve()
    ws_root = get_workspace_root(session_id, user=current_user)
    try:
        target.relative_to(ws_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    target.write_text(body.content or "", encoding="utf-8")
    rel = str(target.relative_to(ws_root)).replace("\\", "/")
    _auto_checkpoint_workspace(session_id, "workspace_changed")
    return {"status": "ok", "data": {"path": rel}}


@router.post("/sessions/{session_id}/workspace/files/upload")
async def upload_workspace_file(
    session_id: str,
    path: str = "",
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """向指定 workspace 目录上传文件（path 为 workspace 内相对路径，空表示该 workspace 根目录）"""
    fn = _normalize_workspace_filename(file.filename or "")
    try:
        dir_path = _resolve_workspace_path(session_id, path or "", current_user)
    except HTTPException:
        raise
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    target = (dir_path / fn).resolve()
    ws_root = get_workspace_root(session_id, user=current_user)
    try:
        target.relative_to(ws_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE_BYTES)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as e:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    finally:
        await file.close()
    rel = str(target.relative_to(ws_root)).replace("\\", "/")
    _auto_checkpoint_workspace(session_id, "workspace_changed")
    return {"status": "ok", "data": {"path": rel}}


@router.put("/sessions/{session_id}/workspace/files/rename")
async def rename_workspace_file(
    session_id: str,
    path: str,
    body: FileRenameBody,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """重命名/移动 workspace 中文件。"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    target_path = (body.target_path or "").strip().replace("\\", "/")
    if not target_path:
        raise HTTPException(status_code=400, detail="target_path is required")
    try:
        normalized_target_path = normalize_public_workspace_path(target_path)
    except WorkspacePathError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        target = _resolve_workspace_path(session_id, path, current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot rename a directory")
    ws_root = get_workspace_root(session_id, user=current_user)
    new_path = (ws_root / normalized_target_path).resolve()
    try:
        new_path.relative_to(ws_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid target_path")
    new_path.parent.mkdir(parents=True, exist_ok=True)
    target.rename(new_path)
    rel = str(new_path.relative_to(ws_root)).replace("\\", "/")
    _auto_checkpoint_workspace(session_id, "workspace_changed")
    return {"status": "ok", "data": {"path": rel}}
