"""Skill settings API implementation."""
from __future__ import annotations

import hashlib
import io
import re
import shutil
import yaml
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from typing import Any

from app.api.import_contract import reject_legacy_import_strategy_fields
from app.core.skill_bundle_service import (
    build_skill_zip_bytes as _build_skill_zip_bytes,
    import_skill_from_bundle_bytes as _import_skill_from_bundle_bytes,
    mcp_rows_for_skill_dir as _mcp_rows_for_skill_dir,
)
from app.core.user_context import get_current_user_context
from app.skills.loader import invalidate_skills_cache_for_user
from app.core.security import user_context_dependency
from app.api.settings_skill_frontmatter import (
    ALLOWED_TOOLS_FM_KEY,
    SkillCreate,
    SkillUpdate,
    normalize_allowed_tools_payload as _normalize_allowed_tools_payload,
    normalized_allowed_tools_dict as _normalized_allowed_tools_dict,
    python_doc_from_allowed_tools as _python_doc_from_allowed_tools,
    runtime_tools_only as _runtime_tools_only,
    sanitize_skill_frontmatter_for_write as _sanitize_skill_frontmatter_for_write,
)
from app.api.settings_skill_store import (
    _get_skills_dir,
    get_mcp_servers_for_skill,
    load_skills_config,
    read_skill_file as _read_skill_file,
    skill_dir_for_directory_name as _skill_dir_for_directory_name,
    skill_display_name_from_dir as _skill_display_name_from_dir,
    write_skill_file as _write_skill_file,
)
from app.api.settings_skill_parts import (
    PartDirCreate,
    PartFileCreate,
    PartFileUpdate,
    register_skill_part_routes,
)

router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])


# ========== MCP 配置 API ==========


# ========== Skills 配置 API ==========


def _refresh_skills_loader():
    """使当前用户的技能缓存失效，下次请求重新从磁盘加载。"""
    from app.skills.loader import invalidate_skills_cache_for_user

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        invalidate_skills_cache_for_user(user_ctx.user_id)


@router.get("/settings/skills")
async def get_skills():
    """获取 Skills 列表"""
    skills = load_skills_config()
    
    return {
        "status": "ok",
        "data": {
            "skills": skills
        }
    }

def _slugify(name: str) -> str:
    """Generate a stable ASCII Skill directory seed, hashing non-Latin names."""
    raw = (name or "").strip()
    s = re.sub(r"[^A-Za-z0-9_\s-]", "", raw, flags=re.ASCII)
    s = re.sub(r"[-\s]+", "-", s).strip("-").lower()
    if s:
        return s
    h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"skill-{h}"



def _next_available_directory_name(base: Path, seed: str) -> str:
    """基于 seed 生成不冲突的 skill 目录名。"""
    directory_name = seed
    idx = 0
    while (base / directory_name).exists():
        idx += 1
        directory_name = f"{seed}-{idx}"
    return directory_name


@router.post("/settings/skills")
async def create_skill(skill: SkillCreate):
    """新建 Skill：在 skills 目录下新建 <directory_name>/SKILL.md"""
    base = _get_skills_dir()
    base.mkdir(parents=True, exist_ok=True)
    if not (skill.name or "").strip():
        raise HTTPException(status_code=400, detail="name is required")
    seed = _slugify((skill.name or "skill").strip())
    directory_name = _next_available_directory_name(base, seed)
    skill_dir = base / directory_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body = "\n## 说明\n\n（待补充）\n"
    frontmatter = {
        "name": (skill.name or "").strip(),
        "description": skill.description or "",
        ALLOWED_TOOLS_FM_KEY: {"mcp": [], "http_api": [], "python": []},
    }
    content = "---\n" + yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False) + "---\n" + body
    (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    _refresh_skills_loader()
    ret_name = (skill.name or directory_name).strip()
    ret_desc = skill.description or ""
    new_skill = {
        "directory_name": directory_name,
        "name": ret_name,
        "description": ret_desc,
        "path": str(skill_dir),
        "allowed_tools": {"mcp": [], "http_api": [], "python": []},
    }
    return {"status": "ok", "data": new_skill}


@router.post("/settings/skills/import-zip")
async def import_skill_zip(
    request: Request,
    file: UploadFile = File(...),
):
    """通过当前资源包 ZIP 导入 Skill。"""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="仅支持 ZIP 文件")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    await reject_legacy_import_strategy_fields(request)

    result = await _import_skill_from_bundle_bytes(raw, dry_run=False)
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    directory_name = str(result.get("imported_directory_name") or "")
    data = {
        **result,
        "directory_name": directory_name,
        "overwritten_by_directory": bool(summary.get("overwritten_directory_names")),
    }
    return {"status": "ok", "data": data}

