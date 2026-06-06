# P0 完成审计

审计日期：2026-06-06

本文对照 [用户需求文档](../requirements/user-requirements.md)、[工程任务拆分](implementation-task-breakdown.md)、[测试用例目录](../testing/test-case-catalog.md) 和 [上线前测试手册](../testing/pre-release-testing.md)，确认 UR-01 到 UR-08 的 P0 任务已有代码、测试和文档入口。

## 审计结论

| 需求 | P0 任务 | 代码入口 | 测试入口 | 文档入口 | 结论 |
|------|---------|----------|----------|----------|------|
| UR-01 账号与用户隔离 | T-UR01-01、T-UR01-02 | `backend/app/api/auth.py`、`backend/app/api/files.py`、`backend/app/core/user_context.py` | `backend/tests/test_auth_sqlite.py`、`backend/tests/test_user_resource_paths.py`、`backend/tests/test_workspace_files.py`、`frontend/e2e/auth.spec.ts` | `docs/requirements/user-requirements.md`、`docs/testing/test-case-catalog.md` | 已完成，状态为 `verify` |
| UR-02 工作区与统一会话 | T-UR02-01、T-UR02-02 | `backend/app/api/sessions.py`、`frontend/src/features/workspace/` | `backend/tests/test_sessions_api.py`、`backend/tests/test_group_chat_stream_protocol.py`、`frontend/e2e/workspace.spec.ts` | `docs/requirements/user-requirements.md`、`docs/testing/pre-release-testing.md` | 已完成，状态为 `verify` |
| UR-03 主持人与专家协作 | T-UR03-01 | `backend/app/core/scene_scheduler.py`、`backend/app/agent/group_host_decision.py`、`backend/app/agent/leader_scheduler.py` | `backend/tests/test_scene_scheduler.py`、`backend/tests/test_group_host_decision.py`、`backend/tests/test_host_takeover.py` | `docs/requirements/user-requirements.md`、`docs/testing/test-case-catalog.md` | 已完成，状态为 `verify` |
| UR-04 资源中心 | T-UR04-01 | `backend/app/api/dha.py`、`backend/app/api/settings.py`、`backend/app/api/settings_mcp.py`、`frontend/src/features/resources/` | `backend/tests/test_dha_api.py`、`backend/tests/test_llm_config.py`、`backend/tests/test_frontend_business_flows.py`、`frontend/e2e/resources-scenario-expert.spec.ts`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` | `docs/requirements/user-requirements.md`、`docs/testing/test-case-catalog.md` | 已审计通过，状态为 `verify` |
| UR-05 Skill 与脚本执行 | T-UR05-01 | `backend/app/skills/loader.py`、`backend/app/agent/skill_session_contract.py`、`frontend/src/features/resources/SkillDetailView.vue` | `backend/tests/test_skill_mcp_and_script_requirements.py`、`backend/tests/test_skill_agent_tool_resolution.py`、`backend/tests/test_group_chat_skill_script_cli_flow.py` | `docs/skills/skill-standard.md`、`docs/testing/test-case-catalog.md` | 已完成，状态为 `verify` |
| UR-06 MCP 工具能力 | T-UR06-01 | `backend/app/mcp/manager.py`、`backend/app/mcp/tool_arg_normalizers.py`、`backend/app/agent/tools_for_skill.py` | `backend/tests/test_skill_agent_tool_resolution.py`、`backend/tests/test_file_ref_and_gateway.py`、`frontend/e2e/resources-skill-mcp-llm.spec.ts` | `docs/requirements/user-requirements.md`、`docs/testing/test-case-catalog.md` | 已完成，状态为 `verify` |
| UR-07 沙箱运行环境 | T-UR07-01 | `backend/app/api/sandbox_settings.py`、`backend/app/agent/sandbox_service.py`、`backend/app/agent/sandbox_policy_runtime.py` | `backend/tests/test_sandbox_service.py`、`backend/tests/test_sandbox_policy_runtime.py`、`backend/tests/test_sandbox_requirements_runtime.py` | `docs/testing/pre-release-testing.md`、`docs/operations/single-user-single-sandbox.md` | 已完成，状态为 `verify` |
| UR-08 工作区文件管理 | T-UR08-01 | `backend/app/api/files.py`、`frontend/src/features/workspace/FileDetailView.vue`、`backend/app/tools/filesystem_session_wrapper.py` | `backend/tests/test_workspace_files.py`、`backend/tests/test_file_ref_and_gateway.py`、`frontend/e2e/workspace.spec.ts` | `docs/testing/test-case-catalog.md`、`docs/testing/pre-release-testing.md` | 已完成，状态为 `verify` |

## 本轮补强提交

- `6f91b3c`：阻止工作区 ID 路径逃逸，补齐用户资源路径隔离回归。
- `f05e543`：显示会话轮次上限暂停提示，补齐工作区状态提示。
- `518bc01`：补强场景调度边界回归。
- `c2aafd7`：补强 Skill 加载诊断。
- `2bcde95`：补强 MCP 参数错误诊断。
- `67f0628`：支持沙箱网络工具前缀白名单。
- `fcd600a`：修复上线验收 UI 流程中的登录退出和文件详情编辑态操作区。

## 审计验证命令

```bash
rtk conda run --no-capture-output -n st49 python -m pytest backend/tests/test_dha_api.py backend/tests/test_llm_config.py backend/tests/test_frontend_business_flows.py -q
rtk proxy npm --prefix frontend run test:e2e:full -- e2e/resources-scenario-expert.spec.ts e2e/resources-skill-mcp-llm.spec.ts
rtk ./scripts/test-layer1.sh
```

当前 P0 审计通过后，下一步才进入 P1 上线验收项：T-UR09-01、T-UR10-01、T-UR11-01。
