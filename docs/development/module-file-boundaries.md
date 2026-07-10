# 模块与文件拆分边界

本文规定哪些职责必须独立成文件，哪些文件只能作为薄入口。后续大刀阔斧删除和重写代码时，以本文作为文件拆分依据。

## 1. 拆分原则

1. 一个文件只承担一个业务责任。文件名应能回答“这里负责什么”，而不是“这里顺便处理什么”。
2. 字段契约、运行决策、状态落盘、Prompt 组装、工具组装和前端展示状态必须分开。
3. 一起变化的逻辑放在一起；只是技术层级相同但业务责任不同的逻辑不要塞进同一个大文件。
4. 旧字段迁移和运行时主路径分开。迁移文件可以读旧字段，主路径不能读旧字段兜底。
5. 测试文件跟随模块边界。每个独立契约模块都要有对应聚焦测试。

## 2. 后端文件边界

### 2.1 API 层

目录：`backend/app/api/`

职责：

- FastAPI 路由注册。
- 鉴权和当前用户上下文注入。
- 请求体和响应体模型。
- HTTP 状态码和错误转换。
- 调用 `agent/`、`core/`、`session_state/` 或 `tools/` 的服务函数。

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `sessions.py` | 会话 CRUD、聊天流入口、停止运行、会话详情 API。只做薄入口。 |
| `group_chat_state.py` | 会话运行态文件 API 和状态读写入口。 |
| `agents.py` | 专家资源 API。 |
| `settings_presets.py` | 场景资源 API。 |
| `settings_skills.py`、`settings_skill_store.py`、`settings_skill_frontmatter.py`、`settings_skill_parts.py` | Skill 列表、正文、frontmatter 和分片文件管理。 |
| `settings_mcp.py` | MCP 和工具资源 API。 |
| `settings_app.py`、`settings_env_vars.py`、`sandbox_settings.py` | 应用设置、用户级环境变量和沙箱设置 API。 |
| `files.py` | 工作区文件 API。 |
| `auth.py` | 认证和账号 API。 |

禁止把主持人调度、专家执行、Prompt 拼接、工具组装或旧字段迁移写进 API 文件。

### 2.2 契约和 schema 层

目录：`backend/app/agent/` 或贴近调用方的专门模块。

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `structured_output_contracts.py` | LLM 和工具控制 JSON 的严格 schema 与解析错误。 |
| `message_contracts.py` | `history.json`、SSE `message` 和工具结果的消息结构。 |
| `skill_session_contract.py` | Skill 会话 keep/release、agent_turn 和 stdout 结构。 |
| 新增请求/响应契约文件 | 当 `sessions.py` 请求模型继续膨胀时，把请求体、SSE payload、错误码模型拆出。 |

规则：

- Schema 文件不读写磁盘，不调用 LLM，不发 SSE。
- Schema 只做结构定义、枚举、严格校验和错误描述。
- 新增字段必须先落在 schema，再进入运行时代码。

### 2.3 群聊编排层

目录：`backend/app/agent/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `group_chat_runtime.py` | 群聊一轮请求的总编排入口。只能串联步骤，不承载所有细节。 |
| `group_orchestration_fsm.py` | 入口路由优先级：空专家、目标专家、continuation、host_scheduler、主持人调度。 |
| `group_host_decision.py` | 主持人严格 JSON 解析、合法性校验和保护决策。 |
| `group_chat_host_runtime.py` | 主持人调用 LLM 的运行时包装。 |
| `group_chat_host_messages.py` | 主持人可见消息生成，不做路由判断。 |
| `expert_runtime.py` | 专家回合准备：专家资料、Skill 解析、LLM 和工具运行时构造。 |
| `group_chat_skill_session.py` | 从 `skill_result.next_action` 推导跨轮 Skill 状态。 |
| `group_chat_soft_stop.py` | soft stop 和等待用户规则。 |
| `group_chat_streaming.py` | SSE 事件构造和序列化。 |
| `group_chat_title_meta.py` | 标题刷新和会话元信息更新。 |
| `group_chat_memory_prompt.py`、`group_memory_store.py` | 记忆摘要读取、写入和 Prompt 材料。 |

拆分触发条件：

- 单个函数超过 80 行且混合 2 个以上职责。
- 单个文件超过 600 行且包含可命名的独立业务块。
- 同一字段在 3 个以上函数中被手写解析。
- 既解析请求又写状态又调用 LLM。

### 2.4 Prompt 层

目录：`backend/app/agent/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `group_chat_prompt_builder.py` | 按契约组装 Prompt 块。 |
| `expert_self_awareness.py` | 专家自我认知或身份说明材料。 |
| `group_chat_presentation_rewriter.py` | 展示改写类 LLM 调用。 |
| `platform_prompt_templates.json` | 唯一保存平台内置 Prompt 模板正文。 |
| `platform_prompts.py` | 读取、校验和渲染 `prompt_id` 对应模板；不直接保存大段 Prompt 正文。 |

