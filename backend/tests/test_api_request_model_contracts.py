import pytest
from pydantic import ValidationError

from app.api.agents import AgentCreate, AgentUpdate
from app.api.auth import ChangeAccountBody, ChangePasswordBody, LoginBody, RegisterBody
from app.api.files import DirCreateBody, FileContentBody, FileCreateBody, FileRenameBody
from app.api.sandbox_settings import (
    SandboxRequirementsBody,
    SandboxRequirementsMergeBody,
    SandboxRequirementsStatusBody,
    SandboxSettingsBody,
)
from app.api.settings_app import AppSettingsBody, HostProfileBody
from app.api.settings_env_vars import EnvVarCreate, EnvVarUpdate
from app.api.settings_mcp import MCPServerCreate, MCPServerUpdate, MCPToolCallBody, MCPTransport, MCPSandboxCallBody
from app.api.settings_presets import SessionPresetItem, SessionPresetsBody
from app.api.settings_skill_frontmatter import SkillCreate, SkillUpdate
from app.api.settings_skill_parts import PartDirCreate, PartFileCreate, PartFileUpdate


@pytest.mark.parametrize(
    "model,payload",
    [
        (AgentCreate, {"name": "写作专家"}),
        (AgentUpdate, {"description": "负责写作"}),
        (LoginBody, {"username": "13800138000", "password": "pw"}),
        (RegisterBody, {"username": "13800138000", "password": "pw"}),
        (ChangeAccountBody, {"new_username": "13800138001", "current_password": "pw"}),
        (ChangePasswordBody, {"current_password": "old", "new_password": "new"}),
        (DirCreateBody, {"dirname": "docs"}),
        (FileContentBody, {"content": "hello"}),
        (FileCreateBody, {"filename": "a.md"}),
        (FileRenameBody, {"new_name": "b.md"}),
        (SandboxRequirementsBody, {"content": "requests"}),
        (SandboxSettingsBody, {"image_variant": "standard"}),
        (SandboxRequirementsMergeBody, {"requirements": ["requests"]}),
        (SandboxRequirementsStatusBody, {"requirements": ["requests"]}),
        (AppSettingsBody, {"default_llm": "qwen"}),
        (HostProfileBody, {"name": "四九"}),
        (MCPTransport, {"type": "stdio"}),
        (MCPServerCreate, {"name": "tool"}),
        (MCPServerUpdate, {"description": "desc"}),
        (MCPToolCallBody, {"arguments": {"q": "x"}}),
        (MCPSandboxCallBody, {"arguments": {"q": "x"}}),
        (SessionPresetItem, {"name": "写作", "agent_names": ["写作专家"]}),
        (SessionPresetsBody, {"presets": [{"name": "写作", "agent_names": ["写作专家"]}]}),
        (EnvVarCreate, {"name": "QWEN_API_KEY", "value": "sk"}),
        (EnvVarUpdate, {"label": "Qwen"}),
        (SkillCreate, {"name": "写作 Skill"}),
        (SkillUpdate, {"description": "desc"}),
        (PartFileCreate, {"path": "references/a.md"}),
        (PartFileUpdate, {"content": "body"}),
        (PartDirCreate, {"path": "references"}),
    ],
)
def test_api_request_models_reject_top_level_extra_fields(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate({**payload, "legacy_control": "forbidden"})


def test_mcp_request_allows_nested_tool_config_but_rejects_unknown_top_level():
    parsed = MCPServerCreate.model_validate(
        {
            "name": "search",
            "config": {"vendor_specific": {"timeout": 30}},
            "metadata": {"owner": "team"},
        }
    )

    assert parsed.config == {"vendor_specific": {"timeout": 30}}
    assert parsed.metadata == {"owner": "team"}
