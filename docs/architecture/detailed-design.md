# 书童四九详细设计

## 1. 文档目的

本文承接 [用户需求文档](../requirements/user-requirements.md) 和 [需求说明与验收测试](../requirements/acceptance-and-tests.md)，把 UR-01 到 UR-11 落到当前代码模块、数据边界、接口入口、前端页面和测试入口。

本文用于后续开发前的设计复核。任何新增需求应先更新需求和验收矩阵，再同步本文对应模块。

## 2. 总体设计边界

书童四九按“账号隔离资源、会话承载任务、主持人调度专家、Skill/MCP/沙箱执行工具、工作区沉淀结果”的链路组织。

核心边界如下：

| 边界 | 责任 | 主要代码入口 | 对应需求 |
|------|------|--------------|----------|
| 用户与资源根 | 认证、用户上下文、用户目录隔离 | `backend/app/api/auth.py`、`backend/app/core/user_context.py`、`backend/app/core/user_settings_paths.py` | UR-01 |
| 会话与工作区 | 会话 CRUD、SSE、历史、成员和文件上下文 | `backend/app/api/sessions.py`、`backend/app/api/group_chat.py`、`frontend/src/features/workspace/` | UR-02、UR-03、UR-08 |
| 编排运行时 | 主持人决策、专家调度、轮次状态、审计 | `backend/app/agent/group_orchestration_fsm.py`、`backend/app/agent/leader_scheduler.py`、`backend/app/agent/orchestrator_runtime.py` | UR-03 |
| 资源中心 | 场景、专家、Skill、MCP、模型、密钥、文件 | `backend/app/api/agents.py`、`backend/app/api/settings*.py`、`frontend/src/features/resources/` | UR-04、UR-09、UR-10 |
| Skill、MCP 与工具网关 | 专家 Skill 选型、MCP 权限、脚本工具、参数归一化 | `backend/app/agent/expert_runtime.py`、`backend/app/agent/tool_gateway.py`、`backend/app/mcp/manager.py` | UR-05、UR-06 |
| 沙箱 | 镜像选择、挂载、依赖、超时、网络策略 | `backend/app/agent/sandbox_service.py`、`backend/app/agent/sandbox_policy_runtime.py`、`backend/app/api/sandbox_settings.py` | UR-07 |
| 部署运行 | 应用启动、健康检查、静态资源、1Panel/Docker | `backend/app/main.py`、`backend/app/core/lifespan.py`、`backend/app/core/static_spa.py` | UR-11 |

## 3. 请求链路设计

### 3.1 登录和受保护路由

1. 前端从 `frontend/src/main.ts` 初始化全局请求和 401 处理。
2. 用户在 `frontend/src/features/auth/LoginView.vue` 登录后获得令牌。
3. 受保护页面通过路由守卫和后端鉴权共同保护。
4. 后端在 API 层读取当前用户上下文，所有用户资源路径都从当前用户根目录派生。

设计约束：

- 业务错误不能滥用 401。账号安全中“当前密码错误”等业务失败应返回 400，避免前端全局 401 处理把用户踢回登录页。
- 生产环境关闭匿名 API 后，所有受保护接口必须依赖有效令牌。
- 用户资源路径只能通过 `user_context` 和 `user_settings_paths` 获取，不允许在业务代码中拼接其他用户目录。

测试入口：

- `backend/tests/test_auth_sqlite.py`
- `frontend/e2e/auth.spec.ts`
- `frontend/e2e/settings.spec.ts`

### 3.2 会话发送和 SSE 返回

1. 前端工作区由 `frontend/src/features/workspace/WorkspaceContent.vue` 组织页面状态。
2. 消息发送由 `frontend/src/features/workspace/components/group-chat/GroupChatComposer.vue` 发起。
3. 流式读取由 `frontend/src/features/workspace/composables/useGroupChatStreamRunner.ts` 承担。
4. 后端入口为 `backend/app/api/sessions.py` 和 `backend/app/api/group_chat.py`。
5. 编排运行时产生主持人调度、专家消息、工具事件和最终消息。
6. 前端按 SSE 事件更新消息气泡、状态条和工作区文件面板。

设计约束：

- `POST /api/sessions/{id}/chat/stream` 是当前流式主入口。
- `POST /api/sessions/{id}/chat` 的非流式返回必须选择与本轮路由专家一致的主消息，不能因主持人追加提示覆盖专家结果。
- 历史消息、成员列表、工作区文件和会话状态必须可持久化恢复。
- 等待用户补充、工具失败、轮次上限和异常结束都必须有用户可见状态。

