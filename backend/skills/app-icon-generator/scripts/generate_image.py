#!/usr/bin/env python3
"""应用图标图片生成 CLI。供 run_skill_script 调用，使用 Jeniya Gemini 图像生成接口（POST）。

stdin：JSON 字符串，如 {"description": "图标描述...", "pic_size": "1024x1024"}，pic_size 可选默认 1024x1024。
stdout：图片 data URL 或错误信息。环境变量优先 JENIYA_API_KEY（兼容 CHATANYWHERE_IMAGE_API_KEY 回退）。
"""
import json
import os
import sys
import base64
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

# 允许从 backend 导入 app.tools
_backend = Path(__file__).resolve().parents[3]
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.tools.chatanywhere_image_cli_lib import generate_image


def _ext_from_mime(mime_type: str) -> str:
    mt = (mime_type or "").lower().strip()
    if mt == "image/png":
        return "png"
    if mt == "image/webp":
        return "webp"
    return "jpg"


def _save_data_url_to_workspace(result: str) -> str:
    """若结果是 data URL 图片，则写入当前会话工作区并返回可读文本。"""
    text = (result or "").strip()
    if not text.startswith("data:image/") or ";base64," not in text:
        return result

    header, b64_data = text.split(";base64,", 1)
    mime_type = header.replace("data:", "", 1).strip() or "image/jpeg"
    ext = _ext_from_mime(mime_type)
    image_bytes = base64.b64decode(b64_data)

    workspace_root = Path(os.environ.get("SKILL_WORKSPACE_ROOT") or os.getcwd()).resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    output_dir = workspace_root / "generated_images"
    output_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"image-{ts}-{uuid4().hex[:8]}.{ext}"
    output_path = output_dir / filename
    output_path.write_bytes(image_bytes)

    rel_path = output_path.relative_to(workspace_root).as_posix()
    workspace_id = (os.environ.get("SKILL_WORKSPACE_ID") or "").strip()
    download_url = f"/api/workspaces/{workspace_id}/files/download?path={rel_path}" if workspace_id else ""
    lines = [
        f"已生成图片并写入工作区文件：{rel_path}",
        f"MIME 类型：{mime_type}",
    ]
    if download_url:
        lines.append(f"下载链接：{download_url}")
    return "\n".join(lines)


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
    print(_save_data_url_to_workspace(result))


if __name__ == "__main__":
    main()
