"""场景包（ZIP）：内含场景预设、专家快照、技能目录、可选 MCP 列表，用于一键分享与导入。"""
from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple
from urllib.parse import unquote_plus, urlsplit

from app.core.host_config import normalize_host_config_dict
from app.core.name_based_resources import normalize_tool_row, strip_resource_ids

BUNDLE_VERSION = 1
MANIFEST_NAME = "scenario_bundle.json"
AGENTS_BUNDLE_FILE_NAME = "agents.json"
MCP_NAME = "mcp_servers.json"
SKILLS_PREFIX = "skills/"


_SENSITIVE_CONFIG_TOKENS = {
    "apikey",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "key",
    "passwd",
    "password",
    "secret",
    "token",
}
_VAULT_REF_RE = re.compile(r"\$\{vault:[^}]+\}")
_ENV_REF_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*\}")
_SANITIZABLE_URL_SCHEMES = {"http", "https", "ws", "wss"}
_PLACEHOLDER_VALUE_TOKENS = {
    "api_key",
    "apikey",
    "your_api_key",
    "your_apikey",
    "token",
    "your_token",
    "access_token",
    "your_access_token",
    "secret",
    "your_secret",
    "password",
    "your_password",
    "your_username",
    "your_client_id",
    "your_client_secret",
    "your_actual_api_key_here",
    "placeholder",
    "replace_me",
    "changeme",
    "todo",
}


def _zip_parts_safe(parts: List[str]) -> bool:
    if not parts:
        return False
    return not any(not p or p == "." or p == ".." or ".." in p for p in parts)


def _is_sensitive_config_key(raw_key: Any) -> bool:
    key = str(raw_key or "").strip().casefold()
    if not key:
        return False
    compact = re.sub(r"[^a-z0-9]+", "", key)
    tokens = [x for x in re.split(r"[^a-z0-9]+", key) if x]
    if compact in _SENSITIVE_CONFIG_TOKENS:
        return True
    if any(token in _SENSITIVE_CONFIG_TOKENS for token in tokens):
        return True
    return any(compact.endswith(suffix) for suffix in ("apikey", "token", "secret", "password", "passwd"))


def _contains_vault_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_VAULT_REF_RE.search(value))


def _contains_config_ref(value: Any) -> bool:
    return isinstance(value, str) and bool(_VAULT_REF_RE.search(value) or _ENV_REF_RE.search(value))


