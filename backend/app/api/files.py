"""Agent 产出文件 API - 文件系统模块用"""
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.security import CurrentUser, user_context_dependency

router = APIRouter(tags=["files"])

# 工作区根目录与 UserContext.agent_outputs_dir 一致：data/users/{username}/agent-outputs
WORKSPACES_SUBDIR = os.getenv("WORKSPACES_SUBDIR", "workspaces")


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


def get_workspace_root_path(workspace_id: str, user: CurrentUser | None = None) -> Path:
    """
    返回指定 workspace 的根目录路径（不保证已创建），位于 AGENT_OUTPUTS_DIR/workspaces/{workspace_id} 下。
    """
    if user is None:
        # 按当前请求上下文用户推导（Agent 工具与 files API 共用）
        from app.core.security import get_current_user as _get_user

        user = _get_user()
    root = _get_agent_outputs_root_for_user(user)
    return (root / WORKSPACES_SUBDIR / workspace_id).resolve()


def get_workspace_root(workspace_id: str, user: CurrentUser | None = None) -> Path:
    """
    确保指定 workspace 根目录存在并返回路径。
    供创建 Chat / Workspace 文件操作等场景使用。
    """
    ws_root = get_workspace_root_path(workspace_id, user=user)
    ws_root.mkdir(parents=True, exist_ok=True)
    return ws_root


