# 程序运行逻辑与接口契约统一说明

本文用于统一「一次会话请求到底怎么跑」以及「跳转和字段依赖应该由谁负责」。排查字段错位、主持人误跳转、专家续跑断链、前后端 mock 不一致时，先按本文定位。

本文以当前源码为准，重点入口：

- 后端会话 API：[`backend/app/api/sessions.py`](../../backend/app/api/sessions.py)
- 会话 CRUD / 事件流：[`backend/app/agent/group_session_service.py`](../../backend/app/agent/group_session_service.py)
- 会话状态存储：[`backend/app/api/group_chat_state.py`](../../backend/app/api/group_chat_state.py)
- 群聊运行时：[`backend/app/agent/group_chat_runtime.py`](../../backend/app/agent/group_chat_runtime.py)
- 入口路由与 Skill 锁：[`backend/app/agent/group_orchestration_fsm.py`](../../backend/app/agent/group_orchestration_fsm.py)
- 主持人严格输出：[`backend/app/agent/group_host_decision.py`](../../backend/app/agent/group_host_decision.py)
- 主持人后处理：[`backend/app/core/scene_scheduler.py`](../../backend/app/core/scene_scheduler.py)
- 专家运行时：[`backend/app/agent/expert_runtime.py`](../../backend/app/agent/expert_runtime.py)
- 工具组装：[`backend/app/agent/tools_for_skill.py`](../../backend/app/agent/tools_for_skill.py)
- Skill Agent 工具循环：[`backend/app/agent/skill_agent_runtime.py`](../../backend/app/agent/skill_agent_runtime.py)
- 前端流式请求：[`frontend/src/api/chat.ts`](../../frontend/src/api/chat.ts)
- 前端编排状态：[`frontend/src/features/workspace/composables/useGroupOrchestrationState.ts`](../../frontend/src/features/workspace/composables/useGroupOrchestrationState.ts)
- E2E mock：[`frontend/e2e/fixtures/mockApi.ts`](../../frontend/e2e/fixtures/mockApi.ts)

## 1. 统一结论

当前运行时是 **name-based 契约**。会话、场景、主持人、专家、调度、招募、续跑都应该使用名称字段：

| 场景 | 当前字段 |
| --- | --- |
| 会话成员 | `agent_names` |
| 主持人显示名 | `leader_agent_name` 或 `host_config.leader_agent_name` |
| 调度下一位 | `next_speaker`，值为专家名称 / `user` / `end` / `invite` |
| 招募建议 | `suggested_add_agent_names` |
| 专家发言 | `agent_name` |
| Skill 续跑 owner | `skill_session_owner_name` |
| 等待补充 owner | `pending_owner_agent_name` |
| 专家引用 Skill | `skills[].directory_name` |
| 模型引用 | `llm_name` / `default_llm` |

接口统一的原则：

1. 前端、后端、mock、测试必须使用同一套字段名。
2. 新增接口字段前，先说明它的生产方、消费方和生命周期。
3. 运行时主路径不做旧字段兜底；历史文件保留是数据迁移问题，不是运行时契约问题。
4. 任何跳转问题都先查 `next_speaker`、`phase`、`interrupt_reason`、`skill_session_owner_name`、`pending_owner_agent_name` 五类字段。

## 2. 一次流式对话的端到端链路

### 2.1 前端发起

前端通过 `streamSessionChat()` 调用：

```text
POST /api/sessions/{session_id}/chat/stream
```

请求体由 `frontend/src/api/chat.ts` 构造：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `message` | string | 本轮用户输入。 |
| `client_message_id` | string | 前端生成的消息 id，用于去重或关联。 |

前端只解析 SSE 事件，不直接决定后端路由。前端可根据 `end` 事件显示等待、招募、补充字段等 UI。

### 2.2 API 转发

`backend/app/api/sessions.py` 的 `session_chat_stream()` 是薄入口：

```text
session_chat_stream(session_id, GroupChatRequest)
  -> group_chat_stream(session_id, request)
```

非流式接口 `POST /api/sessions/{id}/chat` 也复用同一个 SSE 逻辑，只是在服务端聚合 `route` / `content` / `message` / `end` / `error` 后返回 JSON。

### 2.3 运行时初始化

