# 书童四九：程序运行逻辑梳理

本文从「进程如何起来」到「一次对话如何走完」，概括整个仓库的运行逻辑，便于新人建立心智模型。细节与接口以源码及 [runtime-architecture.md](./runtime-architecture.md)、[文档中心](../README.md)、[backend/README.md](../../backend/README.md) 为准。

---

## 1. 系统分层

| 层级 | 技术 | 职责 |
|------|------|------|
| 浏览器 | Vue 3 + Vite + Pinia + Vue Router + Tailwind | 单页应用：登录、主壳、工作区、资源中心、设置；解析 SSE 流式对话 |
| API 服务 | FastAPI（`uvicorn`） | `/api/*`：认证、会话、群聊流、文件、Agent/专家配置、MCP/Skills/LLM 设置 |
| 数据 | 用户目录下的 JSON / Markdown / 文件 | 多租户隔离：每用户独立会话、配置、技能、工作区 |
| 外部 | 兼容 OpenAI 的 LLM HTTP、MCP 子进程、技能脚本子进程 | 推理与工具执行均在服务端 |

---

## 2. 进程与启动顺序

### 2.1 后端（`backend/`）

1. 入口：`python -m app.main` → 加载 `app/main.py`。
2. **环境**：从 `backend/.env` 及当前工作目录再 `load_dotenv` 一次。
3. **生命周期**（`lifespan`）：启动时调用 `ensure_mcp_and_skills_initialized()`，只预热已存在且确有资源的用户目录（有用户 Skill 或 `mcp_servers.json`），加载用户 Skills 与 MCP 配置；不在启动期主动连接 MCP Server。关闭时 `cleanup_all_mcp_runtimes()`，避免 asyncio cancel scope 跨任务问题。
4. **中间件**：CORS，来源由 `CORS_ORIGINS` 控制（默认含 `http://localhost:5173`）。
5. **路由挂载**（均带 `/api` 前缀）：`settings`、`files`、`auth`、`dha`（Agent）、`group_chat`、`sessions`。
6. **生产静态站**：若设置 `STATIC_DIR` 且目录存在，则挂载前端构建产物并做 SPA 回退；否则根路径返回 JSON 提示。
7. **健康检查**：`GET /health`。

默认监听：`0.0.0.0:8000`（直接 `python -m app.main` 时）。

### 2.2 前端（`frontend/`）

1. 开发：`npm run dev` → Vite 默认 `http://localhost:5173`。
2. **代理**：`vite.config.ts` 将 `/api` 转发到 `http://127.0.0.1:8000`，超时 180s，适配长耗时工具调用；若出现 Vite `ECONNREFUSED`，优先确认后端已通过 `python -m app.main` 监听 8000 端口。
3. **入口**：`src/main.ts` 新建 Vue 应用、注册 Pinia 与路由；**全局包装 `fetch`**：若 `localStorage` 存在 `dha_token`，则对所有请求附加 `Authorization: Bearer <token>`。
4. **路由**：`/` → `MainView`（需登录）；`/login` → `LoginView`。`beforeEach` 用 `dha_logged_in === 'true'` 做简单门禁（与 token 并存）。

### 2.3 开发时典型组合

浏览器只访问 **5173**；业务请求走 **`/api`** → Vite 代理 → **8000** FastAPI。生产可合一域名：后端托管静态 + 同机 `/api`。

---

## 3. 身份与数据隔离

1. 用户通过 `/api/auth/login`（或 register）取得 JWT；前端存 `dha_token` 并设置登录标记。
2. 后续 `/api` 请求依赖 **Bearer**；后端 `user_context_dependency` 解析出当前用户名。
3. 所有会话、专家配置、MCP、Skills、工作区路径均在 **`data/users/{user_id}/...`**（根目录由 `SHUTONG_USER_DATA_ROOT` 等配置，见 `backend/README.md`）。
4. 调试可选 `ALLOW_ANONYMOUS_API=1`（**禁止用于生产**）。

---

## 4. 前端：进入主界面之后在做什么

1. **`MainView`**：左侧导航（工作区、资源中心、设置等），右侧为子内容。
2. **工作区**（如 `WorkspaceContent`）：会话列表、消息区、输入框、工作区文件；与专家的实际推理无关，只负责 UI 与请求。
3. **会话数据**：选中会话时 `GET /api/sessions/{id}` 拉元数据与历史消息。
4. **发送消息**：`POST /api/sessions/{id}/chat/stream`，**不等待整段返回**，按 SSE 风格解析事件流（`start` / `content` / `message` / `end` 等），增量更新界面。

---

## 5. 后端：统一会话与流式对话主路径

