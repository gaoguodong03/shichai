# 书童四九工程任务拆分

## 1. 文档目的

本文把 [用户需求文档](../requirements/user-requirements.md) 的 UR-01 到 UR-11 拆成可执行工程任务，用于后续排期、开发、测试和验收。任务应与 [详细设计](../architecture/detailed-design.md) 和 [测试用例目录](../testing/test-case-catalog.md) 同步维护。

任务状态说明：

| 状态 | 含义 |
|------|------|
| `ready` | 需求、设计、测试入口已明确，可以进入开发 |
| `verify` | 代码已有覆盖，后续迭代时重点做回归验证 |
| `backlog` | 有明确价值，但不阻塞当前 P0 验收 |

## 2. 当前优先级

| 优先级 | 范围 | 处理策略 |
|--------|------|----------|
| P0 | UR-01 到 UR-08 | 任何改动必须保留自动化测试或手工验收入口 |
| P1 | UR-09 到 UR-11 | 上线前必须完成冒烟验证，复杂场景可分批增强 |
| P2 | 主题、偏好、体验 polish | 不影响 P0/P1 稳定性时推进 |

P0 完成审计见：[p0-completion-audit.md](p0-completion-audit.md)。

## 3. 任务池

### T-UR01-01：认证错误语义和全局跳转复核

- 对应需求：UR-01、UR-10
- 状态：`verify`
- 修改范围：`backend/app/api/auth.py`、`frontend/src/main.ts`、`frontend/src/features/settings/AccountSecuritySettingsView.vue`
- 测试入口：`backend/tests/test_auth_sqlite.py`、`frontend/e2e/settings.spec.ts`
- 验收点：
  - 无令牌访问受保护 API 返回 401。
  - 修改密码时当前密码错误返回业务错误，不触发跳转登录。
  - 登录态刷新后保持。

### T-UR01-02：用户资源路径隔离回归

- 对应需求：UR-01、UR-04、UR-08
- 状态：`verify`
- 修改范围：`backend/app/core/user_context.py`、`backend/app/core/user_settings_paths.py`、`backend/app/core/resource_store.py`
- 测试入口：`backend/tests/test_user_resource_paths.py`、`backend/tests/test_workspace_files.py`
- 验收点：
  - 每类资源路径都从当前用户根目录派生。
  - 路径穿越和跨用户路径访问被拒绝。
  - 新增资源类型时同步用户资源目录文档。

### T-UR02-01：统一会话非流式返回主消息契约

- 对应需求：UR-02、UR-03
- 状态：`verify`
- 修改范围：`backend/app/api/sessions.py`
- 测试入口：`backend/tests/test_sessions_api.py`、`backend/tests/test_group_chat_stream_protocol.py`
- 验收点：
  - 专家被路由后，非流式 `message` 返回该专家消息。
  - 主持人补充说明不覆盖专家主结果。
  - 没有专家消息时保留现有 fallback。

### T-UR02-02：工作区刷新恢复和状态提示

- 对应需求：UR-02、UR-08
- 状态：`verify`
- 修改范围：`frontend/src/features/workspace/WorkspaceContent.vue`、`frontend/src/features/workspace/components/group-chat/GroupChatStatusBars.vue`、`backend/app/api/sessions.py`
- 测试入口：`frontend/e2e/workspace.spec.ts`、`backend/tests/test_sessions_api.py`
- 验收点：
  - 刷新后消息、成员、文件和会话状态恢复。
  - 等待用户补充、工具失败、轮次上限都有可见提示。

### T-UR03-01：普通会话和场景会话调度边界

- 对应需求：UR-03
- 状态：`verify`
- 修改范围：`backend/app/agent/leader_scheduler.py`、`backend/app/core/scene_scheduler.py`、`backend/app/agent/group_host_decision.py`
- 测试入口：`backend/tests/test_scene_scheduler.py`、`backend/tests/test_group_host_decision.py`、`backend/tests/test_host_takeover.py`
- 验收点：
  - 普通会话可推荐专家。
  - 场景会话优先使用场景内专家。
  - `@专家` 显式路由优先。

### T-UR04-01：资源中心保存后会话读取最新配置

- 对应需求：UR-04、UR-10
- 状态：`verify`
- 修改范围：`backend/app/api/agents.py`、`backend/app/api/settings_skills.py`、`backend/app/core/resource_store.py`、`frontend/src/features/resources/`
- 测试入口：`backend/tests/test_agents_api.py`、`backend/tests/test_llm_config.py`、`frontend/e2e/resources-scenario-expert.spec.ts`
- 验收点：
  - 专家、模型、Skill、MCP 修改后新会话读取最新配置。
  - 删除资源后列表同步，历史会话不崩溃。

### T-UR05-01：Skill 契约校验和依赖提示

- 对应需求：UR-05、UR-07
- 状态：`verify`
- 修改范围：`backend/app/skills/loader.py`、`backend/app/agent/skill_session_contract.py`、`frontend/src/features/resources/SkillDetailView.vue`
- 测试入口：`backend/tests/test_skill_mcp_and_script_requirements.py`、`backend/tests/test_skill_agent_tool_resolution.py`
- 验收点：
  - 缺失 `SKILL.md` 或 frontmatter 非法时提示明确。
  - requirements 缺失或沙箱版本不匹配时给出可执行建议。