测试入口：

- `backend/tests/test_sessions_api.py`
- `backend/tests/test_group_chat_stream_protocol.py`
- `backend/tests/test_group_orchestration_fsm.py`
- `backend/tests/test_frontend_business_flows.py`
- `frontend/e2e/workspace.spec.ts`

### 3.3 主持人和专家编排

主持人和专家协作由状态机、调度器和专家 runtime 组合完成。

| 组件 | 责任 | 关键文件 |
|------|------|----------|
| FSM | 控制发言、等待用户、结束和错误状态 | `backend/app/agent/group_orchestration_fsm.py` |
| 调度器 | 在普通会话和场景会话中选择发言专家 | `backend/app/agent/leader_scheduler.py`、`backend/app/core/scene_scheduler.py` |
| 主持人决策 | 生成调度说明和下一步动作 | `backend/app/agent/group_host_decision.py`、`backend/app/agent/orchestrator_runtime.py` |
| 专家运行 | 组装上下文、调用模型、处理 Skill/MCP 工具 | `backend/app/agent/expert_runtime.py`、`backend/app/agent/skill_agent_runtime.py` |
| 审计 | 记录编排决策和异常原因 | `backend/app/agent/sandbox_audit.py`、`backend/app/agent/orchestrator_reducer.py` |

设计约束：

- 普通会话允许主持人推荐专家；场景会话必须优先使用场景内专家。
- 用户显式 `@专家` 时，该路由优先级高于主持人自动选择。
- 主持人调度说明是用户可见消息，不应只存在于日志。
- 需要用户补充时进入等待状态，不继续空转。

测试入口：

- `backend/tests/test_group_host_decision.py`
- `backend/tests/test_host_takeover.py`
- `backend/tests/test_scene_scheduler.py`
- `backend/tests/test_expert_runtime.py`
- `backend/tests/test_orchestration_contracts.py`

### 3.4 资源中心

资源中心负责用户资产管理，前端集中在 `frontend/src/features/resources/`，后端由专家 API、设置 API、导入导出校验器和资源存储层支撑。

| 资源 | 前端入口 | 后端入口 | 校验重点 |
|------|----------|----------|----------|
| 场景 | `MainView.vue` 场景资源页、`useScenarioEditor.ts` | `settings_presets.py`、`scenario_bundle.py` | 依赖、冲突、导入预览 |
| 专家 | `AgentView.vue` | `agents.py`、`expert_bundle.py` | 用户隔离、Skill/MCP 绑定 |
| Skill | `SkillDetailView.vue` | `skills/loader.py`、`settings_bundle_import.py` | `SKILL.md`、脚本目录、依赖 |
| MCP | `MCPAddView.vue`、`MCPDetailView.vue` | `settings_mcp.py`、`mcp/manager.py` | transport、密钥引用、工具权限 |
| 模型和密钥 | `LLMSettingsView.vue`、设置页 | `settings_skills.py`、`settings_secrets.py` | 脱敏、引用、保存反馈 |
| 文件 | 工作区文件页和资源文件页 | `files.py`、`workspace_files` 相关逻辑 | 预览、下载、权限 |

设计约束：

- 所有资源列表默认只展示当前用户资源。
- 资源保存后，新会话和新专家运行应读取最新配置。
- 导入资源包必须先预览和校验冲突，不能无确认覆盖。
- 密钥类字段前端只展示脱敏值或状态。

测试入口：

- `backend/tests/test_agents_api.py`
- `backend/tests/test_bundle_import_api.py`
- `backend/tests/test_scenario_bundle.py`
- `backend/tests/test_expert_bundle.py`
- `backend/tests/test_llm_config.py`
- `frontend/e2e/resources-scenario-expert.spec.ts`
- `frontend/e2e/resources-skill-mcp-llm.spec.ts`

### 3.5 Skill、MCP 和沙箱执行

Skill 描述方法，MCP 暴露工具，沙箱提供受控运行环境。专家运行时只能拿到当前用户、当前专家、当前 Skill 声明允许的工具集合。

执行链路：

