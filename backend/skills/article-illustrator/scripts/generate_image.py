#!/usr/bin/env python3
"""文章配图 / 通用图片生成 CLI。供 run_skill_script 调用，与 volces-icon MCP 使用相同 API 与 KEY。

stdin：JSON 字符串，如 {"description": "配图描述...", "pic_size": "1024x1024"}，pic_size 可选默认 1024x1024。
stdout：图片 URL 或错误信息。环境变量 VOLCES_IMAGE_API_KEY 与 MCP 一致（见 backend/.env）。
"""
import json
import os
import sys
from pathlib import Path

# 测试用：直接写死 Key，便于本地跑通（正式环境请改回用 .env）
os.environ.setdefault("VOLCES_IMAGE_API_KEY", "Bearer 2d4ac581-9179-4c70-944b-14a0549d927a")

_backend = Path(__file__).resolve().parents[3]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.tools.volces_image_cli_lib import generate_image


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    try:
        obj = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        print(f"错误：input_json 不是合法 JSON: {e}", file=sys.stderr)
        sys.exit(1)
    description = (obj.get("description") or "").strip()
    if not description:
        print("错误：description 必填。input_json 示例: {\"description\": \"你的提示词\", \"pic_size\": \"1024x1024\"}", file=sys.stderr)
        sys.exit(1)
    pic_size = (obj.get("pic_size") or "1024x1024").strip()
    result = generate_image(description=description, pic_size=pic_size)
    print(result)


if __name__ == "__main__":
    main()