`group_chat_stream()` 进入后依次完成：

1. `ensure_mcp_and_skills_initialized()` 确保当前用户的 MCP / Skill loader 可用。
2. 读取会话定义：`load_session_definitions()`。
3. 读取专家库：`load_agent_instances()`。
4. 归一化会话成员：`agent_names = _dedupe_names(session_item["agent_names"])`。
5. 用专家名称构建 `agent_map`，只保留当前专家库中真实存在的专家。
6. 计算 `available_to_add`，供招募房间使用。
7. 读取历史：`load_group_history(session_id)`。
8. 展开用户消息里的文件引用：`resolve_file_refs_in_text()`。
9. 识别点名、主持人接管、忽略自动切换等入口信号。
10. 如有用户消息，先写入历史并刷新标题：`_record_user_message_and_refresh_title()`。
11. 解析场景 / 主持人：`SceneRuntime.from_group_session(...)`。

### 2.4 SSE 事件顺序

流式返回由 `run_events()` 产生。正常情况下事件顺序是：

```text
start
  -> route?          # 命中专家后发出
  -> content*        # 模型等待、工具运行、生成中等流式状态
  -> message*        # 主持人气泡或专家最终消息
  -> end             # 本轮结束状态
```

异常时可能出现：

```text
start -> message? -> error? -> end
```

前端当前在 `chat.ts` 中只分发 `route`、`content`、`message`、`end`、`error`；`start` 不需要业务处理。

## 3. 跳转规则

跳转核心在 `group_chat_runtime.py::run_events()`，不是 API 层。

### 3.1 总体优先级

| 优先级 | 条件 | 后端动作 | 关键字段 |
| --- | --- | --- | --- |
| 1 | 会话内 0 个专家 | 主持人回复并推荐专家，直接 `end` | `agent_names`, `suggested_add_agent_names` |
| 2 | 用户要求结束 Skill 会话 | 清理 Skill 锁，回主持人调度 | `skill_session_owner_name`, `skill_session_skill` |
| 3 | 有效 Skill 锁且用户未要求主持人接管 | 跳过主持人，直达锁定专家 | `skip_host_dispatch`, `direct_agent_name` |
| 4 | 用户 `@专家` 且专家在场 | 清锁，直达该专家 | `forced_at_mention_agent_name` |
| 5 | 用户显式点名场内专家 | 清锁，直达该专家 | `explicit_requested_agent_names` |
| 6 | 以上都不命中 | 调用主持人或 leader 调度 | `next_speaker`, `speaker_task` |

注意：源码中会先算 `entry_route`，但真正赋值 `next_speaker` 时，`@专家` 和显式点名优先于 Skill 锁短路。

### 3.2 0 专家分支

当 `len(agent_names) == 0`：

1. 不进入专家执行。
2. 调用 `_host_only_respond_and_recommend()`。
3. 从主持人建议或启发式推荐中得到 `picked`。
4. 写入主持人消息。
5. `end` 事件中带 `suggested_add_agent_names`。
6. `waiting_for_user=true`。

前端只有在非 `scene` 模式下展示待邀请专家；`useGroupOrchestrationState.ts` 会在 `orchestration_profile === "scene"` 时清空推荐。

### 3.3 Skill 锁短路

Skill 锁由以下字段表示：

```text
meta.skill_session_owner_name
meta.skill_session_skill
```

入口规则在 `resolve_group_entry_route()`：

| 条件 | 结果 |
| --- | --- |
| owner 为空 | 走主持人 |
| owner 不在当前 `agent_names` | 走主持人 |
| 其他情况 | `skip_host_dispatch=true`，直达 owner |

用户明确说“交给主持人”“请主持人接管”“换专家”“结束当前技能”等时，`group_chat_runtime.py` 会在调用 `resolve_group_entry_route()` 之前先清理 Skill 锁，再进入主持人调度；这类控制只来自 `message` 文本意图，不再使用隐藏请求字段。

这表示：`next_speaker=user` 和 Skill 锁不是一回事。`next_speaker=user` 只是本轮等用户；Skill 锁表示下一轮用户消息要继续给同一个专家。

### 3.4 主持人调度

主持人调度路径：

