# 书童四九需求说明与验收测试

## 1. 文档目标

本文用于沉淀当前产品的核心需求、模块边界与可执行验收点。后续新增功能、重构或上线前回归测试，应优先对照本文更新测试清单。

本文承接 `docs/requirements/user-requirements.md` 中的 UR 编号，将用户需求拆解到模块验收点、自动化测试和手工验收入口。若新增或调整用户需求，应先更新用户需求文档，再同步更新本文的追踪矩阵。

## 2. 产品定位

书童四九是一个多用户隔离的 Agent 对话与工具平台，支持用户管理自己的专家（DHA）、场景、技能（Skills）、MCP 工具、LLM 配置与工作区文件，并通过统一会话完成主持人调度、专家协作、工具调用与结果沉淀。

## 3. 用户角色

| 角色 | 目标 | 关键能力 |
|------|------|----------|
| 普通用户 | 使用专家与技能完成任务 | 登录、创建会话、上传文件、调用工具、查看结果 |
| 配置用户 | 维护个人资源 | 管理 DHA、Skills、MCP、LLM、沙箱与密钥 |
| 运维/部署者 | 保证服务稳定运行 | 配置环境变量、镜像、OpenSandbox、健康检查 |
| 开发/测试者 | 安全迭代系统 | 按模块开发、运行回归、验证接口契约 |

## 4. 用户需求追踪矩阵

| 用户需求 | 业务模块 | 自动化验证入口 | 手工验收入口 | 当前口径 |
|----------|----------|----------------|--------------|----------|
| UR-01 账号与用户隔离 | 认证、用户资源根、受保护路由 | `test_auth_sqlite.py`、`test_sessions_api.py`、`frontend/e2e/auth.spec.ts` | 登录、刷新、跨账号资源隔离 | P0 必测 |
| UR-02 工作区与统一会话 | 会话 API、工作区、SSE 协议 | `test_sessions_api.py`、`test_group_chat_stream_protocol.py`、`test_frontend_business_flows.py`、`frontend/e2e/workspace.spec.ts` | 新建会话、发送消息、上传/引用文件、刷新恢复 | P0 必测 |
| UR-03 主持人与专家协作 | 调度 FSM、主持人决策、专家 runtime | `test_group_orchestration_fsm.py`、`test_scene_scheduler.py`、`test_host_takeover.py`、`test_expert_runtime.py` | 普通会话推荐专家、场景会话固定名单、`@专家` 路由 | P0 必测 |
| UR-04 资源中心 | 场景、专家、Skill、MCP、LLM、文件配置 | `test_dha_api.py`、`test_frontend_business_flows.py`、`frontend/e2e/resources-*.spec.ts` | 资源中心增删改查、保存后会话可用 | P0 必测 |
| UR-05 Skill 与脚本执行 | Skill 契约、脚本工具、沙箱挂载 | `test_file_ref_and_gateway.py`、`test_group_chat_skill_script_cli_flow.py`、`test_skill_agent_tool_resolution.py` | 绑定 Skill 的专家执行脚本，缺依赖时可诊断 | P0 必测 |
| UR-06 MCP 工具能力 | MCP 配置、工具权限、工具网关 | `test_file_ref_and_gateway.py`、`test_skill_agent_tool_resolution.py`、`test_frontend_business_flows.py` | 新增 MCP、授权专家调用、断连/鉴权错误可见 | P0 必测 |
| UR-07 沙箱运行环境 | OpenSandbox、requirements、镜像选择 | `test_sandbox_service.py`、`test_lifespan.py`、`test_file_ref_and_gateway.py` | 普通版/Playwright 版沙箱、依赖安装、超时诊断 | P0 必测 |
| UR-08 工作区文件管理 | 工作区文件 API、文件引用、路径保护 | `test_workspace_files.py`、`test_file_ref_and_gateway.py`、`test_frontend_business_flows.py` | 上传、预览、编辑、下载、专家生成文件落盘 | P0 必测 |
| UR-09 导出与导入 | 资源包导出、ZIP 导入、冲突预览 | `test_bundle_import_api.py`、`test_scenario_bundle.py`、`test_expert_bundle.py`、`frontend/e2e/resources-*.spec.ts` | 场景/专家/Skill 导出导入、冲突确认、依赖提示 | P1 必测 |
| UR-10 模型、密钥与个人设置 | LLM、密钥、主题、账号安全 | `test_llm_config.py`、`test_frontend_business_flows.py`、`frontend/e2e/settings.spec.ts` | 保存模型、密钥脱敏、主题和账号安全设置 | P1 必测 |
| UR-11 部署与运维 | 健康检查、Docker/1Panel、日志诊断 | `test_lifespan.py`、`test_sandbox_service.py`、前端构建 | `/health`、容器启动、OpenSandbox 可达、日志关键词 | P1 上线必测 |

