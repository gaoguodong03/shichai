"""专家包（ZIP）：expert_bundle.json + skills/ + 可选 mcp_servers.json。"""
from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

EXPERT_BUNDLE_VERSION = 1
EXPERT_MANIFEST_NAME = "expert_bundle.json"
MCP_NAME = "mcp_servers.json"
SKILLS_PREFIX = "skills/"


def merge_single_expert_into_instances(
    instances: List[Dict[str, Any]],
    expert_row: Dict[str, Any],
    *,
    id_conflict: str,
) -> Tuple[List[Dict[str, Any]], str | None, bool, List[str]]:
    """
    合并单条专家。id_conflict: skip | overwrite（按 name 判冲突）。
    返回 (新列表, 最终 agent_id, 是否因同名跳过, 被覆盖的旧 agent_id 列表)。
    """
    from app.core.scenario_bundle import strip_agent_row_for_disk

    order: List[str] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for d in instances:
        aid = str(d.get("agent_id") or "").strip()
        if not aid:
            continue
        if aid not in by_id:
            order.append(aid)
        by_id[aid] = strip_agent_row_for_disk(dict(d))

    work = strip_agent_row_for_disk(dict(expert_row))
    aid0 = str(work.get("agent_id") or "").strip()
    incoming_name_key = str(work.get("name") or "").strip().lower()
    same_name_ids = [
        aid
        for aid, row in by_id.items()
        if str(row.get("name") or "").strip().lower() == incoming_name_key and incoming_name_key
    ]
    if same_name_ids and id_conflict == "skip":
        return [by_id[i] for i in order if i in by_id], None, True, []

    overwritten_agent_ids: List[str] = []
    if same_name_ids and id_conflict == "overwrite":
        overwritten_agent_ids.extend(same_name_ids)
        for aid in same_name_ids:
            by_id.pop(aid, None)
        order = [aid for aid in order if aid in by_id]

    if not aid0:
        aid0 = f"agent-{uuid.uuid4().hex[:8]}"
        work["agent_id"] = aid0

    if aid0 in by_id:
        nid = f"agent-{uuid.uuid4().hex[:8]}"
        while nid in by_id:
            nid = f"agent-{uuid.uuid4().hex[:8]}"
        work["agent_id"] = nid
        by_id[nid] = work
        order.append(nid)
        return [by_id[i] for i in order if i in by_id], nid, False, overwritten_agent_ids

    by_id[aid0] = work
    if aid0 not in order:
        order.append(aid0)
    return [by_id[i] for i in order if i in by_id], aid0, False, overwritten_agent_ids


def read_expert_bundle_manifest(bundle_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    path = bundle_dir / EXPERT_MANIFEST_NAME
    if not path.is_file():
        raise ValueError("missing_expert_bundle_json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    expert = manifest.get("expert")
    if not isinstance(expert, dict):
        raise ValueError("missing_expert_in_manifest")
    return manifest, expert


def build_expert_bundle_zip_bytes(
    expert_row: Dict[str, Any],
    mcp_rows: List[Dict[str, Any]],
    skills_root: Path,
    skill_ids: List[str],
) -> bytes:
    from app.core.scenario_bundle import strip_agent_row_for_disk
    from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle

    buf = io.BytesIO()
    clean = strip_agent_row_for_disk(dict(expert_row))
    manifest = {
        "bundle_version": EXPERT_BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "expert": clean,
    }
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EXPERT_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        safe_mcp_rows = sanitize_mcp_servers_for_bundle(mcp_rows)
        if safe_mcp_rows:
            zf.writestr(MCP_NAME, json.dumps(safe_mcp_rows, ensure_ascii=False, indent=2) + "\n")
        root = skills_root.resolve()
        for sid in sorted(skill_ids):
            sdir = (skills_root / sid).resolve()
            if not sdir.is_dir() or not (sdir / "SKILL.md").is_file():
                continue
            try:
                sdir.relative_to(root)
            except ValueError:
                continue
            for fp in sorted(sdir.rglob("*")):
                if fp.is_dir():
                    continue
                if ".git" in fp.parts:
                    continue
                try:
                    rel = fp.relative_to(sdir)
                except ValueError:
                    continue
                arc = f"{SKILLS_PREFIX}{sid}/{rel.as_posix()}"
                zf.write(fp, arc)
    return buf.getvalue()