```text
_host_decide_by_agent(...)
  -> parse_strict_host_scheduler_output(...)
  -> finalize_host_scheduler_decision(...)
  -> _apply_decision_to_ctx(...)
```

如果没有主持人或主持人失败，则回退：

```text
leader_decide(...)
  -> finalize_host_scheduler_decision(...)
```

主持人或 leader 的结构化输出只允许：

```json
{
  "current_phase": "阶段",
  "next_speaker": "专家名称|user|end|invite",
  "speaker_task": "交给下一位执行的任务",
  "reason": "调度原因",
  "suggested_add_agent_names": ["可邀请专家名称"]
}
```

`group_host_decision.py` 使用 `HostSchedulerDecisionPayload` 严格解析，`extra="forbid"`。多余字段、非 JSON、非法 `next_speaker` 都会转成系统保护决策：

```text
next_speaker = "user"
interrupt_reason = "protocol_error"
announcement = "主持人输出格式错误，请重试或联系管理员。"
```

### 3.5 招募与场景模式

`finalize_host_scheduler_decision()` 负责统一后处理：

| 情况 | 规则 |
| --- | --- |
| `orchestration_profile == "scene"` | 强制清空 `suggested_add_agent_names`。 |
| 已有场内专家且用户未明确要求加人 | 抑制模型误发的招募建议。 |
| 真实 0 成员 | 允许从主持人建议里提取可邀请专家。 |
| 招募建议被抑制 | 固定 `next_speaker="user"`，等待用户下一轮输入。 |

因此接口层不要让前端自己猜“该不该招募”。前端只消费后端最终 `suggested_add_agent_names`，并再用 `orchestration_profile` 做 UI 层保险。

### 3.6 专家执行循环

当 `next_speaker in agent_names` 且 `phase == executing`：

1. `build_expert_turn_runtime()` 解析本轮专家、Skill、工具和 LLM。
2. 发 `route` 事件：`agent_name`、`skill`、`skill_route_debug`。
3. 构造专家输入：讨论目标、本轮用户输入、最近讨论、主持人 `speaker_task`。
4. `agent.astream(...)` 进入 `SimpleAgent` 工具循环。
5. 收集模型文本、工具调用、工具原始结果。
6. 用 `resolve_skill_session_state()` 解析 Skill 是否 `keep` / `release`。
7. 写入专家消息、历史、记忆。
8. 根据 required fields、hook、soft stop、Skill 状态决定 `end` 或交回主持人。

专家执行最多 32 轮；超过后用 `timeout_or_budget_exceeded` 中断并等待用户。

## 4. 字段契约矩阵

### 4.1 会话创建与更新

| 字段 | 生产方 | 消费方 | 生命周期 | 统一规则 |
| --- | --- | --- | --- | --- |
| `title` | 前端 / 后端自动标题 | 会话列表、详情 | 存入 session definition | 空标题使用“新对话”。 |
| `agent_names` | 场景、会话创建、邀请专家 | 运行时、前端成员列表 | 存入 session definition | 必须是专家 `name` 数组，写入前校验专家存在。 |
| `add_agent_names` | 前端邀请条 | `update_group_session()` | 请求字段 | 只追加专家名称；成功后刷新详情。 |
| `remove_agent_names` | 前端成员管理 | `update_group_session()` | 请求字段 | 只删除专家名称。 |
| `system_prompt` | 场景或会话设置 | `build_context_system_prompt()` | 存入 session definition | 场景级规则，影响主持人和专家上下文。 |
| `scenario_name` | 场景入口 | `load_session_scenario_row()` | 存入 session definition | 指向资源中心场景名称。 |
| `orchestration_profile` | 后端推断 / 前端更新 | 运行时、前端 UI | 存入 session definition | 只能是 `recruitment` 或 `scene`。 |
| `leader_agent_name` | 旧请求字段 / host profile | 主持人展示名解析 | 请求兼容、运行时解析 | 新运行时不应把它当专家身份。 |
| `host_config` | 场景资源 | `SceneRuntime` | 场景资源优先 | 会话更新里不再持久化为主契约。 |

### 4.2 用户消息请求