### 5.1 API 表面

- **会话主入口**：`/api/sessions/*`（列表、新建、读写、删除消息、`chat/stream` 等），实现上与群聊共用存储（见 `sessions.py` 转调 `group_chat`）。
- **Agent（专家）配置**：`/api/agents/*`，专家资源包导入导出沿用 `/api/dha/instances/*`。

### 5.2 编排策略（`next_speaker` 如何决定）

实现集中在 `backend/app/api/group_chat.py` 的 `group_chat_stream`；内存里用 `OrchestrationContext`（`app/agent/orchestrator_state.py`）记录 **阶段** `phase`（如 `planning` / `executing` / `awaiting_user` / `recruiting` / `completed`）等，SSE 的 `end` 事件里也会带 `phase`、`interrupt_reason` 等。

#### 5.2.1 双轨编排与 meta 字段

- **`orchestration_profile`**（会话 meta，取值 **`recruitment` | `scene`**）：
  - **`recruitment`**：新建空会话或「招募房间」语义；主持人侧可向模型提供「可邀请专家列表」，并可能产出 `suggested_add_agent_ids`。
  - **`scene`**：**场景协作**（如资源中心套用场景、写入 `host_config` 后）；不向调度模型注入可邀请名单（`available_to_add_for_prompt` 为空），`finalize_host_scheduler_decision(..., orchestration_profile="scene")` 会强制清空招募相关字段。
  - **缺省迁移**：meta 无该字段时，由 `effective_orchestration_profile` 推断：无场内专家 → `recruitment`；有专家 → `scene`。
  - **升级**：虚拟主持人 + 已配置 `host_config.skill_ids` + 场内有人，且当前为「空/recruitment」时，在 `update_group_session` / `get_group_session` 中会升为 **`scene`**（避免「已套用场景却仍走招募链」）。

- **Skill 会话锁**（跨请求）：`skill_session_owner_id` / `skill_session_skill_id` 由 `group_orchestration_fsm.persist_skill_session_lock` 写入；当用户继续与同一专家推进 Skill、且未显式要求主持人改派时，`resolve_group_entry_route` 可 **`skip_host_dispatch`**，本轮**不调用** `_host_decide_by_agent` / `leader_decide`，直接进入该专家回合（四九不参与本轮用户消息）。

- **待恢复（pending）**：若专家需用户补信息，meta 中 `pending_owner_agent_id` / `pending_skill_id` 等仍用于 `_host_decide_by_agent` 的提示注入；与 Skill 锁配合时，以入口路由判定为准。

#### 5.2.2 调度模型与后处理

- **主持人**：虚拟场景主持人时，由 `_resolve_scene_host_profile` 合成「类 Agent」profile，优先走 **`_host_decide_by_agent`**（主持技能 + `host_config` + `app_settings.host_prompts.host_master_prompt`）。
- **回退**：主持人失败则 **`leader_decide`**（`leader_scheduler.py`），其提示词按 `orchestration_profile` 区分是否含「可邀请新成员」段落。
- **归一化**：`finalize_host_scheduler_decision` 合并招募抑制；若模型误发「可邀请」且被抑制，**固定** `next_speaker=user`（不猜测下一位专家，由下轮四九按流程图再调度）。`normalize_scheduler_decision` 仅做 id 清洗与非法 id 回落。`speak_mode`（manual/auto）**不再**分支后端逻辑，仅可写入 meta 供前端。
- **主持人多 Skill**：`_host_decide_by_agent` 固定使用 `skill_ids` **列表第一项**（可预测），不由关键词路由代选。

#### 5.2.3 有专家时：`if/elif` 决策顺序（源码顺序）

下列为 **互斥分支**（命中一条后同轮内不再走后面的「选下一位」逻辑）：

1. **群内 0 位专家**（在上一节已 `return` 的块）：仅主持人推荐可邀请 id，`end` 等待操作。
2. **`entry_route`**：若本轮需要**走四九**，先 **`clear_skill_session_lock`**（见 `group_orchestration_fsm`）。
3. **`@` 强制点名** `forced_at_mention_agent_id` 且在群内 → 清锁，`next_speaker` 为该专家，`executing`。
4. **Skill 锁短路** `entry_route.skip_host_dispatch` → `next_speaker = direct_expert_id`，**不跑主持人 LLM**。
5. **四九调度（唯一路径）**：`_host_decide_by_agent` 或 `leader_decide` → `finalize_host_scheduler_decision`；若点中专家且无招募，主持人气泡后同流进入专家 `while`；若有 `suggested_add` 则 recruiting 语义。

