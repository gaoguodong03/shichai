# 书童四九详细设计说明书

版本：v1.0 项目验收版
日期：2026-07-05
适用范围：书童四九平台的账号、工作区、会话、主持人、专家、资源中心、Skill、MCP、沙箱、文件、导入导出、模型密钥和部署运维设计。

## 1. 文档目的

本文承接 [用户需求说明书](../requirements/user-requirements.md)、[运行逻辑与接口契约](../contracts/runtime-interface-contract.md) 与 [数据结构与字段逻辑](../contracts/data-structure-and-field-logic.md)，进一步细化平台各子系统的模块职责、接口输入输出、数据文件、处理流程、异常处理和验收测试映射。

本文面向开发、测试和项目验收人员。它不描述具体上层业务应用的内容设计，重点说明书童四九作为 AI Agent 应用搭建与运行平台，如何通过可配置资源、统一会话、工具执行和用户隔离支撑应用运行。

## 2. 设计范围

### 2.1 本文覆盖

- 账号与用户隔离设计。
- 工作区与统一会话设计。
- 主持人与专家协作设计。
- 资源中心设计。
- Skill、MCP、脚本与沙箱执行设计。
- 工作区文件管理设计。
- 资源导入导出设计。
- 模型、密钥和个人设置设计。
- 部署与运维设计。
- 需求、模块、接口和测试之间的追踪关系。

### 2.2 本文不覆盖

- 具体业务应用的流程、内容质量和运营策略。
- 公网 SaaS 商业化、计费、组织审批和复杂 RBAC。
- 大规模并发压测指标。
- 移动端原生应用。

## 3. 总体模块划分

| 模块 | 主要职责 | 前端入口 | 后端入口 | 对应需求 |
|------|----------|----------|----------|----------|
| 账号与用户上下文 | 登录、注册、改密、受保护访问、用户资源根 | `features/auth`、`features/settings` | `api/auth.py`、`core/security.py`、`core/user_context.py` | UR-01 |
| 工作区与会话 | 会话列表、消息流、成员、状态、会话文件 | `features/workspace` | `api/sessions.py`、`agent/group_session_service.py` | UR-02、UR-08 |
| 编排运行时 | 主持人调度、专家路由、等待用户、结束状态 | `useGroupOrchestrationState.ts` | `agent/group_chat_runtime.py`、`group_orchestration_fsm.py` | UR-03 |
| 资源中心 | 场景、专家、Skill、MCP、模型、文件资源维护 | `features/resources` | `api/agents.py`、`api/settings*.py` | UR-04、UR-09、UR-10 |
| 工具运行 | Skill 选择、MCP 工具、脚本、文件工具、HTTP API | 工作区消息流和资源详情页 | `agent/tools_for_skill.py`、`agent/tool_gateway.py`、`tools/*` | UR-05、UR-06 |
| 沙箱 | 沙箱版本、requirements、挂载、网络、超时 | `SandboxSettingsView.vue` | `api/sandbox_settings.py`、`agent/sandbox_*` | UR-07 |
| 部署运维 | 健康检查、静态资源、Docker/1Panel、日志诊断 | 浏览器入口 | `main.py`、`core/lifespan.py`、`core/static_spa.py` | UR-11 |

## 4. 数据设计

### 4.1 用户数据布局

平台运行数据按 `user_id` 隔离保存。当前标准布局如下：

```text
backend/data/users/{user_id}/
  profile.json

  resources/
    scenarios/{scenario_name}/scenario.json
    agents/{agent_name}/agent.json
    skills/{skill_directory}/SKILL.md
    tools/{tool_name}/tool.json
    models/{model_name}/model.json

  settings/
    app.json
    secrets.enc.json
    sandbox/
      requirements.txt
      settings.json

  sessions/
    index.json
    {session_id}/
      session.json
      history.json
      runtime.json
      chat.md
      workspace/
      checkpoints/
        HEAD.json
        chain.json
        commits/
        objects/
```

约束：

- `resources/` 保存可管理、可导入导出的平台资源。
- `settings/` 保存账号级设置、密钥库和沙箱依赖。
- `sessions/` 保存真实会话、运行状态、消息历史、工作区产物和检查点。
- `meta.json` 不作为新会话协议文件名使用。
- 密钥明文只允许后端密钥库持有，不进入资源包、会话文件或沙箱挂载目录。

