"""Expert resource bundle ZIP helpers."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.name_based_resources import normalize_tool_row, strip_resource_ids

EXPERT_MANIFEST_NAME = "bundle.json"


def merge_single_expert_into_instances(
    instances: List[Dict[str, Any]],
    expert_row: Dict[str, Any],
    *,
    name_conflict: str,
) -> Tuple[List[Dict[str, Any]], str | None, bool, List[str]]:
    """Merge one expert by current name identity; same-name rows are overwritten."""
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
    overwritten_agent_names: List[str] = []
    if same_names:
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
        raise ValueError("missing_bundle_json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    if manifest.get("bundle_type") != "agent":
        raise ValueError("invalid_bundle_type")
    agents_root = bundle_dir / "resources" / "agents"
    expert = None
    if agents_root.is_dir():
        for child in sorted(agents_root.iterdir(), key=lambda path: path.name):
            path = child / "agent.json"
            if not path.is_file():
                continue
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                expert = raw
                break
    if expert is None:
        raise ValueError("missing_expert_resource")
    return manifest, expert


def build_expert_bundle_zip_bytes(
    expert_row: Dict[str, Any],
    mcp_rows: List[Dict[str, Any]],
    skills_root: Path,
    skill_directories: List[str],
) -> bytes:
    from app.core.scenario_bundle import strip_agent_row_for_disk
    from app.core.scenario_bundle import sanitize_mcp_servers_for_bundle
    from app.core.scenario_bundle import _resource_dir_name

    buf = io.BytesIO()
    clean = strip_agent_row_for_disk(dict(expert_row))
    safe_mcp_rows = [normalize_tool_row(row) for row in sanitize_mcp_servers_for_bundle(mcp_rows)]
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "bundle_type": "agent",
        "root_resources": [{"type": "agent", "name": str(clean.get("name") or "").strip()}],
        "resource_counts": {
            "scenarios": 0,
            "agents": 1,
            "skills": len(skill_directories),
            "tools": len(safe_mcp_rows),
            "models": 0,
        },
    }
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(EXPERT_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        agent_dir = _resource_dir_name(clean.get("name"), "agent")
        zf.writestr(f"resources/agents/{agent_dir}/agent.json", json.dumps(strip_resource_ids(clean), ensure_ascii=False, indent=2) + "\n")
        for row in safe_mcp_rows:
            tool_dir = _resource_dir_name(row.get("name"), "tool")
            zf.writestr(f"resources/tools/{tool_dir}/tool.json", json.dumps(row, ensure_ascii=False, indent=2) + "\n")
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
                arc = f"resources/skills/{sid}/{rel.as_posix()}"
                zf.write(fp, arc)
    return buf.getvalue()