| 字段 | 生产方 | 消费方 | 影响 |
| --- | --- | --- | --- |
| `message` | 前端输入框 | `group_chat_stream()` | 写入历史、解析点名、调度目标、专家 prompt。 |
| `client_message_id` | 前端 | `_record_user_message_and_refresh_title()` | 用于消息关联。 |

### 4.3 主持人调度结果

| 字段 | 生产方 | 消费方 | 合法值 | 统一规则 |
| --- | --- | --- | --- | --- |
| `current_phase` | 主持人 / leader | host message、scheduler state | 非空字符串 | 阶段描述，不等于平台 `phase`。 |
| `next_speaker` | 主持人 / leader | 运行时跳转 | 专家名称 / `user` / `end` / `invite` | 专家必须在当前 `agent_names` 中。 |
| `speaker_task` | 主持人 / leader | 专家 prompt | 字符串 | 当 `next_speaker` 是专家或 `user` / `invite` 时通常必须非空。 |
| `reason` | 主持人 / leader | 日志、end payload | 字符串或 null | 只做解释，不决定跳转。 |
| `suggested_add_agent_names` | 主持人 / leader | 前端邀请条 | 专家名称数组 | 只有 `next_speaker=user` 或 invite 语义下有效；scene 模式清空。 |

### 4.4 SSE route 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `type` | 后端 | 前端 | 固定 `"route"`。 |
| `agent_name` | 后端 | 前端当前专家状态 | 本轮被路由到的专家名称。 |
| `skill` | 后端 | 前端当前 Skill 状态 | 本轮解析出的 Skill 目录名。 |
| `expert_route_debug` | 后端 | 调试 | 专家路由辅助信息。 |
| `skill_route_debug` | 后端 | 调试、自动切换提示 | Skill 选型策略、失败原因。 |

### 4.5 SSE content 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `text` | 后端 | 前端流式展示 | 当前实现多为空状态提示；最终正文靠 `message`。 |
| `agent_name` | 后端 | 前端流状态 | 正在执行的专家名称。 |
| `meta.phase` | 后端 | 前端状态 | `file_resolving` / `tool_running` / `assistant_generating` / 展示重写等。 |

### 4.6 SSE message 事件

| 字段 | 生产方 | 消费方 | 统一规则 |
| --- | --- | --- | --- |
| `message_id` | 后端 | 前端列表、删除消息 | 后端生成。 |
| `role` | 后端 | 前端渲染 | `user` / `assistant` / `host`。 |
| `agent_name` | 后端 | 前端头像、发言人 | 专家消息为专家名称；主持人消息为主持人显示名。 |
| `content` | 后端 | 前端展示 | 最终展示文本。 |
| `presentation_content` | 后端 | `frontend_history_message()` | 如果存在，详情接口会优先展示它。 |
| `timestamp` | 后端 | 前端时间 | 后端统一格式。 |
| `skill` | 后端 | 前端 Skill 标识 | 专家消息为 Skill 目录名。 |
| `tool_raw_results` | 后端 | 调试、交付校验 | 有工具结果时写入。 |
| `tool_debug` | 后端 | 调试 | 工具调用、匹配、Skill 会话状态。 |
| `required_user_fields` | 后端 | 前端补充表单 | Skill 推断出的用户必填项。 |

### 4.7 SSE end 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `waiting_for_user` | 后端 | 前端等待状态 | true 表示本轮结束，等用户继续。 |
| `discussion_ended` | 后端 | 前端结束态 | true 表示任务结束。 |
| `suggested_next_speaker` | 后端 | 前端提示 | 建议下一位，但不等于强制路由。 |
| `phase` | `OrchestrationContext` | 前端状态 | 平台阶段：`planning` / `executing` / `awaiting_user` / `recruiting` / `completed`。 |
| `interrupt_reason` | 后端 | 前端提示 | `need_user_input`、`need_more_context`、`need_recruit_expert`、`tool_unavailable`、`timeout_or_budget_exceeded`、`protocol_error` 等。 |
| `resume_target_agent_name` | 后端 | pending 状态、前端提示 | 用户补充后应恢复给哪个专家。 |
| `required_user_fields` | 后端 | 前端补充表单 | 需要用户补齐的字段列表。 |
| `turn_id` | 后端 | 调试 | 本轮编排 id。 |
| `token_version` | 后端 | 调试 | 编排上下文版本。 |
| `handoff_reason` | 后端 | 调试 / 提示 | 中断或交接原因。 |
| `suggested_add_agent_names` | 后端 | 前端邀请条 | 可邀请专家名称数组。 |

