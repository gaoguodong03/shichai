#!/usr/bin/env python3
"""深度研究报告输出脚本。

从 stdin 读取 JSON：{"title": "报告标题", "content_md": "# 报告全文 Markdown"}，
输出建议保存路径与完整正文，供 Agent 呈现给用户或写入工作区。

用法（run_skill_script）：
  script_path=write_report.py
  input_json={"title": "某主题研究报告", "content_md": "# 摘要\\n..."}
"""
import json
import re
import sys


def slug(s: str, max_len: int = 40) -> str:
    """简单 slug：保留中文、英文、数字，空格与非法字符替换为 -，截断长度。"""
    s = (s or "").strip()
    s = re.sub(r"[^\w\s\u4e00-\u9fff\-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s[:max_len] if s else "report"


def main() -> None:
    raw = sys.stdin.read()
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        print("错误：input_json 必须是合法 JSON，包含 title 与 content_md。")
        sys.exit(1)

    title = (data.get("title") or "深度研究报告").strip()
    content_md = (data.get("content_md") or "").strip()
    if not content_md:
        print("错误：content_md 不能为空。")
        sys.exit(1)

    suggested_name = slug(title) or "report"
    suggested_path = f"reports/深度研究-{suggested_name}.md"

    print(f"SUGGESTED_PATH: {suggested_path}")
    print("CONTENT:")
    print(content_md)


if __name__ == "__main__":
    main()
