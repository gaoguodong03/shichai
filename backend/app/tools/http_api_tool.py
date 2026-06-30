"""Saved HTTP API tool execution."""
from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Dict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.agent.tool_spec import ToolSpec
from app.tools.call_api import _call_api_impl

_TOOL_NAME_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _runtime_tool_name(display_name: str) -> str:
    raw = str(display_name or "").strip()
    safe = _TOOL_NAME_INVALID_CHARS_RE.sub("_", raw).strip("_.-")
    if not safe:
        safe = "tool"
    if safe != raw:
        safe = f"{safe}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"
    return f"http_api_{safe}"


def _subst_placeholders(value: str, secrets: Dict[str, str]) -> str:
    def repl_vault(match: re.Match[str]) -> str:
        return secrets.get(match.group(1), "")

    def repl_env(match: re.Match[str]) -> str:
        name = match.group(1)
        return os.environ.get(name) or secrets.get(name, "")

    out = re.sub(r"\$\{vault:([A-Za-z0-9_-]+)\}", repl_vault, value)
    out = re.sub(r"\$\{(\w+)\}", repl_env, out)
    return out


def _subst_jsonish(value: Any, secrets: Dict[str, str]) -> Any:
    if isinstance(value, str):
        return _subst_placeholders(value, secrets)
    if isinstance(value, list):
        return [_subst_jsonish(item, secrets) for item in value]
    if isinstance(value, dict):
        return {str(k): _subst_jsonish(v, secrets) for k, v in value.items()}
    return value


def _merge_dict(base: Any, extra: Any) -> Dict[str, Any]:
    out = dict(base) if isinstance(base, dict) else {}
    if isinstance(extra, dict):
        out.update(extra)
    return out


def _append_path(base_url: str, path: str) -> str:
    base = str(base_url or "").strip()
    suffix = str(path or "").strip()
    if not suffix:
        return base
    return base.rstrip("/") + "/" + suffix.lstrip("/")


def _append_query(url: str, query: Dict[str, Any]) -> str:
    if not query:
        return url
    parts = urlsplit(url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    for key, value in query.items():
        if isinstance(value, list):
            for item in value:
                pairs.append((str(key), str(item)))
        elif value is not None:
            pairs.append((str(key), str(value)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))


def create_http_api_tool(row: Dict[str, Any], secrets: Dict[str, str] | None = None) -> ToolSpec:
    name = str((row or {}).get("name") or "").strip()
    cfg = (row or {}).get("config") if isinstance((row or {}).get("config"), dict) else {}
    secrets = secrets or {}

    def _execute(query: Dict[str, Any] | None = None, body: Any = None, headers: Dict[str, Any] | None = None) -> str:
        merged_query = _subst_jsonish(_merge_dict(cfg.get("query"), query), secrets)
        merged_headers = _subst_jsonish(_merge_dict(cfg.get("header"), headers), secrets)
        configured_body = cfg.get("body")
        payload = configured_body if body is None else body
        payload = _subst_jsonish(payload, secrets)
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False)
        url = _append_query(
            _append_path(_subst_placeholders(str(cfg.get("base_url") or ""), secrets), str(cfg.get("path") or "")),
            merged_query,
        )
        return _call_api_impl(
            url=url,
            method=str(cfg.get("type") or "GET"),
            headers_json=json.dumps(merged_headers, ensure_ascii=False) if merged_headers else "",
            body=payload,
            timeout_seconds=float(cfg.get("timeout_seconds") or 60),
        )

    return ToolSpec.from_function(
        name=_runtime_tool_name(name),
        description=f"调用已保存的 HTTP API 工具「{name}」。可传 query、headers 或 body 覆盖/补充默认配置。",
        func=_execute,
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "object", "description": "追加或覆盖默认查询参数。"},
                "headers": {"type": "object", "description": "追加或覆盖默认请求头。"},
                "body": {"description": "覆盖默认请求体；对象会自动序列化为 JSON。"},
            },
        },
    )
