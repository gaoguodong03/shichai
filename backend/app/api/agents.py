"""Agent 实例 API - 多专家群聊的智能体配置"""
from __future__ import annotations

import io
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.core.security import user_context_dependency
from app.core.settings_references import mark_agent_id_missing_in_session_presets, merge_reference_rows_for_ids
from app.core.user_context import get_current_user_context, get_current_username
from app.core.resource_store import mirror_rows_to_resource_dir

router = APIRouter(tags=["agents"], dependencies=[Depends(user_context_dependency)])

_FILE_CAP_LABELS = {
    "read": "文件读取",
    "edit": "文件编辑",
    "write": "文件写入",
    "rename": "文件重命名",
    "mkdir": "文件夹新建",
    "list_dir": "列出目录中文件（含子目录）",
}

def _get_agent_instances_path() -> Path:
    """根据当前用户返回 Agent 配置文件路径，实现多用户隔离。"""
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is None:
        raise RuntimeError("缺少用户上下文，无法解析 Agent 配置路径。")
    return (user_ctx.config_dir / "dha_instances.json").resolve()


class AgentCreate(BaseModel):
    """新建 Agent 实例请求"""
    name: str
    role: str = ""
    system_prompt: Optional[str] = None
    skill_ids: List[str] = []
    skill_refs: Optional[List[Dict[str, Any]]] = None
    mcp_server_ids: List[str] = []
    is_leader: bool = False
    llm_provider_id: Optional[str] = None  # 该 Agent 使用的 LLM，空则用应用默认
    avatar_url: Optional[str] = None  # 头像（可选，前端可传 data URL 或远程地址）
    file_capabilities: Optional[Dict[str, bool]] = None  # read/edit/write/rename/mkdir/list_dir
    url_capability: Optional[bool] = None  # 是否可使用 call_api 访问外部 http(s) URL
    agent_id: Optional[str] = None


class AgentUpdate(BaseModel):
    """更新 Agent 实例请求"""
    name: Optional[str] = None
    role: Optional[str] = None
    system_prompt: Optional[str] = None
    skill_ids: Optional[List[str]] = None
    skill_refs: Optional[List[Dict[str, Any]]] = None
    mcp_server_ids: Optional[List[str]] = None
    is_leader: Optional[bool] = None
    llm_provider_id: Optional[str] = None
    avatar_url: Optional[str] = None
    file_capabilities: Optional[Dict[str, bool]] = None
    url_capability: Optional[bool] = None
    agent_id: Optional[str] = None


_DEFAULT_FILE_CAPS: Dict[str, bool] = {
    "read": True,
    "edit": True,
    "write": True,
    "rename": True,
    "mkdir": True,
    "list_dir": True,
}


def _empty_file_capabilities() -> Dict[str, bool]:
    return {
        "read": False,
        "edit": False,
        "write": False,
        "rename": False,
        "mkdir": False,
        "list_dir": False,
    }


def merge_file_capabilities(stored: Any) -> Dict[str, bool]:
    """合并磁盘上的 file_capabilities 与默认值（缺省键视为 True，与旧配置兼容）。"""
    out = dict(_DEFAULT_FILE_CAPS)
    if isinstance(stored, dict):
        for k in out:
            if k in stored:
                out[k] = bool(stored[k])
    return out


def _labels_from_file_capabilities(caps: Dict[str, bool]) -> List[str]:
    return [label for key, label in _FILE_CAP_LABELS.items() if caps.get(key)]


def _skill_name_lookup() -> Dict[str, str]:
    try:
        from app.api.settings_skill_store import load_skills_config

        return {
            str(row.get("id") or "").strip(): str(row.get("name") or "").strip()
            for row in load_skills_config()
            if str(row.get("id") or "").strip()
        }
    except Exception:
        return {}


def _skill_refs_for_ids(skill_ids: List[str], existing_refs: Any = None) -> List[Dict[str, str]]:
    return merge_reference_rows_for_ids(skill_ids, existing_refs, _skill_name_lookup())


async def enrich_agent_instance(instance: Dict[str, Any], workspace_id: str = "__capability_probe__") -> Dict[str, Any]:
    """导出函数：为 Agent 实例附加内置能力派生字段（不触发 MCP 连接）。"""
    out = dict(instance or {})
    _ = workspace_id
    file_caps = merge_file_capabilities(instance.get("file_capabilities"))
    out["file_capabilities"] = file_caps
    out["file_capability_labels"] = _labels_from_file_capabilities(file_caps)
    out["url_capability"] = bool(instance.get("url_capability", True))
    return out


