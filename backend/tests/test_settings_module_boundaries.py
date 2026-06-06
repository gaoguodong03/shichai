"""Settings API module boundaries."""
from __future__ import annotations

import inspect
from pathlib import Path

from fastapi import APIRouter

from app.api import settings


def test_settings_module_is_thin_compatibility_entrypoint():
    path = Path(inspect.getsourcefile(settings) or "")
    assert path.name == "settings.py"
    source = path.read_text(encoding="utf-8")
    source_lines = source.splitlines()
    assert len(source_lines) <= 120
    assert "_sync_test_overrides" not in source
    assert "def _get_skills_dir" not in source
    assert "def _get_sandbox_requirements_path" not in source


def test_settings_module_keeps_public_compatibility_exports():
    assert isinstance(settings.router, APIRouter)
    for name in (
        "load_app_settings",
        "save_app_settings",
        "normalize_host_profile",
        "load_api_secret_values",
        "load_api_secret_values_for_user",
        "load_skills_config",
        "get_mcp_servers_for_skill",
        "_merge_imported_skill_requirements_and_prewarm",
        "_content_disposition_attachment",
    ):
        assert hasattr(settings, name), name
