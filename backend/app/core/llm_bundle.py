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
        for key in list(copied):
            if key in {"api_key", "api_key_env", "api_key_set", "label"}:
                copied.pop(key, None)
            elif key.startswith("api_key_") and key.endswith("ref"):
                copied.pop(key, None)
    return copied if isinstance(copied, dict) else {}


def provider_for_settings_import(provider: Dict[str, Any]) -> Dict[str, Any]:
    """Drop response-only fields before persisting an imported provider."""
    copied = sanitize_llm_provider_for_bundle(provider)
    copied.pop("api_key_set", None)
    return copied


def _model_name(llm_name: str, provider: Dict[str, Any]) -> str:
    return str(llm_name or "").strip()


def build_llm_bundle_zip_bytes(llm_name: str, provider: Dict[str, Any], *, default_llm: str = "") -> bytes:
    clean = sanitize_llm_provider_for_bundle(provider)
    name = _model_name(llm_name, clean)
    manifest = {
        "bundle_version": LLM_BUNDLE_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "name": name,
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
    llm_name = str(manifest.get("name") or "").strip()
    provider = manifest.get("provider")
    if not llm_name:
        raise ValueError("missing_llm_name")
    if not isinstance(provider, dict):
        raise ValueError("missing_provider_in_manifest")
    return manifest, llm_name, sanitize_llm_provider_for_bundle(provider)