def _resolve_workspace_path(workspace_id: str, relative_path: str, user: CurrentUser) -> Path:
    """
    将 workspace 内的相对路径解析为绝对路径，并确保落在该 workspace 根目录内。
    workspace 根目录位于 AGENT_OUTPUTS_DIR/workspaces/{workspace_id}。
    """
    ws_root = get_workspace_root(workspace_id, user=user)
    # 去掉前导斜杠、归一化，禁止 ..
    normalized = (relative_path or "").strip("/").replace("..", "")
    full = (ws_root / normalized).resolve()
    if not str(full).startswith(str(ws_root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return full


# 以下带子路径的路由（如 /files/mkdir）必须注册在 /files 之前，否则 POST /files 可能先匹配导致 404
class DirCreateBody(BaseModel):
    dirname: str


def _count_files_recursively(root: Path) -> int:
    """统计目录下文件数量（递归）。"""
    if not root.exists() or not root.is_dir():
        return 0
    count = 0
    for _, _, files in os.walk(root):
        count += len(files)
    return count


@router.get("/workspaces/sessions-with-files")
async def list_sessions_with_workspace_files(
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """返回有工作区文件的会话列表；空工作区会被自动清理。"""
    # 延迟导入，避免与 group_chat 形成模块加载循环
    from app.api.group_chat import _load_group_meta

    meta = _load_group_meta()
    sessions = []
    for session_id, session_meta in meta.items():
        ws_root = get_workspace_root_path(session_id, user=current_user)
        file_count = _count_files_recursively(ws_root)
        # 约束：没有文件的会话不应有工作区。若目录存在但为空，顺手清理。
        if file_count == 0:
            try:
                if ws_root.exists() and ws_root.is_dir():
                    shutil.rmtree(ws_root)
            except Exception:
                pass
            continue
        sessions.append({
            "id": session_id,
            "title": session_meta.get("title", "新对话"),
            "updated_at": session_meta.get("updated_at", ""),
            "file_count": file_count,
        })
    sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return {"status": "ok", "data": {"sessions": sessions}}


@router.post("/workspaces/{workspace_id}/files/mkdir")
async def create_workspace_dir(
    workspace_id: str,
    body: DirCreateBody,
    path: str = "",
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """在指定 workspace 内创建子目录（path 为父目录相对路径，空表示根目录）。完整路径: POST /api/workspaces/{id}/files/mkdir"""
    dirname = (body.dirname or "").strip().replace("..", "").replace("\\", "").strip("/")
    if not dirname:
        raise HTTPException(status_code=400, detail="dirname is required")
    try:
        parent = _resolve_workspace_path(workspace_id, path or "", current_user)
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
    ws_root = get_workspace_root(workspace_id, user=current_user)
    rel = str(new_dir.relative_to(ws_root)).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}


@router.get("/workspaces/{workspace_id}/files")
async def list_workspace_files(
    workspace_id: str,
    path: str = "",
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """
    列出指定 workspace 下的文件/子目录。
    - workspace_id 通常与 Chat / Group Session ID 对应；
    - path 为 workspace 内相对路径，空表示该 workspace 根目录；
    - 工作区根目录未创建时（用户尚未使用过该工作区）直接返回空列表，不创建目录。
    """
    ws_root_path = get_workspace_root_path(workspace_id, user=current_user)
    if (path or "").strip() == "":
        if not ws_root_path.exists() or not ws_root_path.is_dir():
            return {"status": "ok", "data": {"path": "/", "entries": []}}
    try:
        target = _resolve_workspace_path(workspace_id, path or "", current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    ws_root = get_workspace_root(workspace_id, user=current_user)
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            stat = p.stat()
            rel = str(p.relative_to(ws_root)).replace("\\", "/")
            entries.append({
                "name": p.name,
                "path": rel,
                "is_dir": p.is_dir(),
                "size": stat.st_size if p.is_file() else None,
                "modified": stat.st_mtime,
            })
        except (ValueError, OSError):
            continue
    # 前端展示用 path 字段维持 workspace 内视角
    return {"status": "ok", "data": {"path": path or "/", "entries": entries}}


@router.get("/workspaces/{workspace_id}/files/download")
async def download_workspace_file(
    workspace_id: str,
    path: str,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """下载指定 workspace 中的文件（path 为 workspace 内相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(workspace_id, path, current_user)
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
    )


class FileContentBody(BaseModel):
    content: str = ""


@router.get("/workspaces/{workspace_id}/files/content")
async def get_workspace_file_content(
    workspace_id: str,
    path: str,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """读取 workspace 中文本文件内容（path 为 workspace 内相对路径），供插入到提示词等场景使用"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(workspace_id, path, current_user)
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
    return {"status": "ok", "data": {"path": path, "content": content}}


class FileCreateBody(BaseModel):
    filename: str
    content: str = ""


class FileRenameBody(BaseModel):
    new_name: str


@router.put("/workspaces/{workspace_id}/files/content")
async def update_workspace_file_content(
    workspace_id: str,
    path: str,
    body: FileContentBody,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """更新 workspace 中文件内容（仅限文本文件，path 为 workspace 内相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(workspace_id, path, current_user)
    except HTTPException:
        raise
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot edit a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content or "", encoding="utf-8")
    return {"status": "ok", "data": {"path": path}}


@router.delete("/workspaces/{workspace_id}/files/content")
async def delete_workspace_file(
    workspace_id: str,
    path: str,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """删除 workspace 中的文件或空目录（path 为 workspace 内相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_workspace_path(workspace_id, path, current_user)
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
    return {"status": "ok", "data": {"path": path, "deleted": True}}


@router.post("/workspaces/{workspace_id}/files")
async def create_workspace_file(
    workspace_id: str,
    body: FileCreateBody,
    path: str = "",
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """在指定 workspace 内创建新文件（path 为 workspace 内目录相对路径，body.filename 为文件名）"""
    if not body.filename or not body.filename.strip():
        raise HTTPException(status_code=400, detail="filename is required")
    fn = body.filename.strip().replace("..", "").replace("/", "")
    if not fn:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        dir_path = _resolve_workspace_path(workspace_id, path or "", current_user)
    except HTTPException:
        raise
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    target = (dir_path / fn).resolve()
    ws_root = get_workspace_root(workspace_id, user=current_user)
    if not str(target).startswith(str(ws_root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    target.write_text(body.content or "", encoding="utf-8")
    rel = str(target.relative_to(ws_root)).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}


@router.post("/workspaces/{workspace_id}/files/upload")
async def upload_workspace_file(
    workspace_id: str,
    path: str = "",
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """向指定 workspace 目录上传文件（path 为 workspace 内相对路径，空表示该 workspace 根目录）"""
    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="filename is required")
    fn = file.filename.strip().replace("..", "").replace("/", "").replace("\\", "")
    if not fn:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        dir_path = _resolve_workspace_path(workspace_id, path or "", current_user)
    except HTTPException:
        raise
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    target = (dir_path / fn).resolve()
    ws_root = get_workspace_root(workspace_id, user=current_user)
    if not str(target).startswith(str(ws_root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        content = await file.read()
        target.write_bytes(content)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    rel = str(target.relative_to(ws_root)).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}


@router.put("/workspaces/{workspace_id}/files/rename")
async def rename_workspace_file(
    workspace_id: str,
    path: str,
    body: FileRenameBody,
    current_user: CurrentUser = Depends(user_context_dependency),
):
    """重命名/移动 workspace 中文件（path 为原相对路径，body.new_name 可为新文件名或新相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    new_name = (body.new_name or "").strip().replace("\\", "/")
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    if ".." in new_name:
        raise HTTPException(status_code=400, detail="Invalid new_name")
    try:
        target = _resolve_workspace_path(workspace_id, path, current_user)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot rename a directory")
    ws_root = get_workspace_root(workspace_id, user=current_user)
    # 兼容：若仅传文件名，沿用“同目录重命名”；若包含 /，视为工作区内目标相对路径（可移动）。
    if "/" in new_name:
        candidate = new_name.strip("/")
        new_path = (ws_root / candidate).resolve()
    else:
        new_path = (target.parent / new_name).resolve()
    if not str(new_path).startswith(str(ws_root)):
        raise HTTPException(status_code=400, detail="Invalid new_name")
    new_path.parent.mkdir(parents=True, exist_ok=True)
    target.rename(new_path)
    rel = str(new_path.relative_to(ws_root)).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}