### 4.8 会话定义中的运行态字段

| 字段 | 谁写 | 谁读 | 清理时机 |
| --- | --- | --- | --- |
| `skill_session_owner_name` | `_store_skill_session_lock_for_turn()` | `resolve_group_entry_route()` / `locked_skill_for_expert()` | 用户要求主持人、点名其他专家、Skill release、专家不在场。 |
| `skill_session_skill` | `_store_skill_session_lock_for_turn()` | `locked_skill_for_expert()` | 同上。 |
| `pending_owner_agent_name` | `_persist_pending_state()` | 主持人调度 prompt | 不再等待用户、resume 不在场、无 required fields 时清理。 |
| `pending_skill` | `_persist_pending_state()` | 主持人调度 prompt | 同上。 |
| `pending_phase` | `_persist_pending_state()` | 调试 / 恢复 | 同上。 |
| `pending_required_user_fields` | `_persist_pending_state()` | 前端 / 主持人 | 同上。 |
| `pending_handoff_reason` | `_persist_pending_state()` | 调试 / 主持人 | 同上。 |
| `scheduler_state` | `_host_decide_by_agent()` | 主持人状态延续 | 配置变更时 `_clear_scheduler_state_for_session()`。 |

`group_chat_state._clean_session_item()` 会把这些运行态字段从 `session.json` 的定义形态里移除，避免把运行态混入会话静态定义。

## 5. 工具与 Skill 执行边界

### 5.1 Skill 选择

`build_expert_turn_runtime()` 的职责是把一位专家变成可执行运行时：

```text
agent_profile + agent_name
  -> resolve_expert_skill()
  -> build_tools_for_group_chat()
  -> create_skill_execution_agent()
```

Skill 选择规则：

| 条件 | 结果 |
| --- | --- |
| 当前专家有有效 Skill 锁 | 继续锁定 Skill。 |
| 专家没有可加载 Skill | 中断，提示配置错误。 |
| 只有一个可加载 Skill | 直接使用。 |
| 多个可加载 Skill | 调用专家 LLM 严格输出 `{"selected_skill":"..."}`。 |
| 多 Skill 选择失败 | 中断，等待用户或主持人重派。 |

### 5.2 工具组装

`build_tools_for_group_chat(agent_profile, workspace_id, resolved_skill)` 统一组装工具：

| 工具类型 | 来源 | 规则 |
| --- | --- | --- |
| MCP | Skill frontmatter `allowed-tools.mcp` | 只有本轮 Skill 声明的 MCP server 才加载。 |
| HTTP API | Skill frontmatter `allowed-tools.http_api` | 注入 `http_api_<name>` 工具。 |
| 工作区文件 | 内置工具 | 注入读、写、编辑、重命名、建目录、列目录。 |
| 通用 HTTP | `call_api` | 无 MCP 配置问题时默认注入。 |
| Skill 脚本 | 专家 `skills[].directory_name` | 磁盘存在 `SKILL.md` 时注入 `run_skill_script_<directory>`。 |
| MCP 配置状态 | 配置缺失时 | 注入 `mcp_configuration_status`，提示用户缺密钥或配置。 |

这里的关键边界是：专家资源不再保存工具权限主契约；本轮工具权限由当前 Skill 的 frontmatter 决定。

### 5.3 脚本执行

脚本工具由 `backend/app/tools/run_skill_script.py` 创建，执行链路是：

```text
run_skill_script_<skill>
  -> create_run_skill_script_tool()
  -> UnifiedToolGateway
  -> SandboxService / OpenSandbox
```

脚本 stdout 的结构化契约由 `SkillScriptStdoutPayload` 管：

```json
{
  "execution_status": "succeeded|blocked|failed",
  "result_code": "code",
  "message": "message",
  "artifacts": {},
  "next_action": {
    "agent_turn": "respond|continue",
    "skill_session": "keep|release"
  }
}
```

### 5.4 MCP 与 HTTP

