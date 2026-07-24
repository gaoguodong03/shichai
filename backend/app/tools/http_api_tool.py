"""Saved HTTP API tool execution."""
from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import re
from typing import Any, Dict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.agent.platform_prompts import render_platform_prompt
from app.agent.tool_spec import ToolSpec
from app.agent.workspace_visibility import WorkspacePathError, normalize_public_workspace_path
from app.api.files import get_workspace_root_path
from app.tools.call_api import _call_api_response_impl

_TOOL_NAME_INVALID_CHARS_RE = re.compile(r"[^a-zA-Z0-9_.-]+")


def _runtime_tool_name(display_name: str) -> str:
    raw = str(display_name or "").strip()
    safe = _TOOL_NAME_INVALID_CHARS_RE.sub("_", raw).strip("_.-")
    if not safe:
        safe = "tool"
    if safe != raw:
        safe = f"{safe}_{hashlib.sha1(raw.encode('utf-8')).hexdigest()[:8]}"
    return f"http_api_{safe}"


def _subst_placeholders(value: str, env_vars: Dict[str, str]) -> str:
    def repl_platform_env(match: re.Match[str]) -> str:
        name = match.group(1)
        return env_vars.get(name, "") or os.environ.get(name, "")

    return re.sub(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}", repl_platform_env, value)


def _subst_jsonish(value: Any, env_vars: Dict[str, str]) -> Any:
    if isinstance(value, str):
        return _subst_placeholders(value, env_vars)
    if isinstance(value, list):
        return [_subst_jsonish(item, env_vars) for item in value]
    if isinstance(value, dict):
        return {str(k): _subst_jsonish(v, env_vars) for k, v in value.items()}
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


def _workspace_file_payload(
    payload: Any,
    workspace_file: Dict[str, Any] | None,
    file_upload_config: Dict[str, Any] | None,
    workspace_id: str,
) -> Any:
    if workspace_file is None:
        return payload
    if not isinstance(file_upload_config, dict):
        raise ValueError("此 HTTP API 工具未配置文件上传字段。")
    if not isinstance(workspace_file, dict):
        raise ValueError("workspace_file 必须是包含 path 的对象。")
    if not str(workspace_id or "").strip():
        raise ValueError("缺少当前会话工作区，无法上传文件。")
    raw_path = str(workspace_file.get("path") or "").strip()
    if not raw_path:
        raise ValueError("workspace_file.path 不能为空。")
    try:
        relative_path = normalize_public_workspace_path(raw_path)
    except WorkspacePathError as exc:
        raise ValueError(f"文件路径无效：{exc}") from exc
    workspace_root = get_workspace_root_path(workspace_id).resolve()
    source = (workspace_root / relative_path).resolve()
    try:
        source.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("文件路径必须位于当前会话工作区内。") from exc
    if not source.is_file():
        raise ValueError(f"工作区文件不存在：{relative_path}")
    max_bytes = int(file_upload_config.get("max_bytes") or 0)
    size = source.stat().st_size
    if max_bytes > 0 and size > max_bytes:
        raise ValueError(f"文件超过工具允许的大小上限：{max_bytes} 字节。")
    if not isinstance(payload, dict):
        raise ValueError("文件上传请求体必须是 JSON 对象。")

    content_field = str(file_upload_config.get("content_base64_field") or "contentBase64").strip()
    filename_field = str(file_upload_config.get("filename_field") or "filename").strip()
    mime_type_field = str(file_upload_config.get("mime_type_field") or "mimeType").strip()
    if not content_field or not filename_field or not mime_type_field:
        raise ValueError("文件上传字段配置不完整。")
    filename = source.name
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    merged = dict(payload)
    merged[content_field] = base64.b64encode(source.read_bytes()).decode("ascii")
    merged[filename_field] = filename
    merged[mime_type_field] = mime_type
    return merged