### 4.2 主要实体

| 实体 | 主身份 | 存储位置 | 关键引用 |
|------|--------|----------|----------|
| 用户 | `user_id` | `backend/data/users/{user_id}` | 资源、会话、设置、密钥、沙箱 |
| 场景 | `name` | `resources/scenarios/{name}/scenario.json` | 主持人配置、专家名称、场景规则 |
| 专家 | `name` | `resources/agents/{name}/agent.json` | 模型名称、Skill 目录、系统提示词 |
| Skill | `directory_name` | `resources/skills/{directory_name}/` | `SKILL.md`、脚本、依赖、allowed-tools |
| MCP/工具 | `name` | `resources/tools/{name}/tool.json` | transport、密钥引用、工具 schema |
| 模型 | `name` | `resources/models/{name}/model.json` | Base URL、模型名、密钥引用 |
| 会话 | `session_id` | `sessions/{session_id}/` | 场景名称、专家名称、历史、工作区 |
| 文件 | 工作区相对路径 | `sessions/{session_id}/workspace/` | 消息引用、工具读写、下载预览 |

### 4.3 会话文件职责

| 文件或目录 | 职责 |
|------------|------|
| `sessions/index.json` | 当前用户会话列表摘要和排序信息 |
| `session.json` | 会话定义：标题、场景、参与专家、新建时间、归档状态等 |
| `history.json` | 平台消息事实：用户、主持人、专家、工具结果和 Skill 控制结果 |
| `runtime.json` | UI 恢复所需运行态镜像，如等待、运行中、下一步状态 |
| `chat.md` | 面向 Agent、检查点或导出的会话 Markdown 快照 |
| `workspace/` | 当前会话工作区文件 |
| `checkpoints/` | 会话检查点、对象存储和回滚链 |

## 5. 接口设计

### 5.1 通用约定

所有业务 API 统一挂载在 `/api` 下，健康检查 `/health` 和前端静态入口除外。

通用响应格式：

```json
{
  "status": "ok",
  "data": {}
}
```

错误约定：

| 状态码 | 场景 |
|--------|------|
| `400` | 请求结构、导入包、路径或配置不合法 |
| `401` | 未登录或凭据无效 |
| `403` | 当前用户无权访问该资源 |
| `404` | 会话、资源、文件或配置不存在 |
| `500` | 服务内部错误 |
| `503` | 模型、MCP、沙箱等外部服务不可用 |

### 5.2 核心接口分组

| 分组 | 主要接口 | 说明 |
|------|----------|------|
| 认证与账号 | `/api/auth/login`、`/api/auth/register`、`/api/auth/account`、`/api/auth/password` | 登录、注册、账号和密码维护 |
| 统一会话 | `/api/sessions`、`/api/sessions/{id}`、`/api/sessions/{id}/chat/stream` | 会话 CRUD、流式消息、历史和状态 |
| 专家资源 | `/api/agents/*`、`/api/dha/instances/*` | 专家 CRUD 和专家包导入导出 |
| 场景资源 | `/api/settings/session-presets/*` | 场景列表、保存、导入导出 |
| Skill | `/api/settings/skills/*` | Skill 元信息、`SKILL.md`、文件分区、ZIP 导入导出 |
| MCP | `/api/settings/mcp/*` | MCP 配置、连接测试、工具列表、工具调用、导入导出 |
| 工作区文件 | `/api/workspaces/{workspace_id}/files*` | 文件列表、上传、新建、编辑、下载、删除 |
| 设置 | `/api/settings/app`、`/api/settings/host-profile`、`/api/settings/api-secrets` | 应用设置、默认主持人、密钥 |
| 沙箱 | `/api/settings/sandbox*` | 沙箱版本、requirements、依赖合并 |

### 5.3 SSE 事件设计

主入口：

```text
POST /api/sessions/{session_id}/chat/stream
```

常见事件：

