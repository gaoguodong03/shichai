"""Helpers for group-chat tool traces and workspace previews."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List
from urllib.parse import parse_qs, unquote, urlparse


_WORKSPACE_DOWNLOAD_URL_RE = re.compile(r"/api/workspaces/[^\s)\"'<>]+/files/download\?path=[^\s)\"'<>]+")
_WORKSPACE_WRITE_SUCCESS_RE = re.compile(r"已写入当前(?:\s*Chat)?\s*工作区文件[:：]\s*([^\s]+)")
_DELIVERY_CLAIM_RE = re.compile(
    r"(已生成|已经生成|生成完成|已保存|已经保存|保存到工作区|保存至工作区|图片链接|下载链接|可下载路径)"
)
_EXPLICIT_FILE_DELIVERY_RE = re.compile(r"(保存到工作区|保存至工作区|图片链接|下载链接|可下载路径)")
_MENTIONED_WORKSPACE_PATH_RE = re.compile(
    r"(?<![\w/])((?:generated_images|outputs|reports|materials|notes|drafts|images|exports)/[^\s`'\"）)>,，。；;]+)"
)


def _json_loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _normalize_workspace_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/api/workspaces/"):
        try:
            parsed = urlparse(text)
            paths = parse_qs(parsed.query).get("path") or []
            if paths:
                text = unquote(paths[0])
        except Exception:
            return ""
    text = text.strip().strip("`\"'，。；;)")
    while text.startswith("./"):
        text = text[2:].lstrip("/")
    text = text.lstrip("/")
    if not text or ".." in text.split("/"):
        return ""
    return text


def _iter_values(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        for item in value.values():
            yield item
            yield from _iter_values(item)
    elif isinstance(value, list):
        for item in value:
            yield item
            yield from _iter_values(item)


def _looks_like_success_payload(payload: dict[str, Any]) -> bool:
    status = str(payload.get("execution_status") or payload.get("status") or "").strip().lower()
    code = str(payload.get("result_code") or payload.get("code") or "").strip().lower()
    ok = payload.get("ok")
    return ok is True or status in {"succeeded", "success", "completed"} or code in {"succeeded", "success", "file.generated"}


def _extract_success_paths_from_payload(payload: dict[str, Any]) -> List[str]:
    if not _looks_like_success_payload(payload):
        return []
    paths: List[str] = []
    for value in _iter_values(payload):
        if not isinstance(value, str):
            continue
        normalized = _normalize_workspace_path(value)
        if normalized and (
            "/" in normalized
            or normalized.lower().endswith((".md", ".txt", ".csv", ".json", ".png", ".jpg", ".jpeg", ".webp", ".pdf"))
        ):
            paths.append(normalized)
    return paths


def _extract_success_paths_from_tool_results(tool_raw_results: List[str]) -> List[str]:
    paths: List[str] = []
    for raw in tool_raw_results or []:
        text = str(raw or "")
        for match in _WORKSPACE_WRITE_SUCCESS_RE.finditer(text):
            normalized = _normalize_workspace_path(match.group(1))
            if normalized:
                paths.append(normalized)
        for url in _WORKSPACE_DOWNLOAD_URL_RE.findall(text):
            normalized = _normalize_workspace_path(url)
            if normalized:
                paths.append(normalized)
        payload = _json_loads_maybe(text)
        if isinstance(payload, dict):
            paths.extend(_extract_success_paths_from_payload(payload))
            stdout_payload = _json_loads_maybe(payload.get("stdout"))
            if isinstance(stdout_payload, dict):
                paths.extend(_extract_success_paths_from_payload(stdout_payload))
    deduped: List[str] = []
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _verified_existing_paths(paths: List[str], workspace_root: Path | None) -> List[str]:
    if workspace_root is None:
        return paths
    root = workspace_root.resolve()
    verified: List[str] = []
    for path in paths:
        target = (root / path).resolve()
        if str(target).startswith(str(root)) and target.exists():
            verified.append(path)
    return verified


def _extract_mentioned_paths(content: str) -> List[str]:
    paths: List[str] = []
    for url in _WORKSPACE_DOWNLOAD_URL_RE.findall(content or ""):
        normalized = _normalize_workspace_path(url)
        if normalized:
            paths.append(normalized)
    for match in _MENTIONED_WORKSPACE_PATH_RE.finditer(content or ""):
        normalized = _normalize_workspace_path(match.group(1))
        if normalized:
            paths.append(normalized)
    deduped: List[str] = []
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def _raw_failure_summary(tool_raw_results: List[str]) -> str:
    lines: List[str] = []
    for raw in tool_raw_results or []:
        text = str(raw or "").strip()
        if not text:
            continue
        payload = _json_loads_maybe(text)
        if isinstance(payload, dict):
            for key in ("message", "error", "stderr", "gateway_error", "stdout"):
                value = str(payload.get(key) or "").strip()
                if value:
                    lines.append(value.splitlines()[0][:240])
                    break
        else:
            lines.append(text.splitlines()[0][:240])
        if len(lines) >= 3:
            break
    return "\n".join(f"- {line}" for line in lines if line)


def guard_unverified_delivery_claims(
    content: str,
    *,
    tool_calls: List[Dict[str, Any]] | None = None,
    tool_raw_results: List[str] | None = None,
    workspace_root: Path | None = None,
) -> str:
    """Replace unbacked "generated/saved" claims with a platform-verified status."""
    text = str(content or "")
    if not text.strip() or not _DELIVERY_CLAIM_RE.search(text):
        return content

    calls = tool_calls or []
    raw_results = [str(item or "") for item in (tool_raw_results or [])]
    mentioned_paths = _extract_mentioned_paths(text)
    has_relevant_tool_activity = bool(calls or raw_results)
    has_explicit_file_delivery = bool(_EXPLICIT_FILE_DELIVERY_RE.search(text) or mentioned_paths)
    if not has_relevant_tool_activity and not has_explicit_file_delivery:
        return content

    success_paths = _verified_existing_paths(_extract_success_paths_from_tool_results(raw_results), workspace_root)
    if success_paths:
        return content

    parts = [
        "本轮没有确认文件生成成功。",
        "平台没有捕获到成功的文件、图片或工作区写入工具结果，因此不能把专家回复中的生成/保存声明视为已完成。",
    ]
    if mentioned_paths:
        parts.append("原回复提到的路径或链接：\n" + "\n".join(f"- {path}" for path in mentioned_paths))
    summary = _raw_failure_summary(raw_results)
    if summary:
        parts.append("本轮工具返回摘要：\n" + summary)
    if calls:
        parts.append("请重新发起生成，或让专家先完成真实工具调用后再交付文件链接。")
    else:
        parts.append("请重新发起生成，或启用对应专家的文件/图片生成工具后再试。")
    return "\n\n".join(parts).strip()


def append_workspace_image_preview_markdown(content: str, tool_raw_results: List[str]) -> str:
    """Append Markdown image previews for workspace image download URLs found in tool output."""
    if not tool_raw_results:
        return content
    urls: List[str] = []
    for raw in tool_raw_results:
        if not raw:
            continue
        for url in _WORKSPACE_DOWNLOAD_URL_RE.findall(raw):
            urls.append(url)
    if not urls:
        return content
    image_urls = []
    for url in urls:
        lower_url = url.lower()
        if any(ext in lower_url for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")):
            image_urls.append(url)
    if not image_urls:
        return content
    seen = set()
    unique_urls = []
    for url in image_urls:
        if url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)
    base_text = content or ""
    filtered: List[str] = []
    for url in unique_urls:
        if url in base_text:
            continue
        try:
            query = parse_qs(urlparse(url).query)
            paths = query.get("path") or []
            if paths and unquote(paths[0]) in base_text:
                continue
        except Exception:
            pass
        filtered.append(url)
    if not filtered:
        return content
    blocks = [f"![生成图片{i}]({url})" for i, url in enumerate(filtered, start=1)]
    extra = "\n\n".join(blocks)
    if extra in base_text:
        return content
    base = (content or "").rstrip()
    return f"{base}\n\n---\n\n{extra}" if base else extra


def extract_tool_calls_from_accumulated(accumulated_chunks: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for chunk in accumulated_chunks or []:
        text = str(chunk or "")
        if "```json" not in text:
            continue
        try:
            block = text.split("```json", 1)[1].split("```", 1)[0].strip()
            obj = json.loads(block)
            if isinstance(obj, dict) and str(obj.get("action") or "").strip().lower() == "tool_call":
                out.append(
                    {
                        "tool": obj.get("tool"),
                        "arguments": obj.get("arguments") if isinstance(obj.get("arguments"), dict) else obj.get("arguments"),
                    }
                )
        except Exception:
            continue
    return out


def extract_sandbox_entry_trace(raw_outputs: List[str]) -> List[Dict[str, Any]]:
    traces: List[Dict[str, Any]] = []
    for item in raw_outputs or []:
        text = str(item or "").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                trace = obj.get("_sandbox_trace")
                if isinstance(trace, dict):
                    traces.append(trace)
        except Exception:
            continue
    return traces