def _workspace_text_payload(
    payload: Any,
    workspace_file: Dict[str, Any] | None,
    workspace_text_config: Dict[str, Any] | None,
    workspace_id: str,
) -> Any:
    if workspace_file is None:
        return payload
    if not isinstance(workspace_text_config, dict):
        raise ValueError("此 HTTP API 工具未配置工作区文本字段。")
    if not isinstance(workspace_file, dict):
        raise ValueError("workspace_file 必须是包含 path 的对象。")
    if not str(workspace_id or "").strip():
        raise ValueError("缺少当前会话工作区，无法读取文本。")
    raw_path = str(workspace_file.get("path") or "").strip()
    if not raw_path:
        raise ValueError("workspace_file.path 不能为空。")
    try:
        relative_path = normalize_public_workspace_path(raw_path)
    except WorkspacePathError as exc:
        raise ValueError(f"文件路径无效：{exc}") from exc
    workspace_root = get_workspace_root_path(workspace_id).resolve()
    source = (workspace_root / relative_path).resolve()
    try:
        source.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("文件路径必须位于当前会话工作区内。") from exc
    if not source.is_file():
        raise ValueError(f"工作区文件不存在：{relative_path}")

    allowed_extensions = [
        str(item).strip().lower()
        for item in workspace_text_config.get("allowed_extensions") or []
        if str(item).strip()
    ]
    if allowed_extensions and source.suffix.lower() not in allowed_extensions:
        raise ValueError(f"不允许的文件类型：{source.suffix or '无扩展名'}。")
    max_bytes = int(workspace_text_config.get("max_bytes") or 0)
    size = source.stat().st_size
    if max_bytes > 0 and size > max_bytes:
        raise ValueError(f"文件超过工具允许的大小上限：{max_bytes} 字节。")
    encoding = str(workspace_text_config.get("encoding") or "utf-8").strip() or "utf-8"
    try:
        content = source.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise ValueError(f"工作区文件无法按 {encoding} 解码。") from exc
    except LookupError as exc:
        raise ValueError(f"不支持的文本编码：{encoding}。") from exc

    if payload is None:
        merged: Dict[str, Any] = {}
    elif isinstance(payload, dict):
        merged = dict(payload)
    else:
        raise ValueError("工作区文本请求体必须是 JSON 对象。")
    content_field = str(workspace_text_config.get("content_field") or "body").strip()
    title_field = str(workspace_text_config.get("title_field") or "title").strip()
    if not content_field or not title_field:
        raise ValueError("工作区文本字段配置不完整。")
    merged[content_field] = content
    if not str(merged.get(title_field) or "").strip():
        merged[title_field] = source.stem
    return merged


def create_http_api_tool(
    row: Dict[str, Any],
    env_vars: Dict[str, str] | None = None,
    workspace_id: str = "",
) -> ToolSpec:
    name = str((row or {}).get("name") or "").strip()
    cfg = (row or {}).get("config") if isinstance((row or {}).get("config"), dict) else {}
    env_vars = env_vars or {}

    def _execute(
        query: Dict[str, Any] | None = None,
        body: Any = None,
        headers: Dict[str, Any] | None = None,
        workspace_file: Dict[str, Any] | None = None,
    ) -> object:
        merged_query = _subst_jsonish(_merge_dict(cfg.get("query"), query), env_vars)
        merged_headers = _subst_jsonish(_merge_dict(cfg.get("header"), headers), env_vars)
        configured_body = cfg.get("body")
        payload = configured_body if body is None else body
        payload = _subst_jsonish(payload, env_vars)
        file_upload_config = cfg.get("file_upload")
        workspace_text_config = cfg.get("workspace_text")
        if isinstance(file_upload_config, dict) and isinstance(workspace_text_config, dict):
            raise ValueError("file_upload 和 workspace_text 不能同时配置。")
        if isinstance(workspace_text_config, dict):
            payload = _workspace_text_payload(payload, workspace_file, workspace_text_config, workspace_id)
        else:
            payload = _workspace_file_payload(payload, workspace_file, file_upload_config, workspace_id)
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False)
        url = _append_query(
            _append_path(_subst_placeholders(str(cfg.get("base_url") or ""), env_vars), str(cfg.get("path") or "")),
            merged_query,
        )
        return _call_api_response_impl(
            url=url,
            method=str(cfg.get("type") or "GET"),
            headers_json=json.dumps(merged_headers, ensure_ascii=False) if merged_headers else "",
            body=payload,
            timeout_seconds=float(cfg.get("timeout_seconds") or 60),
        )

    tool = ToolSpec.from_function(
        name=_runtime_tool_name(name),
        description=render_platform_prompt("tool.description.saved_http_api.v1", {"tool_name": name}),
        func=_execute,
        args_schema={
            "type": "object",
            "properties": {
                "query": {"type": "object", "description": render_platform_prompt("tool.schema.saved_http_api.query.v1", {})},
                "headers": {"type": "object", "description": render_platform_prompt("tool.schema.saved_http_api.headers.v1", {})},
                "body": {"description": render_platform_prompt("tool.schema.saved_http_api.body.v1", {})},
                "workspace_file": {
                    "type": "object",
                    "description": render_platform_prompt("tool.schema.saved_http_api.workspace_file.v1", {}),
                },
            },
        },
    )
    tool.metadata.update(
        {
            "source": "api",
            "provider": name,
            "provider_tool": tool.name,
        }
    )
    return tool
