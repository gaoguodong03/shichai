# 项目结构文档

## 概述

本文档说明 DHA 项目当前目录结构与文件职责，便于理解主流程与扩展点。

## 整体结构

```
DHA/
├── backend/                 # Python 后端
│   ├── app/
│   │   ├── main.py          # FastAPI 入口组装（create_app / health / 启动）
│   │   ├── api/             # 路由：sessions、group_chat、settings、files、auth、dha、public_scenario
│   │   ├── agent/           # ReAct 工作流、工具组装、技能选择、LLM 客户端
│   │   ├── core/            # 生命周期、运行环境、静态挂载、用户上下文、安全、用户存储
│   │   ├── mcp/             # MCP 管理、工具参数归一化
│   │   ├── skills/          # Skills 加载（SKILL.md 扫描与内容获取）
│   │   └── tools/           # 内置工具：export_session、run_skill_script、call_api、filesystem 包装等
│   ├── config/              # 配置（若有）
│   ├── data/                # 会话/群聊等数据目录（运行时生成）
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
├── docs/                     # 文档（architecture、features、development、next-plan 等）
├── config/                   # 项目级配置（如 mcp_servers.json、models.json）
└── README.md
```

## 后端结构详解

### `backend/app/main.py`

- FastAPI 应用入口；注册路由：`sessions`、`settings`、`files`、`auth`、`dha`、`group_chat`（均挂载在 `/api` 下）。
- 会话列表与流式对话由 **`sessions`** 模块提供（如 `/api/sessions`、`/api/sessions/{id}/chat/stream`）；`group_chat` 内含实现函数与会话归档等辅助路由。

### `api/`

| 文件 | 职责 |
|------|------|
| `group_chat.py` | 会话核心实现：主持人调度、`group_chat_stream`、`build_tools_for_group_chat`、流式 SSE、历史/meta 存储；并暴露 `create_session_internal`、`export_session_to_markdown` 等供 `sessions` 复用；另含 `GET /sessions/{id}/archive`。 |
| `sessions.py` | **统一会话 API**：`GET/POST /sessions`、`GET/PUT/DELETE /sessions/{id}`、`POST /sessions/{id}/chat/stream`、`POST /sessions/{id}/export`；与 group_chat 共用存储，新对话即「仅主持人」会话。 |
| `settings.py` | MCP/Skills/App 配置：`/api/settings/mcp`、`/api/settings/skills`、`/api/settings/app` 等。 |
| `files.py` | Agent 工作区文件：workspace 路径、上传/下载/列表/重命名/读取。 |
| `auth.py` | 登录/注册等认证。 |
| `dha.py` | DHA 实例 CRUD：`/api/dha/instances`。 |

### `agent/`

| 文件 | 职责 |
|------|------|
| `skill_agent_runtime.py` | 技能执行 Agent 运行时：构建系统提示、绑定工具 schema、驱动 `SimpleAgent` 的 agent/tool/final 步进。 |
| `tools_for_skill.py` | **工具组装**：`build_tools_for_group_chat(all_tools, dha, workspace_id)`，按 DHA 的 mcp_server_ids/skill 依赖过滤 MCP + 只读 file-reader/filesystem + call_api + 每 skill 的 `run_skill_script_<skill_id>`。 |
| `skill_selector.py` | 技能选择：根据用户消息与 name+description 选出 skill_id。 |
| `llm_client.py` | LLM 客户端封装（如 Qwen）。 |
| `leader_scheduler.py` | 群聊主持人调度。 |
| `types.py` | Agent 状态等类型定义。 |

### `core/`

| 文件 | 职责 |
|------|------|
| `init.py` | **应用级初始化**：`ensure_mcp_and_skills_initialized()`，启动时扫描已存在用户并加载各自 MCP + Skills；后续会话与群聊共用该用户运行时。 |
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
| `volces_image_cli_lib.py` | 火山图像等辅助。 |

当前项目**未使用**独立 `models/`、`storage/`、`utils/` 目录；数据与持久化分散在 api/skills/core 及本地文件（如 `data/users/<用户>/sessions`）。

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
- **项目级**：`config/mcp_servers.json`、`config/models.json`；Skills 为每用户 `data/users/<用户名>/skills/`。

## 命名与组织原则

- **后端**：文件/函数 `snake_case`，类 `PascalCase`，常量 `UPPER_SNAKE_CASE`。
- **前端**：`views/` 仅保留顶层布局壳；业务页面放入 `features/<domain>/`，公共能力放入 `api/`、`components/`、`composables/`。
- **单一职责**：主流程在 api/agent，启动横切逻辑在 core，工具与归一化在 tools/mcp；文档与实现保持一致，过时描述及时修正。

## 相关文档

- [运行流程](runtime-flow.md)：两阶段、单聊主流程、初始化、流式。
- [步骤类型与工具](step-types-and-tools.md)：MCP / script / service / export / 只读文件等执行路径。
- [镜像与依赖边界](images-and-dependencies.md)：主应用、OpenSandbox、技能沙箱与用户依赖的职责划分。
- [需求说明与验收测试](../需求说明与验收测试.md)：产品需求、模块验收点与回归测试建议。