1. `expert_runtime.py` 根据用户任务、专家绑定、会话锁和候选 Skill 描述选定本轮 Skill。
2. `tools_for_skill.py` 和 `skill_agent_runtime.py` 组装可用工具。
3. `tool_gateway.py` 统一处理脚本工具、MCP 工具和文件工具调用。
4. `mcp/manager.py` 管理 MCP Server 和工具列表。
5. `sandbox_service.py`、`sandbox_policy_*` 和 `sandbox_workspace_*` 负责脚本执行环境。
6. 工具结果、错误、超时和诊断信息回传会话。

设计约束：

- Skill 脚本必须在当前用户工作区和用户沙箱中执行。
- MCP 工具权限来自专家配置和 Skill 声明，不能把全部 MCP 工具暴露给每个专家。
- 文件路径必须经过白名单和工作区策略检查。
- 沙箱错误信息要区分冷启动、依赖安装、超时、网络限制、工具不可用和 OpenSandbox 不可达。

测试入口：

- `backend/tests/test_skill_agent_tool_resolution.py`
- `backend/tests/test_skill_mcp_and_script_requirements.py`
- `backend/tests/test_group_chat_skill_script_cli_flow.py`
- `backend/tests/test_file_ref_and_gateway.py`
- `backend/tests/test_sandbox_service.py`
- `backend/tests/test_sandbox_policy_runtime.py`
- `backend/tests/test_sandbox_requirements_runtime.py`

### 3.6 工作区文件

工作区文件是会话成果沉淀和工具读写的公共边界。前端由 `WorkspaceFilesView.vue`、`FileDetailView.vue`、`GroupWorkspacePanel.vue` 展示；后端由文件 API、文件引用解析和沙箱工作区策略共同保护。

设计约束：

- 用户可以上传、预览、编辑、保存、重命名、删除和下载文件。
- 图片和 PDF 预览、文件下载不能直接依赖裸 URL；需要携带鉴权请求后转换为 Blob URL。
- 专家只读取当前会话或授权范围内的文件引用。
- 路径穿越、内部运行日志误读、跨用户路径访问必须被拒绝。

测试入口：

- `backend/tests/test_workspace_files.py`
- `backend/tests/test_file_ref_and_gateway.py`
- `backend/tests/test_sandbox_workspace_fs.py`
- `frontend/e2e/workspace.spec.ts`

### 3.7 部署和运维

部署形态以本地开发、Docker 和 1Panel 为主，后端启动由 `lifespan.py` 管理环境初始化和 MCP 生命周期，静态前端由 `static_spa.py` 挂载。

设计约束：

- `/health` 是基础健康检查入口。
- `STATIC_DIR` 存在时，根路径返回前端应用，非 API 路由走 SPA fallback。
- OpenSandbox、镜像 tag、沙箱 endpoint 和资源配额由部署环境控制。
- 生产日志需要包含 OpenSandbox、MCP、模型、路径权限和用户上下文相关关键词，便于排障。

测试入口：

- `backend/tests/test_lifespan.py`
- `backend/tests/test_static_spa.py`
- `backend/tests/test_sandbox_service.py`
- `backend/tests/test_pack_1panel_backup.py`

## 4. 横向设计规则

| 规则 | 说明 | 需要同步的文档 |
|------|------|----------------|
| 需求先行 | 新功能先分配或新增 UR 编号，再写接口和测试 | `../requirements/user-requirements.md`、`../requirements/acceptance-and-tests.md` |
| 用户隔离默认开启 | 任何资源读写都要能回答“当前用户是谁” | `user-resource-store/README.md` |
| 工具权限最小化 | Skill、MCP、脚本工具按专家和任务授权 | `../skills/skill-standard.md`、`../skills/sandbox-tool-interface.md` |
| 状态必须可见 | 等待、失败、超时、补充信息都要回到前端 | `../testing/test-case-catalog.md` |
| 测试跟随变更 | API、编排、沙箱、文件和前端路由变更必须更新测试入口 | `../testing/layer1-regression.md` |

## 5. 设计变更检查清单

每次修改架构或模块边界前，按以下顺序检查：

1. 需求编号是否已有，若没有先更新 `docs/requirements/user-requirements.md`。
2. 验收矩阵是否包含自动化测试和手工验收入口。
3. 本文对应模块是否需要补充代码入口、约束或失败模式。
4. `docs/project/implementation-task-breakdown.md` 是否已有可执行任务。
5. `docs/testing/test-case-catalog.md` 是否有覆盖正向、异常和权限边界的测试用例。
6. 代码变更后运行 `rtk ./scripts/test-layer1.sh` 或更窄的等价测试命令。
