#!/usr/bin/env python3
"""从 HTML 中提取正文（供 run_skill_script_url-fetch 调用，CLI-only）。"""

from __future__ import annotations

import argparse
import pathlib
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract main content from HTML.",
        epilog="CLI-only: provide --html or --html_file.",
    )
    parser.add_argument("--html", default="", help="Inline html string")
    parser.add_argument("--html_file", default="", help="Path to html file")
    parser.add_argument("--url", default="", help="Optional source URL")
    parser.add_argument("--max_chars", type=int, default=8000, help="Max chars in output")
    return parser.parse_args(argv)


def _load_html(args: argparse.Namespace) -> str:
    if (args.html or "").strip():
        return str(args.html)
    if (args.html_file or "").strip():
        p = pathlib.Path(str(args.html_file)).expanduser()
        if not p.exists() or not p.is_file():
            print(f"错误：html_file 不存在: {p}")
            sys.exit(2)
        return p.read_text(encoding="utf-8", errors="replace")
    print("错误：请通过 --html 或 --html_file 提供 HTML 输入。")
    sys.exit(2)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    html = _load_html(args).strip()
    url = str(args.url or "").strip()

    text = _extract_with_trafilatura(html)
    method = "trafilatura"
    if not text:
        text = _extract_with_bs4(html)
        method = "bs4"
    if not text:
        print("错误：未能从 HTML 提取正文。")
        sys.exit(1)

    cleaned = _cleanup_text(text, max_chars=int(args.max_chars or 8000))
    lines = []
    if url:
        lines.append(f"URL: {url}")
    lines.append(f"EXTRACT_METHOD: {method}")
    lines.append("MAIN_CONTENT:")
    lines.append(cleaned)
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1:])