def _content_disposition_attachment(filename: str) -> str:
    """下载文件名：HTTP 头须为 latin-1；含中文等非 ASCII 时用 RFC 5987 的 filename*。"""
    try:
        filename.encode("latin-1")
        safe = filename.replace("\\", "\\\\").replace('"', '\\"')
        return f'attachment; filename="{safe}"'
    except UnicodeEncodeError:
        return (
            'attachment; filename="skill-export.zip"; '
            f"filename*=UTF-8''{quote(filename, safe='')}"
        )


@router.get("/settings/skills/{directory_name}/export-zip")
async def export_skill_zip(directory_name: str):
    """导出当前技能目录为 ZIP，可用于备份或再次 import-zip 导入。"""
    base = _get_skills_dir().resolve()
    skill_dir = (base / directory_name).resolve()
    if not skill_dir.is_dir() or skill_dir.parent != base:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not (skill_dir / "SKILL.md").is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    raw = _build_skill_zip_bytes(skill_dir, _mcp_rows_for_skill_dir(skill_dir))
    filename = f"{directory_name}.zip"
    return StreamingResponse(
        io.BytesIO(raw),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.put("/settings/skills/{directory_name}")
async def update_skill(directory_name: str, skill_update: SkillUpdate):
    """更新 Skill：修改 SKILL.md 的 frontmatter 与/或正文 body"""
    base = _get_skills_dir()
    skill_dir = base / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    fm, body = _read_skill_file(skill_dir)
    if skill_update.name is not None:
        fm["name"] = skill_update.name
    if skill_update.description is not None:
        fm["description"] = skill_update.description
    if skill_update.allowed_tools is not None:
        if not isinstance(skill_update.allowed_tools, dict):
            raise HTTPException(status_code=400, detail="allowed_tools must be an object")
        normalized_tools = _normalize_allowed_tools_payload(skill_update.allowed_tools)
        fm[ALLOWED_TOOLS_FM_KEY] = _runtime_tools_only(normalized_tools)
    if skill_update.body is not None:
        body = skill_update.body
    _sanitize_skill_frontmatter_for_write(fm)
    _write_skill_file(skill_dir, fm, body)
    new_directory_name = directory_name
    _refresh_skills_loader()
    return {
        "status": "ok",
        "data": {
            "directory_name": new_directory_name,
            "updated": True,
            "renamed": new_directory_name != directory_name,
            "old_directory_name": directory_name,
        },
    }

@router.delete("/settings/skills/{directory_name}")
async def delete_skill(directory_name: str):
    """删除 Skill：删除对应目录"""
    base = _get_skills_dir()
    skill_dir = base / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    shutil.rmtree(skill_dir)
    _refresh_skills_loader()
    return {"status": "ok", "data": {"directory_name": directory_name, "deleted": True}}

@router.get("/settings/skills/{directory_name}/content")
async def get_skill_content(directory_name: str):
    """获取技能 SKILL.md 的完整内容（raw 全文）及 frontmatter 解析结果，用于详情页展示。"""
    base = _get_skills_dir()
    skill_dir = base / directory_name
    if not skill_dir.is_dir():
        raise HTTPException(status_code=404, detail="Skill not found")
    path = skill_dir / "SKILL.md"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Skill not found")
    raw = path.read_text(encoding="utf-8")
    fm, body = _read_skill_file(skill_dir)
    allowed = _normalized_allowed_tools_dict(fm)
    return {
        "status": "ok",
        "data": {
            "raw": raw,
            "name": fm.get("name", directory_name),
            "description": fm.get("description", ""),
            "body": body,
            "allowed_tools": allowed,
        },
    }



register_skill_part_routes(router)
