"""场景包（ZIP）：内含场景预设、专家快照、技能目录、可选 MCP 列表，用于一键分享与导入。"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from app.core.host_config import normalize_host_config_dict

BUNDLE_VERSION = 1
MANIFEST_NAME = "scenario_bundle.json"
DHA_NAME = "dha_instances.json"
MCP_NAME = "mcp_servers.json"
SKILLS_PREFIX = "skills/"


def _zip_parts_safe(parts: List[str]) -> bool:
    if not parts:
        return False
    return not any(not p or p == "." or p == ".." or ".." in p for p in parts)


def collect_skill_and_mcp_ids_for_preset(
    preset: Dict[str, Any], dha_by_id: Dict[str, Any]
) -> Tuple[Set[str], Set[str]]:
    skill_ids: Set[str] = set()
    mcp_ids: Set[str] = set()
    hc_raw = preset.get("host_config")
    if isinstance(hc_raw, dict):
        hc = normalize_host_config_dict(hc_raw)
        skill_ids.update(str(x).strip() for x in (hc.get("skill_ids") or []) if str(x).strip())
        mcp_ids.update(str(x).strip() for x in (hc.get("mcp_server_ids") or []) if str(x).strip())
    for aid in preset.get("agent_ids") or []:
        aid = str(aid).strip()
        d = dha_by_id.get(aid)
        if not isinstance(d, dict):
            continue
        for x in d.get("skill_ids") or []:
            s = str(x).strip()
            if s:
                skill_ids.add(s)
        for x in d.get("mcp_server_ids") or []:
            s = str(x).strip()
            if s:
                mcp_ids.add(s)
    return skill_ids, mcp_ids


def build_scenario_bundle_zip_bytes(
    preset_row: Dict[str, Any],
    expert_rows: List[Dict[str, Any]],
    mcp_rows: List[Dict[str, Any]],
    skills_root: Path,
    skill_ids: List[str],
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "preset": preset_row,
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(DHA_NAME, json.dumps(expert_rows, ensure_ascii=False, indent=2) + "\n")
        if mcp_rows:
            zf.writestr(MCP_NAME, json.dumps(mcp_rows, ensure_ascii=False, indent=2) + "\n")
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


def extract_scenario_bundle_dir(raw: bytes) -> Path:
    """解压到临时目录；调用方负责 shutil.rmtree。"""
    tmp = Path(tempfile.mkdtemp(prefix="scenario-bundle-"))
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = (info.filename or "").replace("\\", "/").strip("/")
                if not name:
                    continue
                parts = [p for p in name.split("/") if p and p != "."]
                if not _zip_parts_safe(parts):
                    raise ValueError("unsafe_zip_path")
                dest = (tmp / Path(*parts)).resolve()
                if not str(dest).startswith(str(tmp.resolve())):
                    raise ValueError("zip_path_escape")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info.filename, "r") as rf:
                    dest.write_bytes(rf.read())
    except zipfile.BadZipFile:
        shutil.rmtree(tmp, ignore_errors=True)
        raise ValueError("invalid_zip") from None
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return tmp


def read_bundle_manifest_and_lists(
    bundle_dir: Path,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    man_path = bundle_dir / MANIFEST_NAME
    if not man_path.is_file():
        raise ValueError("missing_scenario_bundle_json")
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    preset = manifest.get("preset")
    if not isinstance(preset, dict):
        raise ValueError("missing_preset_in_manifest")

    dha_list: List[Dict[str, Any]] = []
    dha_path = bundle_dir / DHA_NAME
    if dha_path.is_file():
        raw = json.loads(dha_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            dha_list = [x for x in raw if isinstance(x, dict)]

    mcp_list: List[Dict[str, Any]] = []
    mcp_path = bundle_dir / MCP_NAME
    if mcp_path.is_file():
        raw = json.loads(mcp_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            mcp_list = [x for x in raw if isinstance(x, dict)]

    return manifest, preset, dha_list, mcp_list


def list_skill_ids_in_bundle_skills_dir(bundle_dir: Path) -> List[str]:
    root = bundle_dir / "skills"
    if not root.is_dir():
        return []
    out: List[str] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        sid = child.name.strip()
        if not sid or sid in (".", "..") or ".." in sid:
            continue
        if (child / "SKILL.md").is_file():
            out.append(sid)
    return out


def copy_bundle_skills_to_user(
    bundle_dir: Path,
    user_skills_dir: Path,
    *,
    overwrite: bool,
) -> Tuple[List[str], List[str]]:
    """将 bundle_dir/skills/<id>/ 复制到用户技能目录，目录名即 skill_id。"""
    imported: List[str] = []
    skipped: List[str] = []
    skills_root = bundle_dir / "skills"
    if not skills_root.is_dir():
        return imported, skipped
    user_skills_dir.mkdir(parents=True, exist_ok=True)
    for child in skills_root.iterdir():
        if not child.is_dir():
            continue
        sid = child.name.strip()
        if not sid or sid in (".", "..") or ".." in sid:
            continue
        if not (child / "SKILL.md").is_file():
            continue
        dest = (user_skills_dir / sid).resolve()
        try:
            dest.relative_to(user_skills_dir.resolve())
        except ValueError:
            continue
        if dest.exists():
            if not overwrite:
                skipped.append(sid)
                continue
            shutil.rmtree(dest)
        shutil.copytree(child, dest)
        imported.append(sid)
    return imported, skipped


def strip_dha_row_for_disk(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in row.items() if k not in ("expert_id", "file_capability_labels")}
    return out


def _name_key(raw: Any) -> str:
    return str(raw or "").strip().lower()


def merge_dha_instances_for_bundle(
    user_instances: List[Dict[str, Any]],
    bundle_instances: List[Dict[str, Any]],
    *,
    overwrite: bool,
) -> List[Dict[str, Any]]:
    by_id: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in user_instances:
        aid = str(row.get("agent_id") or "").strip()
        if not aid:
            continue
        by_id[aid] = strip_dha_row_for_disk(dict(row))
        order.append(aid)
    for row in bundle_instances:
        aid = str(row.get("agent_id") or "").strip()
        if not aid:
            continue
        cleaned = strip_dha_row_for_disk(dict(row))
        incoming_name_key = _name_key(cleaned.get("name"))
        conflict_ids = []
        if aid in by_id:
            conflict_ids.append(aid)
        if incoming_name_key:
            conflict_ids.extend(
                old_id
                for old_id, old_row in by_id.items()
                if old_id != aid and _name_key(old_row.get("name")) == incoming_name_key
            )
        conflict_ids = list(dict.fromkeys(conflict_ids))
        if conflict_ids:
            if overwrite:
                for old_id in conflict_ids:
                    by_id.pop(old_id, None)
                order = [old_id for old_id in order if old_id in by_id]
                by_id[aid] = cleaned
                order.append(aid)
        else:
            by_id[aid] = cleaned
            order.append(aid)
    return [by_id[k] for k in order if k in by_id]


def merge_mcp_servers_for_bundle(
    user_servers: List[Dict[str, Any]],
    bundle_servers: List[Dict[str, Any]],
    *,
    skip_existing: bool,
) -> Tuple[List[Dict[str, Any]], int, int, int]:
    by_id: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for s in user_servers:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        by_id[sid] = dict(s)
        order.append(sid)
    added = 0
    skipped = 0
    updated = 0
    for s in bundle_servers:
        sid = str(s.get("id") or "").strip()
        if not sid:
            continue
        incoming_name_key = _name_key(s.get("name"))
        conflict_ids = []
        if sid in by_id:
            conflict_ids.append(sid)
        if incoming_name_key:
            conflict_ids.extend(
                old_id
                for old_id, old_row in by_id.items()
                if old_id != sid and _name_key(old_row.get("name")) == incoming_name_key
            )
        conflict_ids = list(dict.fromkeys(conflict_ids))
        if conflict_ids:
            if skip_existing:
                skipped += 1
                continue
            for old_id in conflict_ids:
                by_id.pop(old_id, None)
            order = [old_id for old_id in order if old_id in by_id]
            by_id[sid] = dict(s)
            order.append(sid)
            updated += 1
        else:
            by_id[sid] = dict(s)
            order.append(sid)
            added += 1
    return [by_id[i] for i in order if i in by_id], added, skipped, updated
