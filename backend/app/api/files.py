"""Agent 产出文件 API - 文件系统模块用"""
import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(tags=["files"])

# Agent 产出文件根目录（仅在此目录内列出/下载，防止路径穿越）
AGENT_OUTPUTS_DIR = os.getenv("AGENT_OUTPUTS_DIR", "./data/agent-outputs")


def _resolve_path(relative_path: str) -> Path:
    """将相对路径解析为绝对路径，且必须落在 AGENT_OUTPUTS_DIR 内"""
    root = Path(AGENT_OUTPUTS_DIR).resolve()
    root.mkdir(parents=True, exist_ok=True)
    # 去掉前导斜杠、归一化，禁止 ..
    normalized = relative_path.strip("/").replace("..", "")
    full = (root / normalized).resolve()
    if not str(full).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    return full


@router.get("/files")
async def list_files(path: str = ""):
    """列出 Agent 产出目录下的文件/子目录（path 为相对路径，空表示根目录）"""
    try:
        target = _resolve_path(path or "")
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")
    entries = []
    for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
        try:
            stat = p.stat()
            entries.append({
                "name": p.name,
                "path": str(p.relative_to(Path(AGENT_OUTPUTS_DIR).resolve())).replace("\\", "/"),
                "is_dir": p.is_dir(),
                "size": stat.st_size if p.is_file() else None,
                "modified": stat.st_mtime,
            })
        except (ValueError, OSError):
            continue
    return {"status": "ok", "data": {"path": path or "/", "entries": entries}}


@router.get("/files/download")
async def download_file(path: str):
    """下载指定相对路径的文件（仅限 AGENT_OUTPUTS_DIR 内）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_path(path)
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


class FileCreateBody(BaseModel):
    filename: str
    content: str = ""


class FileRenameBody(BaseModel):
    new_name: str


@router.put("/files/content")
async def update_file_content(path: str, body: FileContentBody):
    """更新文件内容（仅限文本文件，path 为相对路径）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_path(path)
    except HTTPException:
        raise
    if target.exists() and target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot edit a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content or "", encoding="utf-8")
    return {"status": "ok", "data": {"path": path}}


@router.delete("/files/content")
async def delete_file(path: str):
    """删除文件（path 为相对路径，仅限 AGENT_OUTPUTS_DIR 内，且必须是文件）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    try:
        target = _resolve_path(path)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot delete a directory")
    try:
        target.unlink()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Delete failed: {e}")
    return {"status": "ok", "data": {"path": path, "deleted": True}}


@router.post("/files")
async def create_file(body: FileCreateBody, path: str = ""):
    """创建新文件（path 为所在目录相对路径，body.filename 为文件名）"""
    if not body.filename or not body.filename.strip():
        raise HTTPException(status_code=400, detail="filename is required")
    fn = body.filename.strip().replace("..", "").replace("/", "")
    if not fn:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        dir_path = _resolve_path(path or "")
    except HTTPException:
        raise
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    target = (dir_path / fn).resolve()
    root = Path(AGENT_OUTPUTS_DIR).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    target.write_text(body.content or "", encoding="utf-8")
    rel = str(target.relative_to(root)).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}


@router.post("/files/upload")
async def upload_file(path: str = "", file: UploadFile = File(...)):
    """导入/上传文件到指定目录（path 为相对路径，空表示根目录）"""
    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="filename is required")
    fn = file.filename.strip().replace("..", "").replace("/", "").replace("\\", "")
    if not fn:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        dir_path = _resolve_path(path or "")
    except HTTPException:
        raise
    if not dir_path.is_dir():
        raise HTTPException(status_code=400, detail="Path must be a directory")
    target = (dir_path / fn).resolve()
    root = Path(AGENT_OUTPUTS_DIR).resolve()
    if not str(target).startswith(str(root)):
        raise HTTPException(status_code=400, detail="Invalid path")
    try:
        content = await file.read()
        target.write_bytes(content)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")
    rel = str(target.relative_to(root)).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}


@router.put("/files/rename")
async def rename_file(path: str, body: FileRenameBody):
    """重命名文件（path 为原相对路径，body.new_name 为新文件名）"""
    if not path or path.strip() == "":
        raise HTTPException(status_code=400, detail="path is required")
    new_name = (body.new_name or "").strip().replace("..", "").replace("/", "")
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    try:
        target = _resolve_path(path)
    except HTTPException:
        raise
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if target.is_dir():
        raise HTTPException(status_code=400, detail="Cannot rename a directory")
    new_path = target.parent / new_name
    target.rename(new_path)
    rel = str(new_path.relative_to(Path(AGENT_OUTPUTS_DIR).resolve())).replace("\\", "/")
    return {"status": "ok", "data": {"path": rel}}
