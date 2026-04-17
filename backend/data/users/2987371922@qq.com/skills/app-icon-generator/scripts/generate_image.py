#!/usr/bin/env python3
"""应用图标图片生成 CLI。

CLI-only usage:
  python generate_image.py --description "图标描述" [--pic_size 1024x1024]
"""
import argparse
import base64
import os
import sys
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


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate one image and save it into workspace.",
        epilog="CLI-only: --description is required; stdin JSON is not supported.",
    )
    parser.add_argument("--description", required=True, help="Image prompt/description")
    parser.add_argument("--pic_size", default="1024x1024", help="Image size, default 1024x1024")
    return parser.parse_args(argv)


def main(argv: list[str]) -> None:
    args = parse_args(argv)
    description = (args.description or "").strip()
    pic_size = (args.pic_size or "1024x1024").strip()
    result = generate_image(description=description, pic_size=pic_size)
    print(_save_data_url_to_workspace(result))


if __name__ == "__main__":
    main(sys.argv[1:])