| 事件 | 载荷重点 | 前端用途 |
|------|----------|----------|
| `route` | `agent_name`、`skill`、路由调试信息 | 展示本轮交给谁处理 |
| `content` | 增量文本 | 流式显示生成过程 |
| `tool_start` | 工具名称、参数摘要 | 展示工具运行中 |
| `tool_result` | 工具结果或错误 | 展示工具完成或失败 |
| `message` | 完整消息气泡 | 落到消息列表 |
| `end` | `phase`、`waiting_for_user`、下一步状态 | 更新会话状态 |
| `error` | 可展示错误 | 失败提示 |

约束：

- 前端只消费后端最终事件，不自行推断主持人调度结果。
- 非流式 `/chat` 复用同一条 SSE 逻辑，在服务端聚合结果。
- 新增事件必须同步前端解析、E2E mock、后端测试和文档。

## 6. 子系统详细设计

### 6.1 账号与用户隔离

设计目标：

- 用户登录后只能访问自己的会话、资源、密钥、文件和沙箱配置。
- 生产环境关闭匿名 API 后，无令牌请求必须被拒绝。

主要流程：

1. 用户在登录页提交账号和密码。
2. 后端验证账号，签发会话凭据。
3. 前端后续请求携带凭据。
4. 后端通过用户上下文解析当前用户。
5. 业务模块从当前用户数据根读写资源。

关键文件：

- `backend/app/api/auth.py`
- `backend/app/core/security.py`
- `backend/app/core/user_context.py`
- `backend/app/core/user_settings_paths.py`
- `frontend/src/features/auth/LoginView.vue`
- `frontend/src/router/index.ts`

异常处理：

- 未登录访问受保护页面：前端跳转登录页并保留 redirect。
- 令牌无效：后端返回 401。
- 当前密码错误等业务失败：返回 400，不能误触发全局登出。
- 跨用户资源访问：返回 403 或 404，不泄露真实路径。

验收测试：

- `backend/tests/test_auth_sqlite.py`
- `backend/tests/test_user_resource_paths.py`
- `frontend/e2e/auth.spec.ts`

### 6.2 工作区与统一会话

设计目标：

- 普通会话、场景会话和多专家协作共用统一会话入口。
- 会话刷新后恢复历史、成员、工作区文件和运行状态。

主要流程：

1. 前端请求会话列表或创建会话。
2. 后端在当前用户 `sessions/` 下维护 `index.json` 和会话目录。
3. 用户发送消息时进入 `/chat/stream`。
4. 后端读取会话定义、历史、场景和专家资源。
5. 运行时通过 SSE 返回路由、内容、工具和结束事件。
6. 后端写入 `history.json`、`runtime.json` 和工作区产物。

关键文件：

- `backend/app/api/sessions.py`
- `backend/app/api/group_chat_state.py`
- `backend/app/agent/group_session_service.py`
- `backend/app/session_state/paths.py`
- `backend/app/session_state/service.py`
- `frontend/src/features/workspace/WorkspaceContent.vue`
- `frontend/src/features/workspace/composables/useGroupChatStreamRunner.ts`

异常处理：

- 会话不存在：返回 404。
- 会话被删除后继续发送：请求被拒绝。
- SSE 中断：前端保留已收到消息并展示失败状态。
- 轮次上限或工具失败：`end` 事件带可展示状态。

验收测试：

- `backend/tests/test_sessions_api.py`
- `backend/tests/test_group_chat_stream_protocol.py`
- `backend/tests/test_group_chat_state.py`
- `frontend/e2e/workspace.spec.ts`

### 6.3 主持人与专家协作

设计目标：

- 主持人根据会话、场景、成员和用户消息组织专家协作。
- 用户点名专家时优先交给该专家。
- 专家需要补充信息时进入等待用户状态。

主要流程：

1. 运行时读取当前会话成员和场景配置。
2. 判断是否存在 `@专家`、显式点名、Skill 续跑或主持人接管意图。
3. 若命中强制路由，直接交给对应专家。
4. 否则调用主持人生成结构化调度决策。
5. 决策通过严格结构校验后进入专家执行、等待用户、邀请专家或结束。
6. 主持人调度说明和专家回复都以可见消息进入历史。

关键文件：

- `backend/app/agent/group_chat_runtime.py`
- `backend/app/agent/group_orchestration_fsm.py`
- `backend/app/agent/group_chat_host_runtime.py`
- `backend/app/agent/group_host_decision.py`
- `backend/app/agent/group_chat_expert_resolution.py`
- `backend/app/agent/expert_runtime.py`
- `backend/app/core/scene_scheduler.py`