MCP 工具走 `app.mcp.manager`。保存的 HTTP API 工具走 `create_http_api_tool()`，最终复用 `call_api._call_api_impl()`。通用 `call_api` 只允许公网 `http/https`，默认阻止 localhost、内网、保留地址。

## 6. 接口统一改造时的默认步骤

每次发现“跳转不对”或“字段依赖不对”，不要只改单点。按这个顺序做：

1. **定主字段**：明确业务身份字段是 `name`、`directory_name` 还是运行态枚举。
2. **定生产方**：字段由前端、后端 API、主持人 LLM、专家 Skill、工具 stdout 还是存储层产生。
3. **定消费方**：列出后端函数、前端 composable、mock、测试谁读取它。
4. **删旧入口**：运行时主路径不保留旧字段兜底。
5. **同步 mock**：`frontend/e2e/fixtures/mockApi.ts` 必须同步，否则 E2E 会把旧契约带回来。
6. **同步文档**：至少更新本文或对应专题文档。
7. **跑聚焦验证**：后端契约测试 + 前端 build + 相关 E2E。

## 7. 常见错位与定位表

| 表现 | 优先检查 | 典型根因 |
| --- | --- | --- |
| 用户补充后没有回到原专家 | `skill_session_owner_name`、`pending_owner_agent_name`、`resume_target_agent_name` | Skill 没有输出 keep，或入口被主持人接管清锁。 |
| 明明点名专家却跑了主持人 | `forced_at_mention_agent_name`、`explicit_requested_agent_names`、`agent_names` | 点名名称不在当前场景成员里。 |
| 场景模式出现邀请专家条 | `orchestration_profile`、`suggested_add_agent_names` | 后端后处理未清空，或前端 mock 仍伪造建议。 |
| 主持人输出后没有专家执行 | `next_speaker`、`agent_names`、`protocol_error` | `next_speaker` 不是场内专家名称，或主持人 JSON 严格解析失败。 |
| 专家选错 Skill | `skill_route_debug`、专家 `skills[].directory_name`、Skill 是否加载 | Skill 目录不存在、内容为空、多 Skill LLM 选择失败。 |
| 工具不存在 | `tool_attempt_debug.available_tools`、Skill frontmatter `allowed-tools` | 工具没有在当前 Skill 声明，或 MCP/HTTP API 配置缺失。 |
| 文件已生成但前端看不到 | `tool_raw_results`、工作区路径、`write_workspace_file` 返回值 | 模型口头声称保存，但工具未成功写入。 |
| 非流式 `/chat` 返回 message 不对 | `route.agent_name`、`message_events` | 聚合逻辑会优先选与 route 专家一致的最后一条 message。 |
| 文档和代码说法冲突 | 本文入口文件 | 旧文档可能还残留 id-based 或旧路径口径。 |

## 8. 验收建议

接口统一类改动建议至少验证：

```bash
rtk python -m py_compile backend/app/api/sessions.py backend/app/agent/group_chat_runtime.py backend/app/agent/group_host_decision.py backend/app/agent/group_orchestration_fsm.py backend/app/agent/expert_runtime.py backend/app/agent/tools_for_skill.py
rtk python -m pytest backend/tests/test_group_host_decision.py backend/tests/test_group_orchestration_fsm.py backend/tests/test_group_chat_stream_protocol.py -q
rtk npm --prefix frontend run build
```

如果改动触达前端邀请、点名、自动切换或 mock，再补：

```bash
rtk npx --prefix frontend playwright test frontend/e2e/workspace.spec.ts frontend/e2e/resources-scenario-expert.spec.ts
```

如果本地测试文件路径有调整，以当前 `rg --files | rg 'test_.*(group|host|session|workspace)'` 的结果为准。

## 9. 文档防漂移规则

后续凡是改以下契约，必须同步更新本文：

1. `GroupChatRequest` 请求字段。
2. 主持人严格 JSON 字段。
3. SSE `route` / `message` / `end` payload。
4. 会话定义中的运行态字段。
5. Skill stdout / MCP tool result 结构化契约。
6. `agent_names`、`suggested_add_agent_names`、`skill_session_owner_name` 等 name-based 字段。

如果只改代码不改本文，后续排查会重新陷入“跳转靠猜、字段靠记”的状态。
