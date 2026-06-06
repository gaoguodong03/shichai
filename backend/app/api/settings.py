"""Compatibility entrypoint for Skill settings routes."""
from __future__ import annotations

from app.api.settings_app import load_app_settings, normalize_host_profile, save_app_settings
from app.api.settings_mcp import load_mcp_config, save_mcp_config
from app.api.settings_secrets import (
    load_api_secret_values,
    load_api_secret_values_for_user,
    load_api_secrets_raw,
    save_api_secrets_raw,
)
from app.api.settings_skill_frontmatter import (
    ALLOWED_TOOLS_FM_KEY,
    AUTO_TOOLS_FM_KEY,
    SkillCreate,
    SkillUpdate,
    mcp_ids_from_frontmatter as _mcp_ids_from_frontmatter,
    normalized_allowed_tools_dict as _normalized_allowed_tools_dict,
    python_doc_from_allowed_tools as _python_requirements_doc_from_frontmatter,
    sanitize_skill_frontmatter_for_write as _sanitize_skill_frontmatter_for_write,
)
from app.api.settings_skill_store import (
    get_mcp_servers_for_skill,
    load_skills_config,
    validate_skill_mcp_server_ids as _validate_skill_mcp_server_ids,
)
from app.api.settings_skill_parts import PartDirCreate, PartFileCreate, PartFileUpdate
from app.api.settings_skills import (
    _build_skill_zip_bytes,
    _content_disposition_attachment,
    _invalidate_mcp_runtime_after_config_change,
    _import_expert_from_bundle_bytes,
    _import_skill_from_bundle_bytes,
    _merge_imported_skill_requirements_and_prewarm,
    _merge_sandbox_requirements_lines,
    _python_requirements_from_skill_dir,
    router,
)

_python_doc_from_allowed_tools = _python_requirements_doc_from_frontmatter
