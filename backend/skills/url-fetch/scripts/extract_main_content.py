#!/usr/bin/env python3
"""从 HTML 中提取正文（供 run_skill_script_url-fetch 调用）。"""

from __future__ import annotations

import json
import re
import sys
from html import unescape


def _cleanup_text(text: str, max_chars: int) -> str:
    text = unescape(text or "")
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = text.strip()
    if max_chars > 0:
        text = text[:max_chars]
    return text


def _extract_with_trafilatura(html: str) -> str:
    try:
        import trafilatura  # type: ignore
    except Exception:
        return ""
    try:
        out = trafilatura.extract(
            html,
            include_links=True,
            include_images=False,
            output_format="txt",
            favor_precision=True,
        )
        return out or ""
    except Exception:
        return ""


def _extract_with_bs4(html: str) -> str:
    try:
        from bs4 import BeautifulSoup  # type: ignore
    except Exception:
        return ""
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        body = soup.body if soup.body else soup
        return body.get_text("\n", strip=True)
    except Exception:
        return ""


def main() -> None:
    raw = sys.stdin.read().strip()
    if not raw:
        print("错误：缺少输入。请传入 input_json，至少包含 html 字段。")
        sys.exit(1)
    try:
        data = json.loads(raw)
    except Exception as e:
        print(f"错误：input_json 不是合法 JSON: {e}")
        sys.exit(1)
    if not isinstance(data, dict):
        print("错误：input_json 必须是对象。")
        sys.exit(1)

    html = str(data.get("html") or "").strip()
    url = str(data.get("url") or "").strip()
    max_chars = int(data.get("max_chars") or 8000)
    if not html:
        print("错误：html 不能为空。")
        sys.exit(1)

    text = _extract_with_trafilatura(html)
    method = "trafilatura"
    if not text:
        text = _extract_with_bs4(html)
        method = "bs4"
    if not text:
        print("错误：未能从 HTML 提取正文。")
        sys.exit(1)

    cleaned = _cleanup_text(text, max_chars=max_chars)
    lines = []
    if url:
        lines.append(f"URL: {url}")
    lines.append(f"EXTRACT_METHOD: {method}")
    lines.append("MAIN_CONTENT:")
    lines.append(cleaned)
    print("\n".join(lines))


if __name__ == "__main__":
    main()

