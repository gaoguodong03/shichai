# Skill 契约测试索引

本文把 `docs/skills/skill-standard.md` 和 `docs/skills/sandbox-tool-interface.md` 的核心契约映射到当前代码与测试。它用于补齐 `SKILL-01` 的测试追踪缺口，不替代契约正文。

## 覆盖矩阵

| 文档章节 | 契约要求 | 代码锚点 | 测试锚点 | 验证命令 |
|----------|----------|----------|----------|----------|
| `skill-standard.md §1` | Skill 必须以目录为能力边界，`SKILL.md` 是唯一必需入口；工作产物进入会话工作区，不写回 Skill 目录。 | `backend/app/tools/run_skill_script.py`、`backend/app/agent/tools_for_skill.py` | `backend/tests/test_file_ref_and_gateway.py` | `rtk conda run -n st49 pytest backend/tests/test_file_ref_and_gateway.py -q` |
| `skill-standard.md §2` | `allowed-tools` 只保留 `mcp`、`http_api`、`python`；不兼容旧 `http-api`、`api`、`workspace`、`skill_script` 或通用 `call_api` 声明。 | `backend/app/api/settings_skill_frontmatter.py`、`backend/app/api/settings_skill_store.py`、`backend/app/core/settings_bundle_import.py` | `backend/tests/test_skill_mcp_and_script_requirements.py` | `rtk conda run -n st49 pytest backend/tests/test_skill_mcp_and_script_requirements.py -q` |
| `skill-standard.md §3.2` | 工作区读写工具使用当前会话工作区相对路径；需要保存真实产物时必须调用工作区工具，不能只在自然语言中声称保存。 | `backend/app/agent/skill_execution_prompt_rules.py`、`backend/app/agent/builtin_workspace_tools.py`、`backend/app/tools/read_file.py`、`backend/app/tools/write_workspace_file.py` | `backend/tests/test_file_ref_and_gateway.py`、`backend/tests/test_platform_prompts.py` | `rtk conda run -n st49 pytest backend/tests/test_file_ref_and_gateway.py backend/tests/test_platform_prompts.py -q` |
| `skill-standard.md §4.1` | 脚本型 Skill 只通过 `run_skill_script_<directory_name>` 调用；拒绝通用 `run_skill_script` 和模型自造的脚本工具名。 | `backend/app/agent/skill_agent_runtime.py`、`backend/app/agent/skill_tool_naming.py` | `backend/tests/test_skill_agent_tool_resolution.py` | `rtk conda run -n st49 pytest backend/tests/test_skill_agent_tool_resolution.py -q` |
| `skill-standard.md §4.2` | 脚本工具入口和 LLM 可见 schema 只来自 `scripts/manifest.json` 的 `entry`、`description`、`args`；不注入无 manifest 脚本工具，不接受 `script_path` 或 `cli_args`。 | `backend/app/tools/skill_script_manifest.py`、`backend/app/tools/run_skill_script.py`、`backend/app/agent/tools_for_skill.py` | `backend/tests/test_file_ref_and_gateway.py` | `rtk conda run -n st49 pytest backend/tests/test_file_ref_and_gateway.py -q` |
| `sandbox-tool-interface.md 总体规则` | LLM 可见工具字段统一为 `name`、`description`、`input_schema`；`source`、`provider`、`provider_tool` 只用于内部执行和 trace，不进入业务分支契约。 | `backend/app/agent/tool_spec.py`、`backend/app/agent/tools_for_skill.py`、`backend/app/agent/skill_agent_runtime.py` | `backend/tests/test_file_ref_and_gateway.py`、`backend/tests/test_skill_agent_tool_resolution.py` | `rtk conda run -n st49 pytest backend/tests/test_file_ref_and_gateway.py backend/tests/test_skill_agent_tool_resolution.py -q` |
| `sandbox-tool-interface.md 技能脚本工具` | 当前 Skill 有标准 manifest 时才注入本轮 `run_skill_script_<directory_name>`；脚本 stdout 只把标准结果摘要暴露给 LLM，不暴露 stderr、returncode 或沙箱 trace。 | `backend/app/agent/tools_for_skill.py`、`backend/app/agent/skill_agent_runtime.py`、`backend/app/tools/run_skill_script.py` | `backend/tests/test_skill_agent_tool_resolution.py`、`backend/tests/test_file_ref_and_gateway.py` | `rtk conda run -n st49 pytest backend/tests/test_skill_agent_tool_resolution.py backend/tests/test_file_ref_and_gateway.py -q` |
| `sandbox-tool-interface.md 保存型 HTTP API 工具` | 保存型 HTTP API 只按当前 Skill 的 `allowed-tools.http_api` 注入；通用 `call_api` 不作为 LLM 可见工具。 | `backend/app/agent/tools_for_skill.py`、`backend/app/tools/http_api_tool.py`、`backend/app/tools/call_api.py` | `backend/tests/test_file_ref_and_gateway.py`、`backend/tests/test_platform_prompts.py` | `rtk conda run -n st49 pytest backend/tests/test_file_ref_and_gateway.py backend/tests/test_platform_prompts.py -q` |
| `sandbox-tool-interface.md MCP 工具` | MCP 工具只按当前 Skill 的 `allowed-tools.mcp` 注入；文件系统类 MCP 中与内置工作区工具重复的读取能力不得绕过工作区边界。 | `backend/app/agent/tools_for_skill.py`、`backend/app/mcp/manager.py` | `backend/tests/test_file_ref_and_gateway.py`、`backend/tests/test_skill_mcp_and_script_requirements.py` | `rtk conda run -n st49 pytest backend/tests/test_file_ref_and_gateway.py backend/tests/test_skill_mcp_and_script_requirements.py -q` |

## 维护规则

1. 修改 `allowed-tools`、脚本 manifest、MCP/HTTP API 注入或工作区工具边界时，必须同步更新本索引。
2. 新增 Skill 工具入口前，先补拒绝旧入口或越权入口的测试。
3. 本索引只记录正式契约覆盖，不记录一次性验收、手工截图或真实用户数据。
