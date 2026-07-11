"""Agent 实例 API - 多专家群聊的智能体配置"""
from __future__ import annotations

import io
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Request
from fastapi.responses import StreamingResponse
from app.api.import_contract import reject_legacy_import_strategy_fields
from app.api.request_models import StrictRequestModel

from app.core.security import user_context_dependency
from app.core.name_based_resources import normalize_agent_row, normalize_skill_refs
from app.core.user_context import get_current_user_context, get_current_username
from app.core.resource_store import mirror_rows_to_resource_dir

router = APIRouter(tags=["agents"], dependencies=[Depends(user_context_dependency)])

class AgentCreate(StrictRequestModel):
    """新建 Agent 实例请求"""
    name: str
    description: str = ""
    system_prompt: Optional[str] = None
    skills: List[Dict[str, Any]] = []
    llm_name: Optional[str] = None


class AgentUpdate(StrictRequestModel):
    """更新 Agent 实例请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    skills: Optional[List[Dict[str, Any]]] = None
    llm_name: Optional[str] = None


async def enrich_agent_instance(instance: Dict[str, Any], workspace_id: str = "__capability_probe__") -> Dict[str, Any]:
    """导出函数：为 Agent 实例附加内置能力派生字段（不触发 MCP 连接）。"""
    _ = workspace_id
    return normalize_agent_row(instance or {})


async def enrich_agent_instances(instances: List[Dict[str, Any]], workspace_id: str = "__capability_probe__") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in instances or []:
        out.append(await enrich_agent_instance(row, workspace_id=workspace_id))
    return out


def load_agent_instances() -> List[Dict[str, Any]]:
    """从 resources/agents 加载 Agent 实例。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        return []
    root = user_ctx.agents_dir.resolve()
    if not root.is_dir():
        return []
    rows: List[Dict[str, Any]] = []
    for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        body = child / "agent.json"
        if not body.is_file():
            continue
        try:
            raw = json.loads(body.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                rows.append(normalize_agent_row(raw))
        except Exception:
            continue
    return rows


def save_agent_instances(instances: List[Dict[str, Any]]) -> None:
    """保存 Agent 实例配置"""
    normalized: List[Dict[str, Any]] = []
    for row in instances or []:
        if not isinstance(row, dict):
            continue
        try:
            normalized.append(normalize_agent_row(row))
        except ValueError:
            continue
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        mirror_rows_to_resource_dir(normalized, user_ctx.agents_dir.resolve(), "name", body_filename="agent.json")


def normalize_expert_row_for_import(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将导入 JSON 规范为可写入 agents.json 的条目；name 必填。"""
    try:
        return normalize_agent_row(raw)
    except ValueError:
        return None


def _agent_skills_dir() -> Path:
    ctx = get_current_user_context(default_fallback=False)
    if ctx is None:
        raise HTTPException(status_code=401, detail="未登录")
    return ctx.skills_dir.resolve()


def _agent_validation_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    from app.api.settings_mcp import load_mcp_config
    from app.core.agent_import_validate import validate_agent_instance_row, agent_validation_to_api_dict
    from app.skills.loader import get_skills_loader_for_user

    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise HTTPException(status_code=401, detail="未登录")
    sl = get_skills_loader_for_user(user_ctx.user_id, user_ctx.skills_dir.resolve())

    def skill_ok(sid: str) -> bool:
        return bool(sl.get_skill_full_content(sid))

    v = validate_agent_instance_row(row, skill_has_content=skill_ok, mcp_servers=load_mcp_config())
    return agent_validation_to_api_dict(v)


def _find_agent_row(agent_name: str) -> Optional[Dict[str, Any]]:
    key = str(agent_name or "").strip()
    if not key:
        return None
    for d in load_agent_instances():
        if str(d.get("name") or "").strip() == key:
            return dict(d)
    return None


@router.get("/agents/{agent_name}/export-bundle")
async def export_agent_instance_bundle(agent_name: str):
    """导出专家资源包 ZIP：bundle.json + resources/ 镜像树。"""
    from app.api.settings_mcp import load_mcp_config
    from app.core.expert_bundle import build_expert_bundle_zip_bytes
    from app.core.settings_bundle_import import collect_mcp_refs_from_skill_dirs, mcp_rows_for_bundle_refs
    from app.skills.loader import get_builtin_skills_dir

    row = _find_agent_row(agent_name)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent instance not found")

    skill_directories = sorted({str(x.get("directory_name") or "").strip() for x in (row.get("skills") or []) if isinstance(x, dict) and str(x.get("directory_name") or "").strip()})
    mcp_refs = collect_mcp_refs_from_skill_dirs(_agent_skills_dir(), skill_directories)
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(get_builtin_skills_dir(), skill_directories))
    mcp_all = load_mcp_config()
    mcp_rows = mcp_rows_for_bundle_refs(mcp_refs, mcp_all)

    zip_bytes = build_expert_bundle_zip_bytes(row, mcp_rows, _agent_skills_dir(), skill_directories)
    safe = str(agent_name).replace("..", "").replace("/", "").replace("\\", "") or "expert"
    filename = f"expert-bundle-{safe}.zip"
    from app.api.settings_skills import _content_disposition_attachment

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.post("/agents/import-bundle")
async def import_agent_instance_bundle(
    request: Request,
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
):
    """导入专家包：合并技能、MCP 与专家条目。"""
    from app.api.settings_mcp import load_mcp_config
    from app.core.expert_bundle import read_expert_bundle_manifest
    from app.core.settings_bundle_import import bundle_skill_display_name_map, find_missing_references_for_expert_bundle
    from app.core.scenario_bundle import (
        extract_scenario_bundle_dir,
        list_skill_directories_in_bundle_skills_dir,
        read_bundle_tool_rows,
    )
    from app.skills.loader import get_builtin_skills_dir

    fn = (file.filename or "").strip().lower()
    if not fn.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 专家包")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")
    await reject_legacy_import_strategy_fields(request)

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _man, expert_raw = read_expert_bundle_manifest(tmp)
        norm = normalize_expert_row_for_import(expert_raw)
        if norm is None:
            raise HTTPException(status_code=400, detail="专家包内 expert 无效（需 name）")

        user_skills = _agent_skills_dir()
        skill_directories_in_zip = list_skill_directories_in_bundle_skills_dir(tmp)
        skill_display_names = bundle_skill_display_name_map(tmp, skill_directories_in_zip)
        from app.core.settings_bundle_import import skill_directory_identity_import_plan

        _skill_directory_map, _skill_copy_pairs, would_overwrite = skill_directory_identity_import_plan(
            tmp,
            user_skills,
            skill_directories_in_zip,
        )

        mcp_bundle = read_bundle_tool_rows(tmp)

        mcps_preview = [
            {"name": str(x.get("name") or "")}
            for x in mcp_bundle
            if str(x.get("name") or "").strip()
        ]

        existing_instances = load_agent_instances()
        same_name_agent_names = [
            str(x.get("name") or "")
            for x in existing_instances
            if str(x.get("name") or "").strip().lower() == str(norm.get("name") or "").strip().lower()
        ]
        existing_mcp = load_mcp_config()
        missing_references = find_missing_references_for_expert_bundle(
            norm,
            mcp_bundle,
            tmp,
            user_skills,
            existing_mcp,
            extra_skill_roots=(get_builtin_skills_dir(),),
        )

        if dry_run:
            return {
                "status": "ok",
                "data": {
                    "dry_run": True,
                    "bundle_preview": {
                        "name": norm.get("name"),
                        "skills": skill_directories_in_zip,
                        "skill_display_names": skill_display_names,
                        "mcps": mcps_preview,
                        "would_overwrite_skills": would_overwrite,
                        "name_conflict_existing_names": same_name_agent_names,
                        "missing_references": missing_references,
                    },
                    "note": "确认后将写入技能目录并合并专家；同名专家按当前契约覆盖。",
                },
            }

        from app.core.skill_bundle_service import import_expert_from_bundle_bytes

        helper_result = await import_expert_from_bundle_bytes(raw, dry_run=False)
        summary = dict(helper_result.get("summary") or {})
        final_name = summary.get("imported_agent_name")
        instances = load_agent_instances()
        val_after = None
        if final_name:
            val_after = _agent_validation_payload(next(d for d in instances if d.get("name") == final_name))

        return {
            "status": "ok",
            "data": {
                "dry_run": False,
                "summary": summary,
                "validation_after": val_after,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e) or "无效的专家包") from e
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"专家包导入失败：{e}") from e
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


async def list_agent_instances_response():
    """获取 Agent 实例列表（按名称排序）"""
    instances = load_agent_instances()
    instances = sorted(instances, key=lambda d: (d.get("name") or "").strip())
    return {"status": "ok", "data": {"instances": await enrich_agent_instances(instances)}}


async def create_agent_instance(body: AgentCreate):
    """新建 Agent 实例"""
    instances = load_agent_instances()
    if any(str(d.get("name") or "").strip().casefold() == body.name.strip().casefold() for d in instances):
        raise HTTPException(status_code=409, detail="同名专家已存在")
    new_instance = normalize_agent_row({
        "name": body.name,
        "description": body.description or "",
        "system_prompt": body.system_prompt or "",
        "skills": body.skills,
        "llm_name": body.llm_name or "",
    })
    instances.append(new_instance)
    save_agent_instances(instances)
    return {"status": "ok", "data": await enrich_agent_instance(new_instance)}


async def update_agent_instance(agent_name: str, body: AgentUpdate):
    """更新 Agent 实例"""
    instances = load_agent_instances()
    idx = next((i for i, d in enumerate(instances) if str(d.get("name") or "").strip() == agent_name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Agent instance not found")
    inst = instances[idx]
    if body.name is not None:
        new_name = body.name.strip()
        if new_name.casefold() != agent_name.casefold() and any(
            str(d.get("name") or "").strip().casefold() == new_name.casefold()
            for i, d in enumerate(instances)
            if i != idx
        ):
            raise HTTPException(status_code=409, detail="同名专家已存在")
        inst["name"] = body.name
    if body.description is not None:
        inst["description"] = body.description
    if body.system_prompt is not None:
        inst["system_prompt"] = body.system_prompt
    if body.skills is not None:
        inst["skills"] = normalize_skill_refs(body.skills)
    if body.llm_name is not None:
        inst["llm_name"] = body.llm_name or ""
    inst = normalize_agent_row(inst)
    instances[idx] = inst
    save_agent_instances(instances)
    return {"status": "ok", "data": await enrich_agent_instance(inst)}


async def delete_agent_instance(agent_name: str):
    """删除 Agent 实例"""
    instances = load_agent_instances()
    original = len(instances)
    instances = [d for d in instances if str(d.get("name") or "").strip() != agent_name]
    if len(instances) == original:
        raise HTTPException(status_code=404, detail="Agent instance not found")
    save_agent_instances(instances)
    return {"status": "ok", "data": {"name": agent_name, "deleted": True}}


@router.get("/agents")
async def get_agents():
    """获取 Agent 列表（主入口）。"""
    return await list_agent_instances_response()


@router.post("/agents")
async def create_agent(body: AgentCreate):
    """新建 Agent（主入口）。"""
    return await create_agent_instance(body)


@router.put("/agents/{agent_name}")
async def update_agent(agent_name: str, body: AgentUpdate):
    """更新 Agent（主入口）。"""
    return await update_agent_instance(agent_name, body)


@router.delete("/agents/{agent_name}")
async def delete_agent(agent_name: str):
    """删除 Agent（主入口）。"""
    return await delete_agent_instance(agent_name)
