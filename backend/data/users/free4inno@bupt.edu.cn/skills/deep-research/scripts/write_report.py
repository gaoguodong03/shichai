#!/usr/bin/env python3
"""深度研究报告输出脚本（CLI-only）。

用法：
  python write_report.py --title "报告标题" --content_md "# 报告全文 Markdown"
"""
import argparse
import re


def slug(s: str, max_len: int = 40) -> str:
    """简单 slug：保留中文、英文、数字，空格与非法字符替换为 -，截断长度。"""
    s = (s or "").strip()
    s = re.sub(r"[^\w\s一-鿿\-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:max_len] if s else "report"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render deep-research report output payload.",
        epilog="CLI-only: use --title and --content_md; stdin JSON is not supported.",
    )
    parser.add_argument("--title", default="深度研究报告", help="Report title")
    parser.add_argument("--content_md", required=True, help="Full markdown body")
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    title = (args.title or "深度研究报告").strip()
    content_md = (args.content_md or "").strip()

    suggested_name = slug(title) or "report"
    suggested_path = f"reports/深度研究-{suggested_name}.md"

    print(f"SUGGESTED_PATH: {suggested_path}")
    print("CONTENT:")
    print(content_md)


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
