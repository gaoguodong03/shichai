"""Helpers for group-chat tool traces and workspace previews."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from urllib.parse import parse_qs, unquote, urlparse


_WORKSPACE_DOWNLOAD_URL_RE = re.compile(r"/api/workspaces/[^\s)\"'<>]+/files/download\?path=[^\s)\"'<>]+")


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