异常处理：

- 主持人输出非严格 JSON：转为协议错误提示，等待用户重试。
- 场景会话误推荐场景外专家：后处理清空推荐。
- 专家不存在或已删除：回主持人或返回可诊断错误。
- 专家要求补充字段：进入 `waiting_for_user`，不继续空转。

验收测试：

- `backend/tests/test_group_host_decision.py`
- `backend/tests/test_host_takeover.py`
- `backend/tests/test_scene_scheduler.py`
- `backend/tests/test_scene_runtime.py`
- `backend/tests/test_group_orchestration_fsm.py`

### 6.4 资源中心

设计目标：

- 用户可以集中维护场景、专家、Skill、MCP、模型和文件。
- 资源保存后，新会话和运行时读取最新配置。
- 资源只保存引用关系，不复制另一个资源的完整内容。

设计要点：

| 资源 | 设计重点 |
|------|----------|
| 场景 | 保存主持人配置、协作专家和场景规则，引用专家与 Skill |
| 专家 | 保存名称、模型、描述、系统提示词、Skill 引用和工具权限 |
| Skill | 目录化保存 `SKILL.md`、脚本、引用资料、资产和模板 |
| MCP | 保存 transport、server 配置、工具 schema 和密钥引用 |
| 模型 | 保存 Base URL、模型名、参数和密钥引用 |
| 文件 | 按会话工作区组织，可被用户和工具读写 |

关键文件：

- `frontend/src/features/resources/useScenarioEditor.ts`
- `frontend/src/features/resources/AgentView.vue`
- `frontend/src/features/resources/SkillDetailView.vue`
- `frontend/src/features/resources/MCPDetailView.vue`
- `frontend/src/features/resources/LLMSettingsView.vue`
- `backend/app/api/agents.py`
- `backend/app/api/settings_presets.py`
- `backend/app/api/settings_skills.py`
- `backend/app/api/settings_mcp.py`
- `backend/app/api/settings_app.py`

异常处理：

- 同名资源保存：按资源类型规则覆盖或提示冲突。
- 引用缺失：导入预览和运行时提示缺失专家、Skill、MCP 或模型。
- 密钥引用缺失：MCP 或模型调用返回可诊断错误。
- 用户删除资源：新会话按最新资源解析，旧会话保留运行事实和引用。

验收测试：

- `backend/tests/test_agents_api.py`
- `backend/tests/test_bundle_import_api.py`
- `backend/tests/test_scenario_bundle.py`
- `backend/tests/test_expert_bundle.py`
- `backend/tests/test_llm_config.py`
- `frontend/e2e/resources-scenario-expert.spec.ts`
- `frontend/e2e/resources-skill-mcp-llm.spec.ts`

### 6.5 Skill 与脚本执行

设计目标：

- Skill 描述专家可复用工作方法和工具权限。
- 脚本型 Skill 在当前用户工作区和沙箱中执行。
- 执行结果、错误和下一步控制信号回到会话。

主要流程：

1. 专家运行时读取专家绑定的 Skill 列表。
2. 多 Skill 时按任务和 Skill 描述选择本轮 Skill。
3. 读取 `SKILL.md` 正文和 frontmatter。
4. 根据 `allowed-tools` 组装 MCP、HTTP API、Python 依赖和内置文件工具。
5. 模型触发脚本工具时，`run_skill_script` 将请求交给沙箱。
6. 脚本 stdout JSON 或专家结构化输出决定是否继续 Skill 会话。

关键文件：

- `backend/app/agent/expert_runtime.py`
- `backend/app/agent/skill_agent_runtime.py`
- `backend/app/agent/tools_for_skill.py`
- `backend/app/agent/skill_session_contract.py`
- `backend/app/tools/run_skill_script.py`
- `backend/app/api/settings_skill_store.py`
- `backend/app/api/settings_skill_frontmatter.py`

异常处理：

- Skill 目录不存在：返回缺失引用诊断。
- `SKILL.md` 缺失或 frontmatter 错误：页面和运行时提示配置不完整。
- 脚本超时、退出码非零、stdout 非 JSON：回传工具错误。
- 依赖缺失：提示维护 requirements 或切换沙箱版本。
- Skill 会话状态不明确：按严格协议处理，不用旧字段兜底。