规则：

- 平台内置 Prompt 正文只能新增到 `platform_prompt_templates.json`，不能写进 runtime、API、工具、schema、测试 fixture 或 Vue 文件。
- Prompt 调用点只能传入 `prompt_id` 和结构化变量，由 Prompt 层返回最终模板或 Prompt 块。
- Prompt builder 只接收结构化输入，不扫描用户目录。
- `debug_*`、执行 trace、真实环境变量和绝对路径不能进入 Prompt 块。

### 2.5 工具和执行层

目录：`backend/app/agent/`、`backend/app/tools/`、`backend/app/mcp/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `tools_for_skill.py` | 按当前 Skill `allowed-tools` 组装 MCP、HTTP API、工作区工具和脚本工具。 |
| `tool_gateway.py` | 工具调用网关、执行上下文和统一返回。 |
| `group_chat_tool_trace.py` | 工具 trace、日志和调试记录。 |
| `group_chat_tool_result_content.py` | 工具结果转用户可见内容。 |
| `tools/run_skill_script.py` | Skill 脚本工具创建和沙箱执行入口。 |
| `tools/http_api_tool.py`、`tools/call_api.py` | 保存型 HTTP API 工具。 |
| `mcp/manager.py`、`mcp/tool_arg_normalizers.py` | MCP 连接管理和工具参数归一化。 |

规则：

- 工具权限只来自当前 Skill，不来自专家旧字段。
- 工具 stdout、stderr、参数和耗时进入 trace 或日志，不进入 `history.json` 消息核心字段。
- 工具结果不能直接决定跨轮路由；需要跨轮状态时必须经过 `skill_result.next_action`。

### 2.6 状态和存储层

目录：`backend/app/session_state/`、`backend/app/core/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `session_state/paths.py` | 会话状态路径计算。 |
| `session_state/store.py` | 原子读写和状态文件存储。 |
| `session_state/service.py` | 会话状态服务和检查点组合操作。 |
| `core/user_context.py`、`core/user_settings_paths.py` | 用户隔离和用户目录路径。 |
| `core/name_based_resources.py` | 资源字段归一化。 |
| `core/resource_store.py` | 资源中心读写。 |

规则：

- 路径计算不做业务判断。
- 存储服务不调用 LLM。
- 资源归一化不做运行时兜底，只负责保存入口的统一格式。

### 2.7 沙箱层

目录：`backend/app/agent/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `sandbox_service.py` | 沙箱服务主入口。 |
| `sandbox_policy_builder.py`、`sandbox_policy_runtime.py` | 沙箱策略构造和运行态。 |
| `sandbox_requirements.py`、`sandbox_requirements_runtime.py`、`sandbox_requirements_installer.py`、`sandbox_requirements_verifier.py` | 依赖声明、安装和校验。 |
| `sandbox_workspace_fs.py`、`sandbox_workspace_ops.py`、`sandbox_workspace_access.py` | 工作区挂载和文件访问。 |

规则：

- 沙箱依赖、镜像策略、工作区挂载和脚本执行不要写进群聊 runtime。
- 依赖预热失败只影响依赖状态，不应偷偷修改 Skill 或会话历史。

## 3. 前端文件边界

### 3.1 API 层

目录：`frontend/src/api/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `base.ts` | API base URL、认证头、通用 fetch。 |
| `chat.ts` | 会话、流式聊天、SSE 解析入口和聊天相关类型。 |
| 新增按域 API 文件 | 当资源、设置或文件 API 继续膨胀时，按业务域拆出。 |

规则：

