# 项目结构文档

## 概述

本文档说明书童四九项目当前目录结构与文件职责，便于理解主流程与扩展点。

## 整体结构

```
shichai/
├── backend/                 # Python 后端
│   ├── app/
│   │   ├── main.py          # FastAPI 入口组装（create_app / health / 启动）
│   │   ├── api/             # 路由：sessions、group_chat、settings、files、auth、agents
│   │   ├── agent/           # ReAct 工作流、专家 Skill 选型、工具组装、LLM 客户端
│   │   ├── core/            # 生命周期、运行环境、静态挂载、用户上下文、安全、用户存储
│   │   ├── mcp/             # MCP 管理、工具参数归一化
│   │   ├── skills/          # Skills 加载（SKILL.md 扫描与内容获取）
│   │   └── tools/           # 内置工具：export_session、run_skill_script、call_api、filesystem 包装等
│   ├── config/              # 认证用户模板等本地配置
│   ├── data/                # 用户运行数据目录（运行时生成，不提交）
│   ├── requirements.txt
│   └── .env / .env.example
├── frontend/                 # Vue 3 前端
│   ├── src/
│   │   ├── views/           # 顶层壳页面：MainView
│   │   ├── features/        # 业务域页面：auth、workspace、resources、settings
│   │   ├── components/     # MCPConfig、SkillsConfig、LLMConfig
│   │   ├── composables/    # useEventSource、useTheme
│   │   ├── router/
│   │   └── theme/
│   ├── package.json、vite.config.ts、tsconfig.json
│   └── .env.example
├── docs/                     # 文档中心，按 requirements/architecture/testing 等分类
├── docker/                   # Skill 沙箱镜像等 Docker 构建文件
├── scripts/                  # 一键回归、UI 测试等脚本
└── README.md
```

## 后端结构详解

### `backend/app/main.py`

- FastAPI 应用入口；注册路由：`sessions`、`settings`、`files`、`auth`、`agents`、`group_chat`（均挂载在 `/api` 下）。
- 会话列表与流式对话由 **`sessions`** 模块提供（如 `/api/sessions`、`/api/sessions/{id}/chat/stream`）；`group_chat` 内含实现函数与会话归档等辅助路由。

### `api/`

| 文件 | 职责 |
|------|------|
| `group_chat.py` | 会话核心实现：主持人调度、`group_chat_stream`、`build_tools_for_group_chat`、流式 SSE、历史/meta 存储；并暴露 `create_session_internal`、`export_session_to_markdown` 等供 `sessions` 复用；另含 `GET /sessions/{id}/archive`。 |
| `sessions.py` | **统一会话 API**：`GET/POST /sessions`、`GET/PUT/DELETE /sessions/{id}`、`POST /sessions/{id}/chat/stream`、`POST /sessions/{id}/export`；与 group_chat 共用存储，新对话即「仅主持人」会话。 |
| `settings_skills.py` | Skill 配置与导入导出主路由。 |
| `settings_skill_store.py` / `settings_skill_parts.py` | Skill 文件读写、分片资源管理。 |
| `settings_mcp.py` | MCP Server 配置、工具列表、测试调用与导入导出。 |
| `settings_presets.py` | 场景/会话预设与场景资源包导入导出。 |
| `settings_app.py` | 应用设置和主持人配置。 |
| `settings_secrets.py` | 用户密钥配置。 |
| `sandbox_settings.py` | 用户沙箱版本和 requirements 设置。 |
| `files.py` | Agent 工作区文件：workspace 路径、上传/下载/列表/重命名/读取。 |
| `auth.py` | 登录/注册等认证。 |
| `agents.py` | Agent 配置、专家资源包导入导出 API。 |

### `agent/`

| 文件 | 职责 |
|------|------|
| `skill_agent_runtime.py` | 技能执行 Agent 运行时：构建系统提示、绑定工具 schema、驱动 `SimpleAgent` 的 agent/tool/final 步进。 |
| `tools_for_skill.py` | **工具组装**：`build_tools_for_group_chat(agent_profile, workspace_id)`，按 Agent 的 mcp_server_ids/skill 依赖过滤 MCP + 只读 file-reader/filesystem + call_api + 每 skill 的 `run_skill_script_<skill_id>`。 |
| `expert_runtime.py` | 专家回合入口：根据专家绑定 Skill、用户输入和会话状态选定 Skill，并组装工具。 |
| `llm_client.py` | LLM 客户端封装（如 Qwen）。 |
| `leader_scheduler.py` | 群聊主持人调度。 |
| `orchestrator_state.py` | 编排状态、阶段与中断原因定义。 |

### `core/`