验收测试：

- `backend/tests/test_skill_agent_tool_resolution.py`
- `backend/tests/test_skill_mcp_and_script_requirements.py`
- `backend/tests/test_group_chat_skill_script_cli_flow.py`
- `backend/tests/test_group_orchestration_fsm.py`

### 6.6 MCP 工具能力

设计目标：

- 用户可以配置 MCP Server，并把工具能力授权给专家和 Skill。
- 运行时只暴露本轮允许的 MCP 工具。
- 连接、鉴权、参数和远端错误可诊断。

主要流程：

1. 用户在资源中心新增 MCP 工具配置。
2. 后端保存 transport、server 配置和密钥引用。
3. 资源详情页可测试连接和查看工具列表。
4. 专家运行时根据 Skill `allowed-tools.mcp` 加载允许的 MCP Server。
5. 工具调用通过 MCP manager 执行，并把结果标准化回会话。

关键文件：

- `backend/app/api/settings_mcp.py`
- `backend/app/mcp/manager.py`
- `backend/app/mcp/tool_arg_normalizers.py`
- `backend/app/agent/tools_for_skill.py`
- `backend/app/agent/simple_agent_mcp_tools.py`

异常处理：

- MCP 配置结构错误：保存或连接测试返回 400。
- MCP Server 连接失败：返回连接失败诊断。
- 鉴权失败：提示密钥引用或远端凭据问题。
- 工具 schema 不合法：不进入可用工具列表。
- 未授权 MCP：不暴露给专家工具集合。

验收测试：

- `backend/tests/test_skill_agent_tool_resolution.py`
- `backend/tests/test_file_ref_and_gateway.py`
- `backend/tests/test_mcp_skill_resolution.py`
- `frontend/e2e/resources-skill-mcp-llm.spec.ts`

### 6.7 沙箱运行环境

设计目标：

- 为 Skill 脚本和浏览器自动化提供受控执行环境。
- 沙箱只获得当前任务需要的工作区和 Skill 执行视图。
- requirements、镜像、网络、超时和冷启动问题可诊断。

主要流程：

1. 用户在设置页选择普通版或 Playwright 版沙箱。
2. 用户维护当前账号 Python requirements。
3. 执行脚本时，后端构建沙箱请求和挂载策略。
4. `/workspace` 挂载当前会话工作区。
5. `/skills` 可物理挂载用户 Skill 根，但运行时只注册和暴露本轮允许的 Skill/工具。
6. 执行结果、错误、超时或依赖诊断回传会话。

关键文件：

- `backend/app/api/sandbox_settings.py`
- `backend/app/agent/sandbox_service.py`
- `backend/app/agent/sandbox_policy_runtime.py`
- `backend/app/agent/sandbox_policy_builder.py`
- `backend/app/agent/sandbox_requirements_runtime.py`
- `backend/app/agent/sandbox_workspace_fs.py`

异常处理：

- OpenSandbox 不可达：返回 503 或可诊断运行时错误。
- 镜像缺失或版本不匹配：提示部署侧检查镜像。
- requirements 安装失败：返回依赖解析或安装日志摘要。
- 网络被策略拦截：返回网络策略诊断。
- 访问未授权路径：拒绝并记录路径安全错误。

验收测试：

- `backend/tests/test_sandbox_service.py`
- `backend/tests/test_sandbox_policy_runtime.py`
- `backend/tests/test_sandbox_requirements_runtime.py`
- `backend/tests/test_sandbox_workspace_fs.py`
- `backend/tests/test_sandbox_policy_builder.py`

### 6.8 工作区文件管理

设计目标：

- 用户可以在会话工作区上传、预览、编辑、保存、重命名、删除和下载文件。
- 专家和工具只能访问当前会话或授权范围内的工作区文件。

主要流程：

1. 前端打开工作区文件面板。
2. 后端按当前用户和 `workspace_id` 定位会话工作区。
3. 用户上传或新建文件时写入 `sessions/{session_id}/workspace/`。
4. 用户消息可引用工作区文件。
5. 专家运行时展开文件引用并交给模型或工具。
6. 工具生成文件后，前端文件列表刷新显示新产物。

