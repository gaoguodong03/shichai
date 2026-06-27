"""模型配置包（ZIP）：llm_bundle.json。"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

LLM_BUNDLE_VERSION = 1
LLM_MANIFEST_NAME = "llm_bundle.json"


def sanitize_llm_provider_for_bundle(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Return an export-safe LLM provider row without secrets or key binding metadata."""
    copied = json.loads(json.dumps(provider, ensure_ascii=False))
    if isinstance(copied, dict):
        copied.pop("api_key", None)
        copied.pop("api_key_env", None)
        copied.pop("api_key_ref", None)
    return copied if isinstance(copied, dict) else {}


def provider_for_settings_import(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Drop response-only fields before persisting an imported provider."""
    copied = sanitize_llm_provider_for_bundle(provider)
    copied.pop("api_key_set", None)
    return copied


def build_llm_bundle_zip_bytes(provider_id: str, provider: Dict[str, Any], *, default_llm: str = "") -> bytes:
    clean = sanitize_llm_provider_for_bundle(provider)
    manifest = {
        "bundle_version": LLM_BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "provider_id": str(provider_id or "").strip(),
        "default_llm": str(default_llm or "").strip(),
        "provider": clean,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(LLM_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


def read_llm_bundle_manifest(bundle_dir: Path) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    path = bundle_dir / LLM_MANIFEST_NAME
    if not path.is_file():
        raise ValueError("missing_llm_bundle_json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    provider_id = str(manifest.get("provider_id") or "").strip()
    provider = manifest.get("provider")
    if not provider_id:
        raise ValueError("missing_provider_id")
    if not isinstance(provider, dict):
        raise ValueError("missing_provider_in_manifest")
    return manifest, provider_id, sanitize_llm_provider_for_bundle(provider)
