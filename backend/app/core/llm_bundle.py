"""模型配置资源包（ZIP）：bundle.json + resources/models。"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Tuple

from app.core.scenario_bundle import MANIFEST_NAME, MODELS_DIR, _resource_dir_name, _read_resource_rows

LLM_MANIFEST_NAME = MANIFEST_NAME


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
    copied.pop("name", None)
    copied.pop("default_llm", None)
    return copied


def _model_name(llm_name: str, provider: Dict[str, Any]) -> str:
    return str(llm_name or "").strip()


def build_llm_bundle_zip_bytes(llm_name: str, provider: Dict[str, Any], *, default_llm: str = "") -> bytes:
    clean = sanitize_llm_provider_for_bundle(provider)
    name = _model_name(llm_name, clean)
    model_row = {"name": name, **clean}
    if default_llm:
        model_row["default_llm"] = str(default_llm or "").strip()
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "bundle_type": "model",
        "root_resources": [{"type": "model", "name": name}],
        "resource_counts": {
            "scenarios": 0,
            "agents": 0,
            "skills": 0,
            "tools": 0,
            "models": 1,
        },
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(LLM_MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        model_dir = _resource_dir_name(name, "model")
        zf.writestr(f"{MODELS_DIR}/{model_dir}/model.json", json.dumps(model_row, ensure_ascii=False, indent=2) + "\n")
    return buf.getvalue()


def read_llm_bundle_manifest(bundle_dir: Path) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
    path = bundle_dir / LLM_MANIFEST_NAME
    if not path.is_file():
        raise ValueError("missing_bundle_json")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("invalid_manifest")
    if manifest.get("bundle_type") != "model":
        raise ValueError("invalid_bundle_type")
    model_rows = _read_resource_rows(bundle_dir / MODELS_DIR, "model.json")
    if not model_rows:
        raise ValueError("missing_model_resource")
    provider = sanitize_llm_provider_for_bundle(model_rows[0])
    llm_name = str(provider.get("name") or "").strip()
    if not llm_name:
        raise ValueError("missing_llm_name")
    if "default_llm" in provider:
        manifest = {**manifest, "default_llm": str(provider.get("default_llm") or "")}
    return manifest, llm_name, provider