关键文件：

- `backend/app/api/files.py`
- `backend/app/agent/file_ref_resolver.py`
- `backend/app/agent/path_whitelist_guard.py`
- `backend/app/tools/read_file.py`
- `backend/app/tools/write_workspace_file.py`
- `frontend/src/features/workspace/WorkspaceFilesView.vue`
- `frontend/src/features/workspace/FileDetailView.vue`
- `frontend/src/features/workspace/components/group-chat/GroupWorkspacePanel.vue`

异常处理：

- 路径穿越：拒绝访问。
- 文件不存在：返回 404。
- 跨用户路径：拒绝或返回不存在。
- 二进制预览不支持：提供下载或明确提示。
- 工具声称写入但文件不存在：运行时应校验并纠正交付说法。

验收测试：

- `backend/tests/test_workspace_files.py`
- `backend/tests/test_file_ref_and_gateway.py`
- `backend/tests/test_sandbox_workspace_fs.py`
- `frontend/e2e/workspace.spec.ts`

### 6.9 资源导入导出

设计目标：

- 用户可以导出和导入场景、专家、Skill 或 MCP 工具资源包。
- 导入前展示内容、依赖、冲突和本地引用重映射。
- 资源包不携带账号凭据和密钥明文。

主要流程：

1. 用户在资源详情页点击导出。
2. 后端打包资源主体和必要依赖。
3. 用户在目标账号上传 ZIP。
4. 后端解析资源包，生成导入预览。
5. 用户确认导入后，后端写入当前用户资源中心。
6. 导入结果返回“新增/保留/覆盖”等可理解摘要。

关键文件：

- `backend/app/core/scenario_bundle.py`
- `backend/app/core/expert_bundle.py`
- `backend/app/core/settings_bundle_import.py`
- `backend/app/api/settings_presets.py`
- `backend/app/api/agents.py`
- `frontend/src/features/resources/useBundleImports.ts`
- `frontend/src/features/resources/useZipResourceImports.ts`

异常处理：

- ZIP 结构错误：返回明确结构错误。
- 资源包缺主体文件：拒绝导入。
- 依赖缺失：导入预览展示缺失项。
- 同名冲突：按名称判断覆盖或保留。
- 密钥引用缺失：保留引用但提示目标账号需配置密钥。

验收测试：

- `backend/tests/test_bundle_import_api.py`
- `backend/tests/test_scenario_bundle.py`
- `backend/tests/test_expert_bundle.py`
- `frontend/e2e/resources-scenario-expert.spec.ts`

### 6.10 模型、密钥与个人设置

设计目标：

- 用户可以配置模型、密钥、默认主持人、账号安全、主题和沙箱偏好。
- 密钥在前端脱敏展示，只在后端运行时解析。

主要流程：

1. 用户在设置页维护 API Key、模型或默认主持人配置。
2. 后端保存到当前用户 `settings/`。
3. 新会话或专家运行时读取最新模型和主持人配置。
4. MCP 或模型请求需要密钥时，后端按引用解析密钥。
5. 前端列表和详情只展示脱敏值或配置状态。

关键文件：

- `backend/app/api/settings_app.py`
- `backend/app/api/settings_secrets.py`
- `backend/app/agent/llm_client.py`
- `backend/app/core/host_config.py`
- `frontend/src/features/settings/AppSettingsView.vue`
- `frontend/src/features/settings/ApiSecretsSettingsView.vue`
- `frontend/src/features/settings/AccountSecuritySettingsView.vue`
- `frontend/src/features/settings/ThemeSettingsView.vue`

异常处理：

- 密钥缺失：模型或 MCP 调用返回可诊断错误。
- 密钥保存失败：前端展示保存失败。
- 修改密码错误：返回业务错误，不触发误登出。
- 模型配置无效：运行时返回模型连接或参数诊断。

验收测试：

- `backend/tests/test_llm_config.py`
- `backend/tests/test_auth_sqlite.py`
- `backend/tests/test_sessions_api.py`
- `frontend/e2e/settings.spec.ts`

### 6.11 部署与运维

设计目标：

- 支持本地开发、Docker 和 1Panel 私有化部署。
- 部署后能通过健康检查、日志和冒烟路径判断系统是否可用。