专家回合内：多位 Skill 的选型由 **`resolve_expert_skill`**（`SkillsLoader` 关键词相关度等）与专家模型择一逻辑完成，与旧版「覆盖 next_speaker / 与 pending 抢专家」的路径无关（该路径已移除）。

**专家多轮与上限**：同一 HTTP 连接内专家可 `continue` 多轮（如 `_has_auto_continue_signal`）；全局有 **`agent_turns`** 上限（如 32）。回合结束可写 Skill 锁、`pending`，并发 `end`。

#### 5.2.4 与第 5.3 节的关系

本节描述 **「轮到谁说话」**；选定 `next_speaker` 之后，专家如何组 Skill/MCP/流式 ReAct，见 **5.3.1 专家回合**。

#### 5.2.5 前端与「建议邀请」条

`WorkspaceContent.vue`：当 **`orchestration_profile === 'scene'`** 时，不再从 `end`/主持消息解析待邀请 id，**不展示**「四九 建议邀请 …」条，避免场景内误招募 UI。

### 5.3 一次 `chat/stream` 的逻辑链（简化）

1. **鉴权** → 绑定用户目录。
2. **加载会话**：元数据（标题、已邀请 `agent_ids`、主持人等）+ 历史消息 JSON；必要时处理 pending / 自动续跑同一专家。
3. **推 `start`**：流开始。
4. **无专家**：可走「仅主持人」路径：主持人模型回复、可能推荐可邀请的专家 id，然后 `message` + `end`。
5. **有专家**：按 **§5.2 编排策略** 决定 `next_speaker` 与阶段；有轮次上限防死循环。
6. **专家回合**：见下节「5.3.1 专家回合（实现要点）」。
7. **推事件**：`content` 为增量打字；工具前可有友好提示；最终合并为一条助手 **`message`**；落盘历史与会话 `updated_at`。
8. **群聊记忆**（若开启）：可向工作区 `memory/` 写日志、归档、事实表，供下一轮派发上下文（见 `group_memory_store.py`）。
9. **推 `end`**：带阶段 `phase`、是否等待用户、`interrupt_reason` 等，前端据此决定是否展示表单或继续。

编排阶段与 `OrchestrationPhase` 的对应关系见 [runtime-architecture.md](./runtime-architecture.md) 中的状态机示意。

### 5.3.1 专家回合（实现要点）

以下对应 `group_chat_stream` 中选中某位专家后的路径，源码以 `backend/app/api/group_chat.py`、`backend/app/agent/tools_for_skill.py`、`backend/app/agent/skill_agent_runtime.py`、`backend/app/agent/simple_agent.py` 为准。

1. **按 `agent_id` 读配置**
   专家列表来自当前用户的 `data/users/{user_id}/config/dha_instances.json`（`load_agent_instances()`），流内用 `agent_id` 映射到完整一条专家对象（`name`、`role`、`system_prompt`、`skill_ids`、`mcp_server_ids`、`llm_provider_id`、`file_capabilities`、`url_capability` 等）。若该 `agent_id` 不存在，编排会中断，不继续组工具。

2. **组装 LLM**
   `_get_llm_for_agent`：若专家配置了非空 **`llm_provider_id`** 则用该 provider；否则使用应用设置中的 **`default_llm`**（如缺省 `qwen`），再结合 `llm_providers` 与密钥构造可调用客户端（`get_llm_from_config`）。

3. **本轮 Skill 与工具列表**
   - **选型**：`resolve_expert_skill` 得到本轮 **`resolved_skill_id`** 与 Skill 正文——无 `skill_ids` 时回退 `default`；仅一个 Skill 时直接用；多个 Skill 时结合讨论目标、最近用户消息等与 `SkillsLoader` 的打分/路由策略选型。
   - **MCP**：`build_tools_for_group_chat(agent_profile, workspace_id=会话 id, resolved_skill_id=…)` 仅加载 **`get_mcp_servers_for_skill(resolved_skill_id)`** 允许的服务；若专家配置了 **`mcp_server_ids`**，再与上式**取交集**，做实例级收紧；按需 `ensure_servers_loaded` 后从 `MCPToolManager` 取工具（名通常带 server 前缀）。
   - **工作区**：内置读/写/编辑/删/改名等，按专家的 **`file_capabilities`** 过滤；工作区根与会话绑定。
   - **HTTP**：`call_api` 仅在 `url_capability` 为真时附加（默认常为真）。
   - **脚本**：对 `skill_ids` 中磁盘上存在 `SKILL.md` 的每项注入 **`run_skill_script_<规范化 skill_id>`**，在会话工作区内执行技能脚本。
   - 最后经 **`wrap_filesystem_tools`** 等与文件系统相关的包装，与实现一致。