- 视图组件不得直接拼 `/api/...`。
- SSE 事件名和 payload 类型必须与 `docs/contracts/runtime-interface-contract.md` 一致。
- 非流式 `/chat` 不能生成第二套 `contents` 或顶层 `content` 结构。

### 3.2 工作区页面层

目录：`frontend/src/features/workspace/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `WorkspaceContent.vue` | 工作区页面壳，只组合子组件和 composable。 |
| `components/group-chat/GroupChatComposer.vue` | 输入框、附件、专家选择和发送动作 UI。 |
| `components/group-chat/GroupChatMessages.vue` | 消息列表展示。 |
| `components/group-chat/GroupChatStatusBars.vue` | 运行态、等待用户、邀请提示展示。 |
| `components/group-chat/GroupWorkspacePanel.vue` | 工作区文件面板。 |

必须独立的 composable：

| 文件 | 职责 |
|------|------|
| `useGroupChatStreamRunner.ts` | 发起和停止当前聊天流。 |
| `useGroupStreamEvents.ts` | 处理 `start`、`route`、`progress`、`message`、`end`、`error` 事件。 |
| `useGroupStreamRuntime.ts` | 运行镜像、订阅事件和 stale runtime 展示。 |
| `useGroupOrchestrationState.ts` | `waiting_for_user`、`suggested_next_speaker`、`suggested_add_agent_names` 等编排 UI 状态。 |
| `useGroupMessageList.ts` | 消息列表事实和展示转换。 |
| `useGroupFileReferences.ts` | 附件和工作区文件引用。 |
| `useGroupComposerActions.ts` | 输入区动作。 |

规则：

- Vue 文件不直接解析业务字段，字段转换进入 composable。
- Composable 不从 `message.content` 反推路由或招募。
- 本地 `_streaming` 和 `_streamingStatus` 只能作为页面暂态，不写入 mock、API 或历史。

### 3.3 资源中心和设置层

目录：`frontend/src/features/resources/`、`frontend/src/features/settings/`

必须独立的文件：

| 文件 | 职责 |
|------|------|
| `useScenarioEditor.ts` | 场景编辑字段和保存逻辑。 |
| `useResourceCollections.ts` | 资源集合加载和刷新。 |
| `useBundleImports.ts`、`useZipResourceImports.ts` | 导入导出流程。 |
| `frontend/src/features/resources/mcpConfigContract.ts` | MCP 配置导入导出契约。 |
| `ApiSecretsSettingsView.vue` | 用户级环境变量设置。 |
| `SandboxSettingsView.vue` | 沙箱设置。 |

规则：

- 资源身份字段只按契约保存。
- 缺失引用要展示和保留，不静默清理。
- 导入逻辑与编辑器 UI 分开。

## 4. 测试文件边界

测试按契约边界命名，不按“哪个 bug”命名。

| 范围 | 推荐测试文件 |
|------|--------------|
| 请求和 SSE 契约 | `backend/tests/test_group_chat_stream_protocol.py` |
| 主持人 JSON | `backend/tests/test_group_host_decision.py` |
| 入口路由 FSM | `backend/tests/test_group_orchestration_fsm.py` |
| 消息结构 | `backend/tests/test_message_contracts.py` |
| 资源身份 | `backend/tests/test_name_based_resource_contract.py` |
| 会话 API | `backend/tests/test_sessions_api.py` |
| 前端路由和上下文契约 | `backend/tests/test_frontend_route_and_context_contracts.py` |
| 工作区 E2E | `frontend/e2e/workspace.spec.ts` |
| 资源场景专家 E2E | `frontend/e2e/resources-scenario-expert.spec.ts` |

新增测试应优先复用这些文件；当一个测试文件同时覆盖多个无关子系统时，再按模块拆新文件。

## 5. 重写时的推荐顺序

1. 固定 `docs/contracts/` 中的目标字段。
2. 补 schema 和契约测试。
3. 删除主路径旧字段解析。
4. 拆薄 API 入口。
5. 拆运行时大函数，保留单一主链路。
6. 同步前端 API 类型和 mock。
7. 同步 `docs/design/`、`docs/testing/` 和用户手册中受影响的口径。
8. 运行聚焦测试和构建。

任何一步发现文档冲突，先回到契约文档和设计文档修正，不在代码里新增兼容分支绕过去。
