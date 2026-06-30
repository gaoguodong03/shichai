"""专家包（ZIP）：expert_bundle.json + skills/ + 可选 mcp_servers.json。"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.name_based_resources import normalize_tool_row, strip_resource_ids

EXPERT_BUNDLE_VERSION = 1
EXPERT_MANIFEST_NAME = "expert_bundle.json"
MCP_NAME = "mcp_servers.json"
SKILLS_PREFIX = "skills/"


def merge_single_expert_into_instances(
    instances: List[Dict[str, Any]],
    expert_row: Dict[str, Any],
    *,
    name_conflict: str,
) -> Tuple[List[Dict[str, Any]], str | None, bool, List[str]]:
    """
    合并单条专家。name_conflict: skip | overwrite。
    返回 (新列表, 最终 name, 是否因同名未写入, 被覆盖的旧 name 列表)。
    """
    from app.core.scenario_bundle import strip_agent_row_for_disk

    order: List[str] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for d in instances:
        name = str(d.get("name") or "").strip()
        if not name:
            continue
        if name not in by_name:
            order.append(name)
        by_name[name] = strip_agent_row_for_disk(dict(d))

    work = strip_agent_row_for_disk(dict(expert_row))
    incoming_name = str(work.get("name") or "").strip()
    incoming_name_key = incoming_name.lower()
    same_names = [
        name
        for name, row in by_name.items()
        if str(row.get("name") or "").strip().lower() == incoming_name_key and incoming_name_key
    ]
    if same_names and name_conflict == "skip":
        return [by_name[name] for name in order if name in by_name], None, True, []

    overwritten_agent_names: List[str] = []
    if same_names and name_conflict == "overwrite":
        overwritten_agent_names.extend(same_names)
        for name in same_names:
            by_name.pop(name, None)
        order = [name for name in order if name in by_name]

    if not incoming_name:
        return [by_name[name] for name in order if name in by_name], None, True, []

    by_name[incoming_name] = work
    if incoming_name not in order:
        order.append(incoming_name)
    return [by_name[name] for name in order if name in by_name], incoming_name, False, overwritten_agent_names


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
    skill_directories: List[str],
) -> bytes:
    from app.core.scenario_bundle import strip_agent_row_for_disk
    from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle

    buf = io.BytesIO()
    clean = strip_agent_row_for_disk(dict(expert_row))
    manifest = {
        "bundle_version": EXPERT_BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "expert": strip_resource_ids(clean),
    }
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EXPERT_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        safe_mcp_rows = [normalize_tool_row(row) for row in sanitize_mcp_servers_for_bundle(mcp_rows)]
        if safe_mcp_rows:
            zf.writestr(MCP_NAME, json.dumps(safe_mcp_rows, ensure_ascii=False, indent=2) + "\n")
        root = skills_root.resolve()
        for sid in sorted(skill_directories):
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