async def enrich_agent_instances(instances: List[Dict[str, Any]], workspace_id: str = "__capability_probe__") -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in instances or []:
        out.append(await enrich_agent_instance(row, workspace_id=workspace_id))
    return out


def _ensure_config_dir() -> Path:
    path = _get_agent_instances_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def load_agent_instances() -> List[Dict[str, Any]]:
    """加载 Agent 实例配置"""
    path = _ensure_config_dir()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_agent_instances(instances: List[Dict[str, Any]]) -> None:
    """保存 Agent 实例配置"""
    normalized: List[Dict[str, Any]] = []
    for row in instances or []:
        if not isinstance(row, dict):
            continue
        copied = dict(row)
        copied.pop("expert_id", None)
        copied.pop("file_capability_labels", None)  # 派生字段，不落盘
        normalized.append(copied)
    path = _ensure_config_dir()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, ensure_ascii=False, indent=2)
    user_ctx = get_current_user_context(default_fallback=False)
    if user_ctx is not None:
        mirror_rows_to_resource_dir(
            normalized,
            user_ctx.agents_dir.resolve(),
            "agent_id",
            body_filename="agent.json",
        )


def normalize_expert_row_for_import(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """将导入 JSON 规范为可写入 dha_instances 的条目；name 必填。"""
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    aid = str(raw.get("agent_id") or raw.get("expert_id") or "").strip()
    skill_ids = [str(x).strip() for x in (raw.get("skill_ids") or []) if str(x).strip()]
    return {
        "agent_id": aid,
        "name": name,
        "role": str(raw.get("role") or ""),
        "system_prompt": str(raw.get("system_prompt") or "")
        if raw.get("system_prompt") is not None
        else "",
        "skill_ids": skill_ids,
        "skill_refs": _skill_refs_for_ids(skill_ids, raw.get("skill_refs")),
        "mcp_server_ids": [str(x).strip() for x in (raw.get("mcp_server_ids") or []) if str(x).strip()],
        "is_leader": bool(raw.get("is_leader", False)),
        "llm_provider_id": str(raw.get("llm_provider_id") or "").strip(),
        "avatar_url": str(raw.get("avatar_url") or "").strip(),
        "file_capabilities": merge_file_capabilities(
            raw.get("file_capabilities") if isinstance(raw.get("file_capabilities"), dict) else {}
        ),
        "url_capability": True if raw.get("url_capability") is None else bool(raw.get("url_capability")),
    }


def _agent_skills_dir() -> Path:
    ctx = get_current_user_context(default_fallback=False)
    if ctx is None:
        raise HTTPException(status_code=401, detail="未登录")
    return ctx.skills_dir.resolve()


def _agent_validation_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    from app.api.settings_mcp import load_mcp_config
    from app.core.agent_import_validate import validate_agent_instance_row, agent_validation_to_api_dict
    from app.skills.loader import get_skills_loader_for_user

    un = get_current_username() or ""
    sl = get_skills_loader_for_user(un, _agent_skills_dir())

    def skill_ok(sid: str) -> bool:
        return bool(sl.get_skill_full_content(sid))

    v = validate_agent_instance_row(row, skill_has_content=skill_ok, mcp_servers=load_mcp_config())
    return agent_validation_to_api_dict(v)


def _find_agent_row(agent_id: str) -> Optional[Dict[str, Any]]:
    key = str(agent_id or "").strip()
    if not key:
        return None
    for d in load_agent_instances():
        if str(d.get("agent_id") or "").strip() == key:
            return dict(d)
    return None


@router.get("/dha/instances/{agent_id}/export-bundle")
async def export_agent_instance_bundle(agent_id: str):
    """导出专家包 ZIP：expert_bundle.json、skills/、可选 mcp_servers.json。"""
    from app.api.settings_mcp import load_mcp_config
    from app.core.expert_bundle import build_expert_bundle_zip_bytes
    from app.core.settings_bundle_import import collect_mcp_refs_from_skill_dirs, mcp_rows_for_bundle_refs
    from app.skills.loader import get_builtin_skills_dir

    row = _find_agent_row(agent_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent instance not found")

    skill_ids = sorted({str(x).strip() for x in (row.get("skill_ids") or []) if str(x).strip()})
    mcp_ids = sorted({str(x).strip() for x in (row.get("mcp_server_ids") or []) if str(x).strip()})
    mcp_refs = [{"id": mid, "name": ""} for mid in mcp_ids]
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(_agent_skills_dir(), skill_ids))
    mcp_refs.extend(collect_mcp_refs_from_skill_dirs(get_builtin_skills_dir(), skill_ids))
    mcp_all = load_mcp_config()
    mcp_rows = mcp_rows_for_bundle_refs(mcp_refs, mcp_all)

    zip_bytes = build_expert_bundle_zip_bytes(row, mcp_rows, _agent_skills_dir(), skill_ids)
    safe = str(agent_id).replace("..", "").replace("/", "").replace("\\", "") or "expert"
    filename = f"expert-bundle-{safe}.zip"
    from app.api.settings_skills import _content_disposition_attachment

    return StreamingResponse(
        io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": _content_disposition_attachment(filename)},
    )


@router.post("/dha/instances/import-bundle")
async def import_agent_instance_bundle(
    file: UploadFile = File(...),
    dry_run: bool = Form(True),
    overwrite_skills: bool = Form(True),
    # 兼容旧表单字段；当前导入语义固定为同名保留本地内容并映射到本地 id，不同名生成新 id。
    mcp_skip_existing: bool = Form(False),
    id_conflict: str = Form("overwrite"),
):
    """导入专家包：合并技能、MCP 与专家条目。"""
    from app.api.settings_mcp import load_mcp_config
    from app.core.expert_bundle import read_expert_bundle_manifest
    from app.core.settings_bundle_import import bundle_skill_name_map, find_missing_references_for_expert_bundle
    from app.core.scenario_bundle import (
        extract_scenario_bundle_dir,
        list_skill_ids_in_bundle_skills_dir,
    )
    from app.skills.loader import get_builtin_skills_dir

    fn = (file.filename or "").strip().lower()
    if not fn.endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 ZIP 专家包")
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="上传文件为空")

    conflict = str(id_conflict or "overwrite").strip().lower()
    if conflict not in ("overwrite", "skip"):
        conflict = "overwrite"

    tmp: Optional[Path] = None
    try:
        tmp = extract_scenario_bundle_dir(raw)
        _man, expert_raw = read_expert_bundle_manifest(tmp)
        norm = normalize_expert_row_for_import(expert_raw)
        if norm is None:
            raise HTTPException(status_code=400, detail="专家包内 expert 无效（需 name）")

        user_skills = _agent_skills_dir()
        skill_ids_in_zip = list_skill_ids_in_bundle_skills_dir(tmp)
        skill_names = bundle_skill_name_map(tmp, skill_ids_in_zip)
        from app.core.settings_bundle_import import skill_name_identity_import_plan

        _skill_id_map, _skill_copy_pairs, would_overwrite = skill_name_identity_import_plan(
            tmp,
            user_skills,
            skill_ids_in_zip,
        )

        mcp_path = tmp / "mcp_servers.json"
        mcp_bundle: List[Dict[str, Any]] = []
        if mcp_path.is_file():
            raw_m = json.loads(mcp_path.read_text(encoding="utf-8"))
            if isinstance(raw_m, list):
                mcp_bundle = [x for x in raw_m if isinstance(x, dict)]

        mcps_preview = [
            {"id": str(x.get("id") or ""), "name": str(x.get("name") or "")}
            for x in mcp_bundle
            if str(x.get("id") or "").strip()
        ]

        existing_instances = load_agent_instances()
        same_name_agent_ids = [
            str(x.get("agent_id") or "")
            for x in existing_instances
            if str(x.get("agent_id") or "").strip()
            and str(x.get("name") or "").strip().lower() == str(norm.get("name") or "").strip().lower()
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
                        "agent_id": str(norm.get("agent_id") or "") or "（可空，提交时生成）",
                        "name": norm.get("name"),
                        "skills": skill_ids_in_zip,
                        "skill_names": skill_names,
                        "mcps": mcps_preview,
                        "would_overwrite_skills": would_overwrite,
                        "would_skip_skills": [],
                        "name_conflict_existing_ids": same_name_agent_ids,
                        "name_conflict_mode": conflict,
                        "missing_references": missing_references,
                    },
                    "note": "确认后将写入技能目录并合并专家；依赖校验在提交完成后返回。agent_id 仅可在服务端配置文件中修改。",
                },
            }

        from app.api.settings_skills import _import_expert_from_bundle_bytes

        helper_result = await _import_expert_from_bundle_bytes(raw, dry_run=False)
        summary = dict(helper_result.get("summary") or {})
        final_id = summary.get("imported_agent_id")
        instances = load_agent_instances()
        val_after = None
        if final_id:
            val_after = _agent_validation_payload(next(d for d in instances if d.get("agent_id") == final_id))

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
    agent_id = (body.agent_id or "").strip() or f"agent-{uuid.uuid4().hex[:8]}"
    skill_ids = body.skill_ids or []
    new_instance = {
        "agent_id": agent_id,
        "name": body.name,
        "role": body.role or "",
        "system_prompt": body.system_prompt or "",
        "skill_ids": skill_ids,
        "skill_refs": _skill_refs_for_ids(skill_ids, body.skill_refs),
        "mcp_server_ids": body.mcp_server_ids or [],
        "is_leader": body.is_leader,
        "llm_provider_id": body.llm_provider_id or "",
        "avatar_url": body.avatar_url or "",
        "file_capabilities": merge_file_capabilities(body.file_capabilities if body.file_capabilities is not None else {}),
        "url_capability": True if body.url_capability is None else bool(body.url_capability),
    }
    instances.append(new_instance)
    save_agent_instances(instances)
    return {"status": "ok", "data": await enrich_agent_instance(new_instance)}