主要流程：

1. 后端启动时初始化生命周期、静态资源和必要运行环境。
2. 前端构建后可由后端同源挂载。
3. OpenSandbox 独立运行，由环境变量或编排配置指定 endpoint、镜像和策略。
4. 用户数据、账号配置和运行数据落在持久化数据卷。
5. `/health` 用于基础探活。

关键文件：

- `backend/app/main.py`
- `backend/app/core/lifespan.py`
- `backend/app/core/static_spa.py`
- `Dockerfile`
- `docker-compose.1panel.yml`
- `pack_1panel_backup.sh`

异常处理：

- 后端启动失败：检查环境变量、依赖和日志。
- 前端静态目录缺失：API 可用但 SPA fallback 不可用。
- OpenSandbox 不可达：Skill 脚本和浏览器自动化失败，但主应用不应崩溃。
- 数据卷未挂载：重启后数据丢失，应在部署验收中阻断。

验收测试：

- `backend/tests/test_lifespan.py`
- `backend/tests/test_static_spa.py`
- `backend/tests/test_pack_1panel_backup.py`
- `docs/testing/pre-release-testing.md`

## 7. 异常处理总则

| 异常类型 | 处理原则 |
|----------|----------|
| 鉴权异常 | 返回 401，前端跳转登录或提示重新登录 |
| 权限异常 | 返回 403 或 404，不泄露其他用户路径 |
| 配置异常 | 返回 400，并指出缺失字段、引用或资源 |
| 模型异常 | 保留会话状态，返回模型连接、超时或参数诊断 |
| MCP 异常 | 返回连接、鉴权、断连或 schema 诊断 |
| 沙箱异常 | 返回冷启动、依赖、超时、网络或路径诊断 |
| 文件异常 | 返回路径非法、不存在、类型不支持或读写失败 |
| 编排异常 | 写入可见系统提示或 end 状态，避免会话无提示卡死 |

## 8. 需求到详细设计追踪

| 需求 | 详细设计章节 | 验收测试 |
|------|--------------|----------|
| UR-01 账号与用户隔离 | 6.1 | `test_auth_sqlite.py`、`test_user_resource_paths.py`、`auth.spec.ts` |
| UR-02 工作区与统一会话 | 6.2 | `test_sessions_api.py`、`test_group_chat_stream_protocol.py`、`workspace.spec.ts` |
| UR-03 主持人与专家协作 | 6.3 | `test_group_host_decision.py`、`test_host_takeover.py`、`test_scene_scheduler.py` |
| UR-04 资源中心 | 6.4 | `test_agents_api.py`、资源中心 E2E |
| UR-05 Skill 与脚本执行 | 6.5 | `test_skill_agent_tool_resolution.py`、`test_group_chat_skill_script_cli_flow.py` |
| UR-06 MCP 工具能力 | 6.6 | `test_file_ref_and_gateway.py`、`test_mcp_skill_resolution.py` |
| UR-07 沙箱运行环境 | 6.7 | `test_sandbox_service.py`、`test_sandbox_policy_runtime.py` |
| UR-08 工作区文件管理 | 6.8 | `test_workspace_files.py`、`test_sandbox_workspace_fs.py` |
| UR-09 导出与导入 | 6.9 | `test_bundle_import_api.py`、`test_scenario_bundle.py`、`test_expert_bundle.py` |
| UR-10 模型、密钥与个人设置 | 6.10 | `test_llm_config.py`、`settings.spec.ts` |
| UR-11 部署与运维 | 6.11 | `test_lifespan.py`、`test_static_spa.py`、`test_pack_1panel_backup.py` |

## 9. 变更规则

后续修改详细设计时，必须同步检查：

1. 是否仍符合《用户需求说明书》的平台定位。
2. 是否与《架构设计文档》的分层和边界一致。
3. 是否改变用户数据布局、会话文件、接口字段或 SSE 事件。
4. 是否影响用户隔离、密钥脱敏、路径白名单或工具权限。
5. 是否需要更新 `docs/testing/test-case-catalog.md`。
6. 是否需要补充后端 API 测试、前端 E2E 或手工验收项。

只改文档时，至少运行：

```bash
rtk proxy git diff --check -- docs
```