| 文件 | 职责 |
|------|------|
| `init.py` | **应用级初始化**：`ensure_mcp_and_skills_initialized()`，启动时只预热已有 Skill 或 MCP 配置的用户；MCP 只读配置，不在启动期主动连接工具。 |
| `user_context.py` | 当前用户上下文（依赖注入）。 |
| `security.py` | 安全与认证依赖。 |
| `users_store.py` | 用户存储。 |

### `mcp/`

| 文件 | 职责 |
|------|------|
| `manager.py` | MCP Server 连接与管理；`get_tools()`；`normalize_mcp_kwargs_for_call` 委托给 `tool_arg_normalizers`。 |
| `tool_arg_normalizers.py` | MCP 工具参数归一化（按 server_id/tool_name 分发），供 manager、graph 等复用。 |

### `skills/`

| 文件 | 职责 |
|------|------|
| `loader.py` | 扫描用户 `skills_dir`、读取 SKILL.md；业务用 `get_skills_loader_for_user`；`get_skills_loader()` 仅兼容无用户上下文场景。 |

### `tools/`

| 文件 | 职责 |
|------|------|
| `export_session.py` | `create_export_session_tool(session_id)` → `export_session_to_md`。 |
| `run_skill_script.py` | `create_run_skill_script_tool(skill_id)` → `run_skill_script`。 |
| `call_api.py` | 全局 `call_api` 工具。 |
| `filesystem_session_wrapper.py` | `wrap_filesystem_tools(tools, session_id)`，按会话限定工作区路径。 |
| `read_file.py` | 遗留读文件工具（已由 MCP file-reader/filesystem 替代，若仍存在则仅兼容）。 |
| `write_workspace_file.py` | 写工作区文件（若被其他模块使用）。 |

当前项目**未使用**独立 `models/`、`storage/`、`utils/` 目录；数据与持久化分散在 api/skills/core 及本地文件（如 `backend/data/users/{user_id}/sessions`）。

## 前端结构详解

### `frontend/src/`

- **views/**：顶层布局壳，目前保留 `MainView.vue` 与对应样式。
- **features/**：按业务域组织页面，包含 `auth/`、`workspace/`、`resources/`、`settings/`。
- **components/**：MCPConfig、SkillsConfig、LLMConfig。
- **api/**：统一 API 层。`base.ts` 提供 `apiBase`（默认 `/api`）、`apiUrl`、`apiFetch`；`chat.ts`（流式请求、导出、技能列表）、`settings.ts`（Skills/MCP CRUD）、`files.ts`（工作区文件列表、下载链接）。视图与组件通过 `@/api` 调用，便于代理与生产同源。
- **composables/**：useEventSource（SSE）、useTheme。
- **router/**：路由定义。
- **theme/**：主题样式。

## 配置文件与数据

- **后端**：`.env`、`requirements.txt`、`pyproject.toml`；会话/群聊等数据多在 `backend/data/` 下以 JSON 等形式存储。
- **前端**：`package.json`、`vite.config.ts`、`tsconfig.json`、`.env.example`。
- **用户运行数据**：`backend/data/users/{user_id}/resources/`、`sessions/`、`config/`。其中 Skill 位于 `resources/skills/{skill_id}/`。
- **沙箱镜像**：`docker/skill-sandbox/`。
- **脚本入口**：`scripts/test-layer1.sh`、`scripts/test-ui-flow.sh`、`scripts/test-full-flow.sh`。

## 文档目录

| 目录 | 职责 |
|------|------|
| `docs/requirements/` | 用户需求、验收标准、需求追踪 |
| `docs/architecture/` | 架构、API、运行链路、项目结构 |
| `docs/testing/` | 第一层回归、上线前测试、全流程业务测试 |
| `docs/user-manual/` | 用户说明、上线验收手册、截图和 PDF |
| `docs/skills/` | Skill、脚本路径、沙箱工具接口规范 |
| `docs/operations/` | 部署和运行约束 |
| `docs/project/` | 项目工作清单 |
| `docs/presentations/` | 讲稿、PPT、演示素材 |
| `docs/superpowers/` | 历史规格和实施计划 |

## 命名与组织原则

- **后端**：文件/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`。
- **前端**：`views/` 仅保留顶层布局壳；业务页面放入 `features/<domain>/`，公共能力放入 `api/`、`components/`、`composables/`。
- **单一职责**：主流程在 api/agent，启动横切逻辑在 core，工具与归一化在 tools/mcp；文档与实现保持一致，过时描述及时修正。

## 相关文档

- [运行流程概览](runtime-flow-overview.md)：进程启动、会话主流程、初始化、流式。
- [运行架构说明](runtime-architecture.md)：MCP / script / service / export / 只读文件等执行路径。
- [镜像与依赖边界](images-and-dependencies.md)：主应用、OpenSandbox、技能沙箱与用户依赖的职责划分。
- [需求说明与验收测试](../requirements/acceptance-and-tests.md)：产品需求、模块验收点与回归测试建议。