## 5. 核心业务模块

### 5.1 认证与用户隔离

对应需求：UR-01

**需求**
- 用户可以登录系统，未登录访问受保护页面时跳转登录页。
- 后端 API 通过当前用户上下文隔离配置、会话、工作区、Skills 与沙箱资源。
- 生产环境不应依赖匿名访问。

**验收点**
- 未登录访问 `/`、`/workspace`、`/resources/*`、`/settings/*` 会跳转 `/login?redirect=...`。
- 登录后刷新页面仍保持登录态。
- A 用户不能读取或修改 B 用户的会话、文件、Skills 与配置。
- `ALLOW_ANONYMOUS_API=0` 时，无 Token 请求受保护 API 被拒绝。

### 5.2 统一会话与群聊协作

对应需求：UR-02、UR-03

**需求**
- 用户可以创建、查看、更新、删除会话。
- 会话支持普通输入和从已导入场景创建协作会话。
- 会话流式返回专家输出、工具调用状态、主持人调度与最终结果。
- 会话历史与元信息可持久化并恢复。

**验收点**
- `GET /api/sessions` 返回当前用户会话列表。
- `POST /api/sessions` 可创建新会话，并生成唯一 `session_id`。
- `POST /api/sessions/{id}/chat/stream` 返回符合前端消费约定的 SSE 事件。
- 刷新页面后，历史消息、成员、工作区文件引用仍可展示。
- 删除会话后，列表不再显示该会话，且不能继续向该会话发消息。

### 5.3 DHA 专家管理

对应需求：UR-03、UR-04

**需求**
- 用户可以创建、编辑、删除 DHA 专家实例。
- 专家可绑定 Skills、MCP 工具、头像与提示词配置。
- 专家配置可被会话调度与工具组装模块读取。

**验收点**
- DHA 列表只展示当前用户自己的专家。
- 修改专家名称、描述、技能绑定后，新会话使用最新配置。
- 删除专家后，资源中心列表同步更新；历史会话不应崩溃。
- 导入专家包时，非法结构或冲突配置给出明确错误。

### 5.4 Skills 管理与脚本执行

对应需求：UR-04、UR-05、UR-07

**需求**
- 系统扫描每个用户自己的 Skills 目录。
- 每个 Skill 以 `SKILL.md` 描述能力，可包含脚本与依赖。
- Agent 根据任务选择 Skill，并通过沙箱执行脚本。
- 脚本执行应有超时、网络、路径与资源限制。

**验收点**
- Skills 列表能展示当前用户已安装 Skill。
- 缺失 `SKILL.md`、非法 frontmatter、脚本契约不符合要求时能被校验发现。
- 执行脚本时，输出、错误、超时和原始结果能回传到会话气泡。
- 默认情况下，未授权网络访问被沙箱策略拦截。
- 每个用户使用自己的工作区挂载与沙箱资源。

### 5.5 MCP 工具管理

对应需求：UR-04、UR-06、UR-10

**需求**
- 用户可以配置 MCP Server。
- 系统在启动或用户上下文加载时初始化可用 MCP 工具。
- Agent 只获得当前专家配置允许的 MCP 工具。
- MCP 断连时应可重连或给出可诊断错误。

**验收点**
- 新增、编辑、删除 MCP 配置后，资源中心显示一致。
- 无权限或未绑定的 MCP 工具不会出现在专家可用工具集中。
- 工具参数归一化后，常见参数别名能正确调用。
- 远端 MCP 断连时，日志包含 server/tool 维度信息。

### 5.6 工作区文件

对应需求：UR-02、UR-08

**需求**
- 用户可以上传、下载、预览、编辑、重命名与删除工作区文件。
- 会话可引用工作区文件，工具只在允许路径内读写。
- 文本、图片、Office/PDF 等文件应尽量提供可预览体验。

**验收点**
- 文件列表与详情页展示文件名、类型、大小与更新时间。
- 文本文件可以预览与保存修改。
- 路径穿越（如 `../`）不能访问工作区外文件。
- Agent 生成的新文件会出现在对应会话/用户工作区。

### 5.7 场景导入导出

对应需求：UR-04、UR-09