4. **Skill 正文与专家人设**
   注入模型侧的不只是 SKILL 文件：在 `resolved_skill_id` 对应正文前，会拼接专家的 **`system_prompt`** 与 **`role`**（「你的角色：…」），再交给 `create_skill_execution_agent`。

5. **构造用户侧提示**
   - **讨论目标 `discussion_goal`**：一般取**首条用户消息**经规范化后的摘要；若无则使用占位「待用户提出讨论主题」。
   - **默认用户内容**：包含「群聊讨论目标」「最近讨论」（由历史消息转成的上下文字符串）；若本次请求带 **`custom_prompt`**，仅在**本轮请求中第一位专家**消耗一次。
   - 若内容中已含「最近讨论 / 历史对话」等区块，则避免再重复追加同一段上下文。
   - **`extra_system_prompt`** 在群聊流中通常为空；全局 system 已废弃，主持人人设改在主持人 Agent 与主持技能上维护。

6. **流式 Agent 执行（步进语义）**
   产品形态是「模型一步 → 需要则工具一步 → 直到不再请求工具」的 ReAct 循环，当前实际执行器是 **`SimpleAgent.astream`**：对外事件类型为 **`agent_step`** / **`tool_step`** / **`final_step`**（对应文档里常说的模型步 / 工具步 / 结束步）。`create_skill_execution_agent` 将技能全文、工具名与说明写入系统提示并 `bind_tools`；群聊侧订阅流事件，将 **`agent_step`** 中的文本以 SSE **`content`** 增量推送，**`tool_step`** 多用于内部追踪（避免把原始工具输出直接灌进气泡）。超时等由环境变量（如 `LLM_AGENT_TIMEOUT`）控制。

### 5.4 MCP 与 Skills 在何时参与

- **MCP**：配置在用户 `mcp_servers.json`；`MCPToolManager`（`app/mcp/manager.py`）按用户维护连接，进程退出时清理；本机 stdio 入口脚本在 `app/mcp/stdio/`（配置里写相对 backend 的路径，如 `app/mcp/stdio/file_reader_mcp.py`）；工具名通常带 server 前缀。
- **Skills**：`resources/skills/{skill_id}/SKILL.md` 由 `SkillsLoader` 解析缓存；多 Skill 时可本地关键词相关度选型（见 `backend/README.md`）；脚本通过 `run_skill_script_*` 在用户会话工作区内执行。

应用启动**不会**预连所有 MCP；首次需要时在请求路径内连接（与 `lifespan` 中的设计一致）。

---

## 6. 设置与资源中心（概念位置）

- **应用设置、LLM Provider、默认模型**：经 `/api/settings` 系列路由，落盘如 `app_settings.json`。
- **专家、场景（session_presets）、技能、MCP、文件**：前端资源中心各子页对应后端 settings / files / dha 等接口；「场景」复用 `session_presets`，不单独建表。

---

## 7. 文档与代码对照表

| 主题 | 建议阅读 |
|------|----------|
| 框架级前后端协作与 SSE | [runtime-architecture.md](./runtime-architecture.md) |
| 数据目录与认证约定 | [user-resource-store/README.md](user-resource-store/README.md) |
| 后端环境变量与接口迁移说明 | [backend/README.md](../../backend/README.md) |
| FastAPI 入口与静态站 | `backend/app/main.py` |
| 会话路由 | `backend/app/api/sessions.py` |
| 群聊流与编排实现 | `backend/app/api/group_chat.py` |
| 编排入口路由 / Skill 锁 | `backend/app/agent/group_orchestration_fsm.py` |
| 主持人决策后处理（scene/recruitment） | `backend/app/core/scene_scheduler.py` |
| 回退调度器提示 | `backend/app/agent/leader_scheduler.py` |
| LLM 客户端 | `backend/app/agent/llm_client.py` |
| 工具组装 | `backend/app/agent/tools_for_skill.py` |
| 技能执行 Agent / 流式步进 | `backend/app/agent/skill_agent_runtime.py`、`backend/app/agent/simple_agent.py` |
| 前端路由与 fetch | `frontend/src/main.ts`、`frontend/src/router/index.ts` |

---

## 8. 小结

**书童四九**是一条「浏览器 Vue ↔ FastAPI ↔ 用户目录 + LLM + MCP/Skills」的私有化 Agent 平台链路：身份决定目录；会话 API 统一承载单人/多人形态；对话核心在 **`group_chat` 的流式编排**；工具与技能均在服务端、当前用户上下文中执行。若某一步行为与本文不一致，以当前仓库代码为准。
