#!/usr/bin/env python3
"""Generate slide images from deck.json with style_guide."""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx

_DEFAULT_BASE = "http://jeniya.top"
_DEFAULT_MODEL = "gemini-3.1-flash-image-preview"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-").lower()
    return s or "slide"


def _api_url() -> str:
    base = (os.environ.get("JENIYA_IMAGE_BASE_URL") or _DEFAULT_BASE).rstrip("/")
    model = (os.environ.get("JENIYA_IMAGE_MODEL") or _DEFAULT_MODEL).strip()
    return f"{base}/v1beta/models/{model}:generateContent"


def _get_api_key() -> str:
    key = (os.environ.get("JENIYA_API_KEY") or "").strip()
    if not key:
        key = (os.environ.get("CHATANYWHERE_IMAGE_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("未配置 JENIYA_API_KEY 或 CHATANYWHERE_IMAGE_API_KEY")
    return key if key.startswith("Bearer ") else f"Bearer {key}"


def _call_image_api(description: str, pic_size: str) -> str:
    headers = {"Content-Type": "application/json", "Authorization": _get_api_key()}
    body = {
        "contents": [{"parts": [{"text": f"{description}\n\n请生成尺寸约为 {pic_size} 的图片，输出图像内容。"}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(_api_url(), json=body, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict):
        raise RuntimeError(f"响应格式异常: {data}")
    candidates = data.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeError(f"响应缺少 candidates: {data}")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData")
            if isinstance(inline, dict) and inline.get("data"):
                mime_type = inline.get("mimeType") or "image/png"
                return f"data:{mime_type};base64,{inline['data']}"
    raise RuntimeError(f"响应中未找到图片数据: {data}")


def _save_data_url_to_workspace(result: str, preferred_name: str) -> str:
    text = (result or "").strip()
    if not text.startswith("data:image/") or ";base64," not in text:
        raise RuntimeError(f"生成结果不是图片 data url: {text[:120]}")
    header, b64_data = text.split(";base64,", 1)
    mime_type = header.replace("data:", "", 1).strip() or "image/jpeg"
    ext = "png" if mime_type == "image/png" else ("webp" if mime_type == "image/webp" else "jpg")
    image_bytes = base64.b64decode(b64_data)

    workspace_root = Path(os.environ.get("SKILL_WORKSPACE_ROOT") or os.getcwd()).resolve()
    output_dir = workspace_root / "generated_images"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{preferred_name}.{ext}"
    output_path.write_bytes(image_bytes)
    return output_path.relative_to(workspace_root).as_posix()


def _load_deck(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError("deck.json 必须是对象")
    slides = raw.get("slides")
    if not isinstance(slides, list) or not slides:
        raise RuntimeError("deck.json 缺少非空 slides[]")
    return raw


def _compose_prompt(style_guide: dict[str, Any], slide: dict[str, Any]) -> str:
    palette = style_guide.get("color_palette") or []
    rules = style_guide.get("composition_rules") or []
    negatives = style_guide.get("negative_prompts") or []
    if not isinstance(palette, list):
        palette = []
    if not isinstance(rules, list):
        rules = []
    if not isinstance(negatives, list):
        negatives = []
    title = str(slide.get("title") or "").strip()
    brief = str(slide.get("image_brief") or "").strip()
    theme = str(style_guide.get("visual_theme") or "").strip()
    return (
        f"PPT slide illustration, unified style. Theme: {theme}. "
        f"Color palette: {', '.join(str(x) for x in palette)}. "
        f"Composition rules: {'; '.join(str(x) for x in rules)}. "
        f"Slide title: {title}. Visual intent: {brief}. "
        f"Negative: {'; '.join(str(x) for x in negatives)}."
    )


def _save_deck(path: Path, deck: dict[str, Any]) -> None:
    path.write_text(json.dumps(deck, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _generate_for_slide(deck: dict[str, Any], deck_path: Path, idx: int, pic_size: str) -> str:
    slides = deck["slides"]
    if idx < 1 or idx > len(slides):
        raise RuntimeError(f"slide_index 超出范围: {idx}")
    slide = slides[idx - 1]
    if not isinstance(slide, dict):
        raise RuntimeError(f"slide {idx} 数据非法")
    style = deck.get("style_guide") if isinstance(deck.get("style_guide"), dict) else {}
    prompt = _compose_prompt(style, slide)
    result = _call_image_api(description=prompt, pic_size=pic_size)
    image_path = _save_data_url_to_workspace(result, preferred_name=f"slide-{idx:02d}-{_slug(str(slide.get('title') or ''))}")
    slide["image_path"] = image_path
    _save_deck(deck_path, deck)
    return image_path


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate PPT slide images")
    parser.add_argument("--deck_json", required=True, help="Path to deck.json")
    parser.add_argument("--slide_index", type=int, help="1-based slide index")
    parser.add_argument("--batch", action="store_true", help="Generate all slides")
    parser.add_argument("--pic_size", default="1792x1024", help="Image size")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    if not args.batch and not args.slide_index:
        print("ERROR: 需指定 --slide_index 或 --batch", file=sys.stderr)
        return 1
    deck_path = Path(args.deck_json).resolve()
    try:
        deck = _load_deck(deck_path)
        outputs: list[str] = []
        if args.batch:
            for i in range(1, len(deck["slides"]) + 1):
                path = _generate_for_slide(deck, deck_path, i, args.pic_size)
                outputs.append(f"{i}:{path}")
        else:
            path = _generate_for_slide(deck, deck_path, int(args.slide_index), args.pic_size)
            outputs.append(f"{args.slide_index}:{path}")
        print("生成完成: " + ", ".join(outputs))
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