**需求**
- 用户可以导出场景包，并在其他账号中通过 ZIP 资源包导入。
- 导入场景包时需处理依赖、冲突与预览。
- 不再提供公开分享链接、分享预览页或公共分享 API。

**验收点**
- 场景导出包包含必要的专家、技能引用与会话配置。
- 导入前可预览包内容与冲突项。
- 资源包结构错误、依赖缺失或冲突时返回明确错误。
- 导入完成后，场景、专家、技能与工具配置可在对应资源中心栏目查看。

### 5.8 LLM、密钥与应用设置

对应需求：UR-10

**需求**
- 用户可以配置 LLM Provider、模型与 API Key。
- API Key 等敏感配置不应在前端明文泄露。
- 应用设置、主题、偏好与账号安全配置应拆分管理。

**验收点**
- LLM 配置保存后，新会话使用最新 Provider。
- 前端列表不展示完整密钥，只展示脱敏信息或状态。
- 主题切换后刷新页面仍保持选择。
- 修改密码或安全配置后，旧凭据按预期失效。

### 5.9 沙箱与部署运行

对应需求：UR-07、UR-11

**需求**
- 后端启动时加载 `.env`，应用必要默认环境变量。
- 本地开发可自动探测并启动 OpenSandbox。
- 生产部署通过固定镜像、健康检查与静态前端挂载运行。

**验收点**
- `/health` 返回 `{ "status": "ok" }`。
- `STATIC_DIR` 存在时，根路径返回前端 `index.html`，非 API 路由走 SPA fallback。
- `STATIC_DIR` 不存在时，根路径返回 API 信息。
- OpenSandbox 不可达时，本地启动流程给出可读诊断。

## 6. 非功能需求

| 类别 | 要求 | 验收方式 |
|------|------|----------|
| 安全 | 用户数据隔离、路径白名单、SSRF 防护、密钥脱敏 | 单元测试 + 手工攻击用例 |
| 稳定性 | MCP 生命周期在同一任务初始化/清理，沙箱错误可诊断 | 后端测试 + 日志检查 |
| 可维护性 | 入口薄、模块边界清晰、前端按业务域组织 | 代码审查 + 目录检查 |
| 可测试性 | 核心 API、校验器、调度器、工具网关有回归测试 | `pytest` 与前端构建 |
| 可部署性 | Docker/1Panel 配置清晰，构建产物不进仓库 | 部署演练 + git 检查 |

## 7. 模块化测试建议

### 7.1 后端测试分层

| 层级 | 范围 | 推荐命令 |
|------|------|----------|
| 配置/校验层 | session preset、DHA import、Skill contract | `pytest tests/test_session_preset_validate.py tests/test_dha_import_validate.py` |
| 核心编排层 | FSM、scheduler、orchestrator reducer/audit | `pytest tests/test_group_orchestration_fsm.py tests/test_scene_scheduler.py tests/test_orchestrator_audit.py` |
| 工具/沙箱层 | gateway、workspace、sandbox service | `pytest tests/test_file_ref_and_gateway.py tests/test_workspace_files.py tests/test_sandbox_service.py` |
| API 层 | auth、sessions、bundle import/export | `pytest tests/test_auth_sqlite.py tests/test_sessions_api.py tests/test_bundle_import_api.py` |
| 集成层 | group chat stream、skill script CLI flow | `pytest tests/test_group_chat_stream_protocol.py tests/test_group_chat_skill_script_cli_flow.py` |

### 7.2 前端测试/验证分层

| 层级 | 范围 | 推荐方式 |
|------|------|----------|
| 类型构建 | API 类型、组件引用、路由引用 | `npm run build` |
| 页面冒烟 | 登录、工作空间、资源中心、设置 | 浏览器手工检查 |
| 流式交互 | 会话发送、SSE 消息、工具结果展开 | 本地联调 OpenSandbox |
| 文件体验 | 上传、预览、编辑、下载 | 工作区手工用例 |

## 8. 上线前回归清单

- 后端：运行核心 `pytest`，确认无新增失败。
- 前端：运行 `npm run build`，确认路由与组件引用无断裂。
- 数据：确认仓库不包含 `__pycache__`、`.DS_Store`、`.artifacts`、备份包、用户运行输出。
- 部署：确认 `Dockerfile`、`docker-compose.1panel.yml`、沙箱镜像 tag 与环境变量一致。
- 安全：确认匿名 API、网络访问、SSRF 绕过开关未在生产开启。
- 文档：新增或变更模块时，同步更新本文与 `docs/architecture/project-structure.md`。