def _sanitize_secret_mapping(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    out: Dict[str, Any] = {}
    for key, value in raw.items():
        if _is_sensitive_config_key(key) and not _contains_config_ref(value):
            out[str(key)] = ""
        else:
            out[str(key)] = value
    return out


def _is_auth_control_key(raw_key: Any) -> bool:
    return re.sub(r"[^a-z0-9]+", "", str(raw_key or "").strip().casefold()) in {
        "auth",
        "authtype",
        "authmode",
        "authorizationurl",
        "authurl",
    }


def _looks_like_header_secret(value: Any) -> bool:
    return isinstance(value, str) and bool(re.match(r"^\s*(Bearer|Basic|Digest|Token)\s+\S+", value, re.I))


def _is_placeholder_config_value(value: Any, key: Any = "") -> bool:
    if not isinstance(value, str) or _contains_config_ref(value):
        return False
    trimmed = value.strip()
    if not trimmed:
        return False
    if re.match(r"^<[^>]+>$", trimmed) or re.match(r"^\{\{[^}]+\}\}$", trimmed):
        return True
    normalized = re.sub(r"[^a-z0-9]+", "_", trimmed.casefold()).strip("_")
    compact_key = re.sub(r"[^a-z0-9]+", "", str(key or "").casefold())
    return normalized in _PLACEHOLDER_VALUE_TOKENS or (
        normalized.startswith("your_") and bool(re.search(r"key|token|secret|password|username|client", compact_key + normalized))
    )


def _should_clear_sensitive_value(key: Any, value: Any) -> bool:
    if not isinstance(value, str) or not value or _contains_config_ref(value):
        return False
    normalized_key = re.sub(r"[^a-z0-9]+", "", str(key or "").casefold())
    if _is_sensitive_config_key(key):
        return True
    if "authorization" in normalized_key and _looks_like_header_secret(value):
        return True
    if _is_auth_control_key(key):
        return False
    if str(key) in {"command", "args"}:
        return False
    return _is_placeholder_config_value(value, key)


def _sanitize_url_query(value: str) -> str:
    if "?" not in value:
        return value
    try:
        parsed = urlsplit(value)
    except ValueError:
        return value
    if parsed.scheme not in _SANITIZABLE_URL_SCHEMES:
        return value

    query_start = value.find("?")
    fragment_start = value.find("#")
    if fragment_start != -1 and fragment_start < query_start:
        return value
    query_end = len(value) if fragment_start == -1 else fragment_start
    prefix = value[: query_start + 1]
    raw_query = value[query_start + 1 : query_end]
    suffix = value[query_end:]
    changed = False
    parts: List[str] = []
    for part in raw_query.split("&"):
        raw_key, sep, raw_param_value = part.partition("=")
        key = unquote_plus(raw_key)
        param_value = unquote_plus(raw_param_value)
        if _contains_config_ref(raw_param_value) or _contains_config_ref(param_value):
            parts.append(part)
            continue
        if _is_sensitive_config_key(key) or _is_placeholder_config_value(param_value, key):
            changed = True
            parts.append(f"{raw_key}=")
        else:
            parts.append(part if sep else raw_key)
    return f"{prefix}{'&'.join(parts)}{suffix}" if changed else value


def _sanitize_mcp_config_recursive(value: Any, key_name: str = "") -> Any:
    if isinstance(value, str):
        if _should_clear_sensitive_value(key_name, value):
            return ""
        return _sanitize_url_query(value)
    if isinstance(value, list):
        out: List[Any] = []
        for item in value:
            if key_name == "args" and isinstance(item, str):
                out.append(_sanitize_url_query(item))
            else:
                out.append(_sanitize_mcp_config_recursive(item, key_name))
        return out
    if isinstance(value, dict):
        return {str(k): _sanitize_mcp_config_recursive(v, str(k)) for k, v in value.items()}
    return value


def sanitize_mcp_server_for_bundle(server: Dict[str, Any]) -> Dict[str, Any]:
    """Return a bundle-safe MCP config row: keep wiring, omit plaintext secrets."""
    copied = json.loads(json.dumps(server, ensure_ascii=False))
    server_config = copied.get("server_config")
    if isinstance(server_config, str) and server_config.strip():
        try:
            parsed = json.loads(server_config)
            copied["server_config"] = json.dumps(_sanitize_mcp_config_recursive(parsed), ensure_ascii=False, indent=2)
        except Exception:
            copied["server_config"] = _sanitize_url_query(server_config)
    transport = copied.get("transport")
    if isinstance(transport, dict):
        copied["transport"] = _sanitize_mcp_config_recursive(transport)
        transport = copied.get("transport")
        if isinstance(transport, dict):
            if "env" in transport:
                transport["env"] = _sanitize_secret_mapping(transport.get("env"))
            if "headers" in transport:
                transport["headers"] = _sanitize_secret_mapping(transport.get("headers"))
    return copied


def sanitize_mcp_servers_for_bundle(servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [sanitize_mcp_server_for_bundle(row) for row in servers if isinstance(row, dict)]


def collect_skill_directories_and_tool_names_for_preset(
    preset: Dict[str, Any], agent_by_name: Dict[str, Any]
) -> Tuple[Set[str], Set[str]]:
    skill_directories: Set[str] = set()
    tool_names: Set[str] = set()
    hc_raw = preset.get("host") or preset.get("host_config")
    if isinstance(hc_raw, dict):
        hc = normalize_host_config_dict(hc_raw)
        skill_directory = str(hc.get("skill_directory") or "").strip()
        if skill_directory:
            skill_directories.add(skill_directory)
    for agent_name in preset.get("agent_names") or []:
        key = str(agent_name.get("name") if isinstance(agent_name, dict) else agent_name).strip()
        d = agent_by_name.get(key)
        if not isinstance(d, dict):
            continue
        for x in d.get("skills") or []:
            s = str(x.get("directory_name") if isinstance(x, dict) else x).strip()
            if s:
                skill_directories.add(s)
    return skill_directories, tool_names


def build_scenario_bundle_zip_bytes(
    preset_row: Dict[str, Any],
    expert_rows: List[Dict[str, Any]],
    mcp_rows: List[Dict[str, Any]],
    skills_root: Path,
    skill_directories: List[str],
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "bundle_version": BUNDLE_VERSION,
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "preset": strip_resource_ids(preset_row),
        }
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(AGENTS_BUNDLE_FILE_NAME, json.dumps(strip_resource_ids(expert_rows), ensure_ascii=False, indent=2) + "\n")
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

    agent_list: List[Dict[str, Any]] = []
    agent_path = bundle_dir / AGENTS_BUNDLE_FILE_NAME
    if agent_path.is_file():
        raw = json.loads(agent_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            agent_list = [x for x in raw if isinstance(x, dict)]

    mcp_list: List[Dict[str, Any]] = []
    mcp_path = bundle_dir / MCP_NAME
    if mcp_path.is_file():
        raw = json.loads(mcp_path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            mcp_list = [x for x in raw if isinstance(x, dict)]

    return manifest, preset, agent_list, mcp_list


def list_skill_directories_in_bundle_skills_dir(bundle_dir: Path) -> List[str]:
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
    """将 bundle_dir/skills/<id>/ 复制到用户技能目录，目录名即 skill_directory。"""
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


def strip_agent_row_for_disk(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in strip_resource_ids(row).items() if k not in ("file_capability_labels",)}
    return out


def _name_key(raw: Any) -> str:
    return str(raw or "").strip().lower()


def merge_agent_instances_for_bundle(
    user_instances: List[Dict[str, Any]],
    bundle_instances: List[Dict[str, Any]],
    *,
    overwrite: bool,
) -> List[Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in user_instances:
        cleaned = strip_agent_row_for_disk(dict(row))
        name = str(cleaned.get("name") or "").strip()
        if not name:
            continue
        by_name[name] = cleaned
        order.append(name)
    for row in bundle_instances:
        cleaned = strip_agent_row_for_disk(dict(row))
        incoming_name_key = _name_key(cleaned.get("name"))
        incoming_name = str(cleaned.get("name") or "").strip()
        if not incoming_name_key or not incoming_name:
            continue
        conflict_names = [
            old_name
            for old_name, old_row in by_name.items()
            if _name_key(old_row.get("name")) == incoming_name_key
        ]
        conflict_names = list(dict.fromkeys(conflict_names))
        if conflict_names:
            if not overwrite:
                continue
            for old_name in conflict_names:
                by_name.pop(old_name, None)
            order = [old_name for old_name in order if old_name in by_name]
        by_name[incoming_name] = cleaned
        order.append(incoming_name)
    return [by_name[k] for k in order if k in by_name]


def merge_mcp_servers_for_bundle(
    user_servers: List[Dict[str, Any]],
    bundle_servers: List[Dict[str, Any]],
    *,
    skip_existing: bool,
) -> Tuple[List[Dict[str, Any]], int, int, int]:
    by_name: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for s in user_servers:
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        key = _name_key(name)
        by_name[key] = normalize_tool_row(s)
        order.append(key)
    added = 0
    skipped = 0
    updated = 0
    for s in bundle_servers:
        name = str(s.get("name") or "").strip()
        if not name:
            continue
        incoming_name_key = _name_key(name)
        if incoming_name_key in by_name:
            if skip_existing:
                skipped += 1
                continue
            by_name[incoming_name_key] = normalize_tool_row(s)
            updated += 1
        else:
            by_name[incoming_name_key] = normalize_tool_row(s)
            order.append(incoming_name_key)
            added += 1
    return [by_name[i] for i in order if i in by_name], added, skipped, updated
