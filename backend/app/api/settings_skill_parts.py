"""Skill auxiliary file routes for references/assets/scripts/other."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from fastapi import APIRouter, HTTPException

from app.api.request_models import StrictRequestModel
from app.api.settings_skill_store import _get_skills_dir

ALLOWED_PART_TYPES = ("references", "assets", "scripts", "other")


class PartFileCreate(StrictRequestModel):
    """在 references/assets/scripts 下新建文件"""

    path: str
    content: str = ""


class PartFileUpdate(StrictRequestModel):
    """更新 references/assets/scripts 下某文件内容"""

    content: str


class PartDirCreate(StrictRequestModel):
    """在 references/assets/scripts/other 下新建目录"""

    path: str


def list_skill_part_dir(skill_dir: Path, part_type: str) -> List[Dict[str, str]]:
    """列出 skill 下某子目录中的文件，返回 [{name, path}]，path 为相对该子目录的路径。"""
    if part_type not in ALLOWED_PART_TYPES:
        return []
    if part_type == "other":
        items: List[Dict[str, str]] = []
        exclude = {"references", "assets", "scripts", ".git"}
        for fp in sorted(skill_dir.rglob("*")):
            if fp.is_dir():
                continue
            try:
                rel = fp.relative_to(skill_dir)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] in exclude:
                continue
            if str(rel).replace("\\", "/") == "SKILL.md":
                continue
            items.append({"name": str(rel).replace("\\", "/"), "path": str(rel).replace("\\", "/")})
        return items
    dir_path = skill_dir / part_type
    if not dir_path.is_dir():
        return []
    items = []
    for p in sorted(dir_path.iterdir()):
        if p.is_file():
            items.append({"name": p.name, "path": p.name})
        elif p.is_dir():
            for fp in sorted(p.rglob("*")):
                if fp.is_file():
                    rel = fp.relative_to(dir_path)
                    items.append({"name": str(rel), "path": str(rel).replace("\\", "/")})
    return items


def _skill_dir_or_404(directory_name: str) -> Path:
    skill_dir = _get_skills_dir() / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    return skill_dir


def _resolve_part_path(skill_dir: Path, part_type: str, path: str, *, allow_skill_root: bool) -> Path:
    if part_type not in ALLOWED_PART_TYPES:
        raise HTTPException(status_code=400, detail="Invalid part type")
    cleaned = (path or "").strip().lstrip("/")
    if ".." in cleaned or not cleaned:
        raise HTTPException(status_code=400, detail="Invalid path")
    if part_type == "other":
        full_path = (skill_dir / cleaned).resolve()
        base_dir = skill_dir.resolve()
        if not str(full_path).startswith(str(base_dir)):
            raise HTTPException(status_code=400, detail="Path outside skill dir")
        rel = str(full_path.relative_to(base_dir)).replace("\\", "/")
        if rel == "SKILL.md" or ((not allow_skill_root) and full_path.name == "SKILL.md"):
            raise HTTPException(status_code=400, detail="Cannot edit SKILL.md via other")
        return full_path
    full_path = (skill_dir / part_type / cleaned).resolve()
    part_dir = (skill_dir / part_type).resolve()
    if not str(full_path).startswith(str(part_dir)):
        raise HTTPException(status_code=400, detail="Path outside part dir")
    return full_path


def register_skill_part_routes(router: APIRouter) -> None:
    @router.get("/settings/skills/{directory_name}/parts")
    async def get_skill_parts(directory_name: str):
        """获取某 skill 目录下 references、assets、scripts 的文件列表。"""
        skill_dir = _skill_dir_or_404(directory_name)
        return {
            "status": "ok",
            "data": {
                "references": list_skill_part_dir(skill_dir, "references"),
                "assets": list_skill_part_dir(skill_dir, "assets"),
                "scripts": list_skill_part_dir(skill_dir, "scripts"),
                "other": list_skill_part_dir(skill_dir, "other"),
            },
        }

    @router.get("/settings/skills/{directory_name}/parts/{part_type}/{file_path:path}")
    async def get_skill_part_file(directory_name: str, part_type: str, file_path: str):
        """获取某 skill 下 references/assets/scripts 中指定文件的内容。"""
        if file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid file path")
        skill_dir = _skill_dir_or_404(directory_name)
        full_path = _resolve_part_path(skill_dir, part_type, file_path, allow_skill_root=False)
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Cannot read file: {e}")
        return {"status": "ok", "data": {"path": file_path, "content": content}}

    @router.post("/settings/skills/{directory_name}/parts/{part_type}")
    async def create_skill_part_file(directory_name: str, part_type: str, body: PartFileCreate):
        """在 skill 的 references/assets/scripts 下新建文件。"""
        skill_dir = _skill_dir_or_404(directory_name)
        full_path = _resolve_part_path(skill_dir, part_type, body.path, allow_skill_root=True)
        if part_type == "other" and str(full_path.relative_to(skill_dir.resolve())).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot create SKILL.md in other")
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(body.content or "", encoding="utf-8")
        return {"status": "ok", "data": {"path": (body.path or "").strip().lstrip("/").replace("\\", "/")}}

    @router.post("/settings/skills/{directory_name}/parts/{part_type}/mkdir")
    async def create_skill_part_dir(directory_name: str, part_type: str, body: PartDirCreate):
        """在 skill 的 references/assets/scripts/other 下新建目录。"""
        skill_dir = _skill_dir_or_404(directory_name)
        full_dir = _resolve_part_path(skill_dir, part_type, (body.path or "").rstrip("/"), allow_skill_root=True)
        if part_type == "other" and str(full_dir.relative_to(skill_dir.resolve())).replace("\\", "/") == "SKILL.md":
            raise HTTPException(status_code=400, detail="Cannot create SKILL.md in other")
        full_dir.mkdir(parents=True, exist_ok=True)
        keep = full_dir / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
        return {"status": "ok", "data": {"path": (body.path or "").strip().lstrip("/").rstrip("/").replace("\\", "/"), "created": True}}

    @router.put("/settings/skills/{directory_name}/parts/{part_type}/{file_path:path}")
    async def update_skill_part_file(directory_name: str, part_type: str, file_path: str, body: PartFileUpdate):
        """更新 skill 下 references/assets/scripts 中指定文件的内容。"""
        if file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid file path")
        skill_dir = _skill_dir_or_404(directory_name)
        full_path = _resolve_part_path(skill_dir, part_type, file_path, allow_skill_root=False)
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        full_path.write_text(body.content, encoding="utf-8")
        return {"status": "ok", "data": {"path": file_path}}

    @router.delete("/settings/skills/{directory_name}/parts/{part_type}/{file_path:path}")
    async def delete_skill_part_file(directory_name: str, part_type: str, file_path: str):
        """删除 skill 下 references/assets/scripts 中的指定文件。"""
        if file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid file path")
        skill_dir = _skill_dir_or_404(directory_name)
        full_path = _resolve_part_path(skill_dir, part_type, file_path, allow_skill_root=False)
        if not full_path.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        full_path.unlink()
        return {"status": "ok", "data": {"path": file_path, "deleted": True}}
