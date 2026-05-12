"""User-selectable sandbox image policy."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List


SANDBOX_VARIANT_STANDARD = "standard"
SANDBOX_VARIANT_PLAYWRIGHT = "playwright"
SANDBOX_VARIANTS = {SANDBOX_VARIANT_STANDARD, SANDBOX_VARIANT_PLAYWRIGHT}

DEFAULT_STANDARD_IMAGE = "crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.12.1-standard"
DEFAULT_PLAYWRIGHT_IMAGE = "crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.12.1-playwright"


def default_standard_image() -> str:
    return DEFAULT_STANDARD_IMAGE


def default_playwright_image() -> str:
    return DEFAULT_PLAYWRIGHT_IMAGE


def configured_sandbox_images() -> Dict[str, str]:
    standard = (
        os.getenv("SANDBOX_STANDARD_IMAGE")
        or os.getenv("SANDBOX_BASE_IMAGE")
        or default_standard_image()
    ).strip()
    playwright = (
        os.getenv("SANDBOX_PLAYWRIGHT_IMAGE")
        or os.getenv("SANDBOX_BASE_IMAGE_PLAYWRIGHT")
        or default_playwright_image()
    ).strip()
    return {
        SANDBOX_VARIANT_STANDARD: standard,
        SANDBOX_VARIANT_PLAYWRIGHT: playwright,
    }


def normalize_sandbox_variant(value: Any) -> str:
    variant = str(value or "").strip().lower()
    if variant in SANDBOX_VARIANTS:
        return variant
    return SANDBOX_VARIANT_STANDARD


def sandbox_settings_path(config_dir: Path) -> Path:
    return (config_dir / "sandbox" / "settings.json").resolve()


def read_sandbox_variant(config_dir: Path) -> str:
    path = sandbox_settings_path(config_dir)
    try:
        raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return normalize_sandbox_variant(raw.get("image_variant"))


def write_sandbox_variant(config_dir: Path, variant: str) -> str:
    normalized = normalize_sandbox_variant(variant)
    path = sandbox_settings_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"image_variant": normalized}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return normalized


def image_for_variant(variant: str) -> str:
    images = configured_sandbox_images()
    return images.get(normalize_sandbox_variant(variant)) or images[SANDBOX_VARIANT_STANDARD]


def sandbox_image_options() -> List[Dict[str, str]]:
    images = configured_sandbox_images()
    return [
        {
            "value": SANDBOX_VARIANT_STANDARD,
            "label": "普通版",
            "description": "体积更小，适合不需要浏览器自动化的技能。",
            "image": images[SANDBOX_VARIANT_STANDARD],
        },
        {
            "value": SANDBOX_VARIANT_PLAYWRIGHT,
            "label": "Playwright 版",
            "description": "包含浏览器运行时，适合网页抓取、渲染和自动化技能。",
            "image": images[SANDBOX_VARIANT_PLAYWRIGHT],
        },
    ]
