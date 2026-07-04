"""Environment, network, and image policy helpers for sandbox service."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from app.agent.sandbox_image_policy import (
    SANDBOX_VARIANT_PLAYWRIGHT,
    image_for_variant,
    read_sandbox_variant,
    sandbox_settings_path,
)
from app.agent.sandbox_requirements_runtime import requirements_imply_playwright
from app.core.user_context import get_user_context_for

logger = logging.getLogger(__name__)


def env_truthy(name: str, default: str = "0") -> bool:
    val = (os.getenv(name) or default).strip().lower()
    return val in {"1", "true", "yes", "on", "enabled"}


def env_csv(name: str) -> List[str]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return []
    parts = []
    for x in raw.split(","):
        s = x.strip()
        if s:
            parts.append(s)
    return list(dict.fromkeys(parts))


def sandbox_default_environment() -> Dict[str, str]:
    browsers_path = (os.getenv("PLAYWRIGHT_BROWSERS_PATH") or "/ms-playwright").strip()
    env: Dict[str, str] = {}
    if browsers_path:
        env["PLAYWRIGHT_BROWSERS_PATH"] = browsers_path
    return env


def env_float(name: str) -> Optional[float]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        logger.warning("sandbox_env_invalid_float name=%s value=%s", name, raw)
        return None
    if value <= 0:
        logger.warning("sandbox_env_non_positive_float name=%s value=%s", name, raw)
        return None
    return value


def env_int(name: str) -> Optional[int]:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("sandbox_env_invalid_int name=%s value=%s", name, raw)
        return None
    if value <= 0:
        logger.warning("sandbox_env_non_positive_int name=%s value=%s", name, raw)
        return None
    return value


def network_allowed_for_tool(tool_name: str) -> bool:
    name = (tool_name or "").strip()
    allowlist = env_csv("SANDBOX_NETWORK_TOOL_ALLOWLIST")
    allow_global = env_truthy("SANDBOX_ALLOW_NETWORK", default="0")
    if allowlist:
        if "*" in allowlist:
            return True
        if name in allowlist:
            return True
        for item in allowlist:
            if item.endswith("*") and name.startswith(item[:-1]):
                return True
        if name.startswith("run_skill_script_") and "run_skill_script" in allowlist:
            return True
        return False
    return bool(allow_global)


def sandbox_image_for_user(user_id: str) -> tuple[str, str]:
    uid = (user_id or "").strip()
    settings_exists = False
    req_implies_playwright = False
    settings_path_text = ""
    if uid:
        try:
            user_ctx = get_user_context_for(uid)
            sandbox_dir: Path = user_ctx.settings_dir / "sandbox"
            settings_path = sandbox_settings_path(sandbox_dir)
            settings_path_text = str(settings_path)
            settings_exists = settings_path.is_file()
            variant = read_sandbox_variant(sandbox_dir)
            req_implies_playwright = requirements_imply_playwright(sandbox_dir / "requirements.txt")
            if not settings_exists and req_implies_playwright:
                variant = SANDBOX_VARIANT_PLAYWRIGHT
        except Exception as exc:
            logger.warning(
                "st49_sandbox_image_policy_failed code=image_policy_read_failed user_id=%s settings_path=%s err=%s",
                uid,
                settings_path_text,
                str(exc)[:500],
            )
            variant = "standard"
    else:
        variant = "standard"
    image_ref = image_for_variant(variant)
    logger.info(
        "st49_sandbox_image_policy code=image_policy_resolved user_id=%s variant=%s image_ref=%s settings_exists=%s requirements_imply_playwright=%s env_standard_set=%s env_playwright_set=%s",
        uid or "<empty>",
        variant,
        image_ref,
        settings_exists,
        req_implies_playwright,
        bool((os.getenv("SANDBOX_STANDARD_IMAGE") or "").strip()),
        bool((os.getenv("SANDBOX_PLAYWRIGHT_IMAGE") or "").strip()),
    )
    return variant, image_ref
