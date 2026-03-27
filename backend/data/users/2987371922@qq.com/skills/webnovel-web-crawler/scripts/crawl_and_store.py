#!/usr/bin/env python3
"""
Simple webpage crawler for web-novel research.
Stores raw HTML + cleaned text + metadata for each URL.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def slug_from_url(url: str) -> str:
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{now}_{digest}"


def extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    title = re.sub(r"\s+", " ", match.group(1)).strip()
    return html_unescape(title)


def html_unescape(text: str) -> str:
    # Minimal entity decode without external deps.
    entities = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&#39;": "'",
    }
    for src, dst in entities.items():
        text = text.replace(src, dst)
    return text


def html_to_text(html: str) -> str:
    # Remove scripts/styles/comments first.
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    # Convert block-like tags to line breaks to improve readability.
    text = re.sub(
        r"</?(p|div|br|li|h[1-6]|article|section|main|tr|td|blockquote)[^>]*>",
        "\n",
        text,
        flags=re.IGNORECASE,
    )
    # Remove remaining tags.
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_unescape(text)
    # Normalize whitespace but keep paragraphs.
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.strip() for line in text.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def fetch_url(url: str, timeout: int = 20) -> tuple[int, str, str]:
    req = urllib.request.Request(url=url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = int(getattr(resp, "status", 200))
        content_type = resp.headers.get("Content-Type", "")
        raw = resp.read()
        charset = "utf-8"
        match = re.search(r"charset=([a-zA-Z0-9\-_]+)", content_type)
        if match:
            charset = match.group(1)
        html = raw.decode(charset, errors="replace")
        return code, content_type, html


def ensure_dir(path: pathlib.Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def store_one(url: str, out_dir: pathlib.Path) -> dict:
    item_dir = out_dir / slug_from_url(url)
    ensure_dir(item_dir)
    fetched_at = dt.datetime.now(dt.timezone.utc).isoformat()

    result = {
        "url": url,
        "ok": False,
        "status_code": None,
        "content_type": "",
        "title": "",
        "fetched_at": fetched_at,
        "dir": str(item_dir.as_posix()),
        "error": "",
    }

    try:
        status_code, content_type, html = fetch_url(url)
        text = html_to_text(html)
        title = extract_title(html)

        (item_dir / "page.html").write_text(html, encoding="utf-8")
        (item_dir / "text.md").write_text(text + ("\n" if text else ""), encoding="utf-8")

        result.update(
            {
                "ok": True,
                "status_code": status_code,
                "content_type": content_type,
                "title": title,
            }
        )

    except urllib.error.HTTPError as e:
        result["error"] = f"HTTPError {e.code}: {e.reason}"
    except urllib.error.URLError as e:
        result["error"] = f"URLError: {e.reason}"
    except Exception as e:  # noqa: BLE001
        result["error"] = f"{type(e).__name__}: {e}"

    (item_dir / "meta.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def append_index(index_path: pathlib.Path, rows: list[dict]) -> None:
    ensure_dir(index_path.parent)
    with index_path.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch web pages and store html/text/meta for each URL."
    )
    parser.add_argument("urls", nargs="*", help="One or more target URLs.")
    parser.add_argument(
        "--out",
        default="output/pages",
        help="Output root directory. Default: output/pages",
    )
    return parser.parse_args(argv)


def _extract_urls_from_stdin_json() -> list[str]:
    """Support run_skill_script input_json via stdin.

    Accepted formats:
    - {"url": "..."}
    - {"urls": ["...", "..."]}
    - ["...", "..."]
    - "https://example.com"
    """
    if sys.stdin.isatty():
        return []
    raw = (sys.stdin.read() or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []

    if isinstance(data, str):
        return [data] if data.strip() else []
    if isinstance(data, list):
        return [str(x).strip() for x in data if str(x).strip()]
    if isinstance(data, dict):
        if "urls" in data and isinstance(data["urls"], list):
            return [str(x).strip() for x in data["urls"] if str(x).strip()]
        if "url" in data and str(data["url"]).strip():
            return [str(data["url"]).strip()]
    return []


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    urls = [u.strip() for u in (args.urls or []) if u and u.strip()]
    if not urls:
        urls = _extract_urls_from_stdin_json()
    if not urls:
        print(
            "No URL provided. Pass URLs by CLI args or stdin JSON "
            '(e.g. {"url":"https://example.com"} or {"urls":[...]}).',
            file=sys.stderr,
        )
        return 2

    out_dir = pathlib.Path(args.out)
    ensure_dir(out_dir)

    rows: list[dict] = []
    for url in urls:
        if not urllib.parse.urlparse(url).scheme:
            rows.append(
                {
                    "url": url,
                    "ok": False,
                    "status_code": None,
                    "content_type": "",
                    "title": "",
                    "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "dir": "",
                    "error": "Invalid URL: missing scheme (http/https).",
                }
            )
            continue
        rows.append(store_one(url, out_dir))

    append_index(out_dir / "index.jsonl", rows)

    print(json.dumps({"output_dir": str(out_dir.as_posix()), "results": rows}, ensure_ascii=False, indent=2))
    return 0 if all(r.get("ok") for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