async def update_agent_instance(agent_id: str, body: AgentUpdate):
    """更新 Agent 实例"""
    instances = load_agent_instances()
    idx = next((i for i, d in enumerate(instances) if d.get("agent_id") == agent_id), None)
    if idx is None:
        raise HTTPException(status_code=404, detail="Agent instance not found")
    inst = instances[idx]
    if body.name is not None:
        inst["name"] = body.name
    if body.role is not None:
        inst["role"] = body.role
    if body.system_prompt is not None:
        inst["system_prompt"] = body.system_prompt
    if body.skill_ids is not None:
        inst["skill_ids"] = body.skill_ids
    if body.skill_ids is not None or body.skill_refs is not None:
        inst["skill_refs"] = _skill_refs_for_ids(
            [str(x).strip() for x in (inst.get("skill_ids") or []) if str(x).strip()],
            body.skill_refs if body.skill_refs is not None else inst.get("skill_refs"),
        )
    if body.mcp_server_ids is not None:
        inst["mcp_server_ids"] = body.mcp_server_ids
    if body.is_leader is not None:
        inst["is_leader"] = body.is_leader
    if body.llm_provider_id is not None:
        inst["llm_provider_id"] = body.llm_provider_id or ""
    if body.avatar_url is not None:
        inst["avatar_url"] = body.avatar_url or ""
    if body.file_capabilities is not None:
        inst["file_capabilities"] = merge_file_capabilities(body.file_capabilities)
    if body.url_capability is not None:
        inst["url_capability"] = bool(body.url_capability)
    save_agent_instances(instances)
    return {"status": "ok", "data": await enrich_agent_instance(inst)}


async def delete_agent_instance(agent_id: str):
    """删除 Agent 实例"""
    instances = load_agent_instances()
    original = len(instances)
    target = next((d for d in instances if d.get("agent_id") == agent_id), None)
    instances = [d for d in instances if d.get("agent_id") != agent_id]
    if len(instances) == original:
        raise HTTPException(status_code=404, detail="Agent instance not found")
    mark_agent_id_missing_in_session_presets(agent_id, str((target or {}).get("name") or agent_id))
    save_agent_instances(instances)
    return {"status": "ok", "data": {"agent_id": agent_id, "deleted": True}}


@router.get("/agents")
async def get_agents():
    """获取 Agent 列表（主入口）。"""
    return await list_agent_instances_response()


@router.post("/agents")
async def create_agent(body: AgentCreate):
    """新建 Agent（主入口）。"""
    return await create_agent_instance(body)


@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, body: AgentUpdate):
    """更新 Agent（主入口）。"""
    return await update_agent_instance(agent_id, body)


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """删除 Agent（主入口）。"""
    return await delete_agent_instance(agent_id)