### T-UR06-01：MCP 工具权限和错误诊断

- 对应需求：UR-06
- 状态：`verify`
- 修改范围：`backend/app/mcp/manager.py`、`backend/app/mcp/tool_arg_normalizers.py`、`backend/app/agent/tool_gateway.py`
- 测试入口：`backend/tests/test_skill_agent_tool_resolution.py`、`backend/tests/test_file_ref_and_gateway.py`
- 验收点：
  - 未授权 MCP 工具不进入专家工具集。
  - 断连、鉴权失败、参数错误返回 server/tool 维度诊断。

### T-UR07-01：沙箱镜像、依赖和网络策略回归

- 对应需求：UR-07、UR-11
- 状态：`verify`
- 修改范围：`backend/app/api/sandbox_settings.py`、`backend/app/agent/sandbox_service.py`、`backend/app/agent/sandbox_policy_runtime.py`
- 测试入口：`backend/tests/test_sandbox_service.py`、`backend/tests/test_sandbox_policy_runtime.py`、`backend/tests/test_sandbox_requirements_runtime.py`
- 验收点：
  - 普通版和 Playwright 版沙箱选择可保存。
  - 默认禁网策略生效。
  - 冷启动、依赖安装、超时和工具不可用错误可诊断。

### T-UR08-01：工作区文件预览下载鉴权链路

- 对应需求：UR-08
- 状态：`verify`
- 修改范围：`frontend/src/features/workspace/FileDetailView.vue`、`backend/app/api/files.py`
- 测试入口：`frontend/e2e/workspace.spec.ts`、`backend/tests/test_workspace_files.py`
- 验收点：
  - 图片、PDF、下载都通过带鉴权请求获取 Blob。
  - 裸 URL 访问受保护文件返回拒绝。
  - 编辑保存后文件内容可重新打开。

### T-UR09-01：资源包导入冲突预览

- 对应需求：UR-09
- 状态：`verify`
- 修改范围：`backend/app/core/scenario_bundle.py`、`backend/app/core/expert_bundle.py`、`backend/app/core/settings_bundle_import.py`、`frontend/src/features/resources/`
- 测试入口：`backend/tests/test_bundle_import_api.py`、`backend/tests/test_scenario_bundle.py`、`backend/tests/test_expert_bundle.py`、`frontend/e2e/resources-scenario-expert.spec.ts`
- 验收点：
  - 导入前展示对象类型、名称、依赖和冲突。
  - 结构错误、依赖缺失、无权限导入有明确错误。

### T-UR10-01：模型、密钥和默认主持人配置链路

- 对应需求：UR-10
- 状态：`verify`
- 修改范围：`backend/app/api/settings_skills.py`、`backend/app/api/settings_secrets.py`、`backend/app/core/host_config.py`、`frontend/src/features/settings/`
- 测试入口：`backend/tests/test_llm_config.py`、`frontend/e2e/settings.spec.ts`
- 验收点：
  - 新会话使用最新默认主持人和模型配置。
  - API Key 列表和详情脱敏。
  - 修改账号、安全和主题设置有保存反馈。

### T-UR11-01：部署健康检查和 1Panel 冒烟

- 对应需求：UR-11
- 状态：`verify`
- 修改范围：`backend/app/main.py`、`backend/app/core/lifespan.py`、`backend/app/core/static_spa.py`、`docker-compose.1panel.yml`、`scripts/`
- 测试入口：`backend/tests/test_lifespan.py`、`backend/tests/test_static_spa.py`、`backend/tests/test_pack_1panel_backup.py`
- 验收点：
  - `/health` 返回 `{ "status": "ok" }`。
  - `STATIC_DIR` 存在时 SPA fallback 正常。
  - 打包脚本不包含本地运行输出和敏感文件。

## 4. 单任务执行模板

后续每个任务进入开发时，按以下顺序执行：

1. 读取对应 UR、详细设计和测试用例。
2. 为目标行为补充或更新自动化测试。
3. 运行目标测试，确认测试能覆盖当前变更。
4. 修改最小范围代码。
5. 运行目标测试和必要的第一层回归。
6. 同步更新文档。
7. 狭窄暂存并提交。

推荐命令：

```bash
rtk conda run -n st49 pytest backend/tests/test_sessions_api.py -q
rtk conda run -n st49 pytest backend/tests/test_skill_agent_tool_resolution.py backend/tests/test_sandbox_service.py -q
rtk proxy npm --prefix frontend run build
rtk ./scripts/test-layer1.sh
```

## 5. 排期建议

近期优先顺序：

1. P0 回归守住：T-UR01-02、T-UR02-02、T-UR03-01、T-UR05-01、T-UR06-01、T-UR07-01。
2. 上线验收补强：T-UR08-01、T-UR09-01、T-UR10-01、T-UR11-01。
3. 已修复项持续防回归：T-UR01-01、T-UR02-01。

每轮迭代只选择 1 到 3 个强相关任务，避免同时改动认证、编排、沙箱和前端大面积页面。
