"""Skill script manifest contract helpers.

This module owns parsing `scripts/manifest.json`, generating the model-visible
tool schema, and converting manifest arguments into CLI argv. It does not run
scripts, touch sandboxes, or read user workspace files.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ALLOWED_SCRIPT_SUFFIX = {".py", ".sh", ".bash", ".ps1", ".cmd", ".bat"}
CLI_ARGV_MAX_ITEMS = 64
CLI_ARGV_MAX_STRLEN = 32_768


def normalize_skill_script_path(script_path: str) -> str:
    """Normalize a manifest entry to a relative path inside scripts/."""
    path = (script_path or "").strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:].lstrip("/")
    return path


def load_skill_script_manifest(script_root: Path) -> dict[str, Any]:
    """Load the standard manifest format; non-standard legacy shapes are ignored."""
    manifest_path = script_root / "manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    raw_entry = str(raw.get("entry") or "").strip().replace("\\", "/")
    normalized_raw_entry = raw_entry
    while normalized_raw_entry.startswith("./"):
        normalized_raw_entry = normalized_raw_entry[2:].lstrip("/")
    if normalized_raw_entry.lower().startswith("scripts/"):
        return {}
    entry = normalize_skill_script_path(raw_entry)
    if not entry or ".." in entry or entry.startswith("/"):
        return {}
    if Path(entry).suffix.lower() not in ALLOWED_SCRIPT_SUFFIX:
        return {}
    description = str(raw.get("description") or "").strip()
    args = raw.get("args")
    if not description or not isinstance(args, list):
        return {}
    normalized_args: list[dict[str, Any]] = []
    for item in args:
        if not isinstance(item, dict):
            return {}
        name = str(item.get("name") or "").strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            return {}
        normalized_args.append(
            {
                "name": name,
                "description": str(item.get("description") or "").strip(),
                "required": bool(item.get("required")),
                "type": str(item.get("type") or "string").strip() or "string",
                "default": item.get("default"),
            }
        )
    return {"entry": entry, "description": description, "args": normalized_args}


def input_schema_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Build the LLM-visible input schema from manifest args."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    for arg in manifest.get("args") or []:
        if not isinstance(arg, dict):
            continue
        name = str(arg.get("name") or "").strip()
        if not name:
            continue
        schema: dict[str, Any] = {
            "type": _json_schema_type(str(arg.get("type") or "string")),
            "description": str(arg.get("description") or "").strip(),
        }
        if arg.get("default") is not None:
            schema["default"] = arg.get("default")
        properties[name] = schema
        if arg.get("required"):
            required.append(name)
    out: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        out["required"] = required
    return out


def manifest_args_to_cli_argv(manifest: dict[str, Any], values: dict[str, Any]) -> tuple[list[str] | None, str | None]:
    """Convert structured manifest args into script CLI argv."""
    argv: list[str] = []
    allowed_names = {str(item.get("name") or "") for item in (manifest.get("args") or []) if isinstance(item, dict)}
    unknown = sorted(k for k in values if k not in allowed_names)
    if unknown:
        return None, f"脚本参数不在 manifest 中: {unknown}"
    for arg in manifest.get("args") or []:
        if not isinstance(arg, dict):
            continue
        name = str(arg.get("name") or "").strip()
        if not name:
            continue
        required = bool(arg.get("required"))
        raw_value = values.get(name, arg.get("default"))
        is_empty = raw_value is None or raw_value == "" or raw_value == []
        if is_empty:
            if required:
                return None, f"脚本缺少必填参数: {name}"
            continue
        value_error = _validate_cli_value(name, raw_value)
        if value_error:
            return None, value_error
        flag = _cli_flag_for_arg(name)
        if isinstance(raw_value, bool):
            if raw_value:
                argv.append(flag)
            elif required:
                argv.extend([flag, "false"])
            continue
        if isinstance(raw_value, list):
            for item in raw_value:
                argv.extend([flag, str(item)])
            continue
        argv.extend([flag, str(raw_value)])
    if len(argv) > CLI_ARGV_MAX_ITEMS:
        return None, f"脚本参数转换后的 argv 数量不能超过 {CLI_ARGV_MAX_ITEMS}"
    return argv, None


def _json_schema_type(raw: str) -> str:
    allowed = {"string", "number", "integer", "boolean", "array", "object"}
    return raw if raw in allowed else "string"


def _cli_flag_for_arg(name: str) -> str:
    return "--" + str(name or "").strip().replace("_", "-")


def _validate_cli_value(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        values = value if isinstance(value, list) else [json.dumps(value, ensure_ascii=False)]
    else:
        values = [value]
    for item in values:
        text = str(item)
        if "\x00" in text:
            return f"{name} 含非法字符"
        if len(text) > CLI_ARGV_MAX_STRLEN:
            return f"{name} 长度不能超过 {CLI_ARGV_MAX_STRLEN}"
    return None
