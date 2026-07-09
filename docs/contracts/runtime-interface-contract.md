# 程序运行逻辑与接口契约统一说明

本文用于统一「一次会话请求到底怎么跑」以及「跳转和字段依赖应该由谁负责」。排查字段错位、主持人误跳转、专家续跑断链、前后端 mock 不一致时，先按本文定位。

本文记录目标运行契约；实现改造、测试和前端 mock 应以本文为准。当前改造重点入口：

- 后端会话 API：[`backend/app/api/sessions.py`](../../backend/app/api/sessions.py)
- 会话 CRUD / 事件流：[`backend/app/agent/group_session_service.py`](../../backend/app/agent/group_session_service.py)
- 会话状态存储：[`backend/app/api/group_chat_state.py`](../../backend/app/api/group_chat_state.py)
- 群聊运行时：[`backend/app/agent/group_chat_runtime.py`](../../backend/app/agent/group_chat_runtime.py)
- 入口路由与续跑状态：[`backend/app/agent/group_orchestration_fsm.py`](../../backend/app/agent/group_orchestration_fsm.py)
- 主持人严格输出：[`backend/app/agent/group_host_decision.py`](../../backend/app/agent/group_host_decision.py)
- 主持人后处理：[`backend/app/core/scene_scheduler.py`](../../backend/app/core/scene_scheduler.py)
- 专家运行时：[`backend/app/agent/expert_runtime.py`](../../backend/app/agent/expert_runtime.py)
- 工具组装：[`backend/app/agent/tools_for_skill.py`](../../backend/app/agent/tools_for_skill.py)
- Skill Agent 工具循环：[`backend/app/agent/skill_agent_runtime.py`](../../backend/app/agent/skill_agent_runtime.py)
- 前端流式请求：[`frontend/src/api/chat.ts`](../../frontend/src/api/chat.ts)
- 前端编排状态：[`frontend/src/features/workspace/composables/useGroupOrchestrationState.ts`](../../frontend/src/features/workspace/composables/useGroupOrchestrationState.ts)
- E2E mock：[`frontend/e2e/fixtures/mockApi.ts`](../../frontend/e2e/fixtures/mockApi.ts)

## 1. 统一结论

当前目标运行时是 **name-based 契约**。会话、主持人、专家、调度、招募、续跑都应该使用名称字段：

| 场景 | 当前字段 |
| --- | --- |
| 会话成员 | `agent_names` |
| 会话主持人 | `host` |
| 主持人显示名 | `host.name` |
| 主持人引用 Skill | `host.skill_directory` |
| 调度下一位 | `next_speaker`，值为专家名称 / `user` / `end` |
| 下一步动作 | `next_action` |
| 招募建议 | `suggested_add_agent_names` |
| 专家发言 | `agent_name` |
| 短期续跑状态 | `orchestration_state.json.continuation` |
| 主持人跨轮调度状态 | `orchestration_state.json.host_scheduler` |
| 专家引用 Skill | `skills[].directory_name` |
| 模型引用 | `llm_name` / `default_llm` |

接口统一的原则：

1. 前端、后端、mock、测试必须使用同一套字段名。
2. 新增接口字段前，先说明它的生产方、消费方和生命周期。
3. 运行时主路径不做旧字段兜底；历史文件保留是数据迁移问题，不是运行时契约问题。
4. 任何跳转问题都先查 `next_speaker`、`next_action`、`skill_policy`、`orchestration_state.json.continuation`、`orchestration_state.json.host_scheduler` 和 `history.json` 中的 Skill 结果。
5. `leader` / `leader_agent_name` / `host_config` 是旧术语；会话和资源中心统一使用 `host`，主持人名称统一使用 `host.name`。

## 2. 一次流式对话的端到端链路

### 2.1 前端发起

前端通过 `streamSessionChat()` 调用：

```text
POST /api/sessions/{session_id}/chat/stream
```

请求体由 `frontend/src/api/chat.ts` 构造：

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `message` | string | 本轮用户正文。可以为空，但 `message`、`attachments`、`target_agent_name` 至少一个有效。 |
| `client_message_id` | string | 前端生成的消息 id，用于去重或关联，必填。 |
| `attachments` | array | 本轮用户附带的工作区文件引用。只引用已进入当前会话 `workspace/` 的文件，不承载原始上传流。 |
| `target_agent_name` | string \| null | 用户明确指定本轮交给哪个专家。必须是当前会话 `agent_names` 中的专家名称。 |

前端只解析 SSE 事件，不直接决定主持人调度结果。用户指定专家时，前端通过 `target_agent_name` 表达目标专家，不再把 `@专家` 或点名语义混入 `message` 正文。

### 2.2 API 转发

`backend/app/api/sessions.py` 的 `session_chat_stream()` 是薄入口：

```text
session_chat_stream(session_id, GroupChatRequest)
  -> group_chat_stream(session_id, request)
```

非流式接口 `POST /api/sessions/{id}/chat` 也复用同一个 SSE 逻辑，只是在服务端聚合 `route` / `progress` / `message` / `end` / `error` 后返回 JSON。聚合结果不得重新引入 `content`、`contents` 或 `meta.phase` 结构。

### 2.3 运行时初始化

`group_chat_stream()` 进入后依次完成：

1. `ensure_mcp_and_skills_initialized()` 确保当前用户的 MCP / Skill loader 可用。
2. 读取会话定义：扫描 `sessions/{session_id}/session.json`。
3. 读取专家库：`load_agent_instances()`。
4. 归一化会话成员：`agent_names = _dedupe_names(session_item["agent_names"])`。
5. 用专家名称构建 `agent_map`，只保留当前专家库中真实存在的专家。
6. 计算 `available_to_add`，供招募房间使用。
7. 读取历史：`load_group_history(session_id)`。
8. 校验并解析请求中的 `attachments`：只允许当前会话 `workspace/` 下的相对路径。
9. 校验 `target_agent_name`：如存在，必须是当前会话成员。
10. 如有有效用户输入、附件或目标专家，先写入历史并刷新标题：`_record_user_message_and_refresh_title()`。
11. 从 `session.json` 的 `host` 快照解析本会话主持人。

### 2.4 SSE 事件顺序

流式返回由 `run_events()` 产生。正常情况下事件顺序是：

```text
start
  -> route?          # 命中专家后发出
  -> progress*       # 模型等待、工具运行、生成中等运行阶段
  -> message*        # 主持人气泡或专家最终消息
  -> end             # 本轮结束状态
```

异常时可能出现：

```text
start -> message? -> error? -> end
```

前端目标契约只分发 `start`、`route`、`progress`、`message`、`end`、`error`。`progress` 是运行阶段事件，不承载最终正文；未来如需 token 级流式正文，应另定义 `delta` 事件，不能复用 `progress`。

## 3. 跳转规则

跳转核心在 `group_chat_runtime.py::run_events()`，不是 API 层。

### 3.1 总体优先级

| 优先级 | 条件 | 后端动作 | 关键字段 |
| --- | --- | --- | --- |
| 1 | 会话内 0 个专家 | 主持人回复并推荐专家，直接 `end` | `agent_names`, `suggested_add_agent_names` |
| 2 | 用户要求结束 Skill 会话 | 清理短期续跑状态，回主持人调度 | `orchestration_state.json.continuation` |
| 3 | 请求指定了 `target_agent_name` | 清理短期续跑状态，直达该专家 | `target_agent_name` |
| 4 | 有效短期续跑状态且用户未要求主持人接管 | 跳过主持人，直达续跑专家 | `orchestration_state.json.continuation` |
| 5 | 以上都不命中 | 调用主持人调度 | `next_speaker`, `next_action` |

`message` 正文不再承担路由控制职责。`@专家`、自然语言点名、`host_takeover_requested`、`ignore_auto_agent_name`、`ignore_auto_skill`、`action` 都不是当前请求契约；如出现在请求体顶层，应按非法字段拒绝。

统一路由决策只允许以下字段：

```json
{
  "next_speaker": "专家名称 | user | end | invite",
  "next_action": "下一步动作说明",
  "route_source": "empty_group | target_agent | host_scheduler_state | continuation | host_scheduler",
  "skill_policy": "none | keep | release",
  "skill": "skill-directory 或 null"
}
```

| 字段 | 规则 |
| --- | --- |
| `next_speaker` | 唯一跳转结果。专家名称必须在当前 `agent_names` 中；`user` 表示等待用户，`end` 表示结束，`invite` 只用于内部表达招募入口。 |
| `next_action` | 唯一下一步动作说明。`next_speaker` 是专家时进入专家 prompt；`next_speaker` 是 `user` / `invite` / `end` 时转成主持人消息或前端可见提示。 |
| `route_source` | 仅后端内部和测试断言使用，不进入前端 API、SSE payload 或持久化业务数据。 |
| `skill_policy` | `none` 表示正常选 Skill；`keep` 表示继续 `skill` 指定的 Skill；`release` 表示接回同一专家但重新选择 Skill。 |
| `skill` | 仅 `skill_policy=keep` 时有值。 |

`reason`、`instruction`、`speaker_task`、`next_prompt`、`handoff_reason`、`resume_target_agent_name`、`pending_*` 不属于统一路由决策契约。

### 3.2 0 专家分支

当 `len(agent_names) == 0`：

1. 不进入专家执行。
2. 调用 `_host_only_respond_and_recommend()`。
3. 从主持人建议或启发式推荐中得到 `picked`。
4. 写入主持人消息。
5. `end` 事件中带 `suggested_add_agent_names`。
6. `waiting_for_user=true`。

前端只消费后端最终返回的 `suggested_add_agent_names`。是否展示邀请条由后端事件决定，不再依赖会话定义里的模式字段。

### 3.3 短期续跑短路

跨请求续跑由 `orchestration_state.json` 的 `continuation` 表示：

```json
{
  "continuation": {
    "owner_agent_name": "专家名称",
    "skill_policy": "keep",
    "skill": "skill-directory",
    "next_action": "用户回复后继续由该专家使用该 Skill 处理。"
  }
}
```

入口规则在 `resolve_group_entry_route()`：

| 条件 | 结果 |
| --- | --- |
| `host_scheduler.next_speaker` 是场内专家 | 按主持人调度，直达该专家，并清理冲突的 `continuation`。 |
| `continuation.owner_agent_name` 为空 | 走主持人 |
| `continuation.owner_agent_name` 不在当前 `agent_names` | 走主持人，并清理 `continuation` |
| `continuation.skill_policy == "keep"` | 直达 owner，并锁定 `continuation.skill` |
| `continuation.skill_policy == "release"` | 直达 owner，但不锁定 Skill，由专家重新选择 Skill |

用户明确说“交给主持人”“请主持人接管”“换专家”“结束当前技能”等时，`group_chat_runtime.py` 会在调用入口路由之前清理 `continuation`，再进入主持人调度；这类控制只来自 `message` 文本意图，不再使用隐藏请求字段。

这表示：`next_speaker=user` 和 `continuation` 不是一回事。`next_speaker=user` 只是本轮等用户；`continuation` 表示下一轮用户消息要接回哪个专家，以及是否继续锁定 Skill。

### 3.4 主持人调度

主持人调度路径：

```text
_host_decide_by_agent(...)
  -> parse_strict_host_scheduler_output(...)
  -> finalize_host_scheduler_decision(...)
  -> _apply_decision_to_ctx(...)
```

如果没有会话 `host` 或主持人失败，则进入协议错误或等待用户状态，不再回退到旧 `leader` 路径：

```text
next_speaker = "user"
interrupt_reason = "protocol_error"
```

主持人的结构化输出只允许：

```json
{
  "current_phase": "阶段",
  "next_speaker": "专家名称|user|end",
  "next_action": "下一步动作说明",
  "suggested_add_agent_names": ["可邀请专家名称"]
}
```

`current_phase`、`next_speaker`、`next_action` 必填，`suggested_add_agent_names` 可选。`suggested_add_agent_names` 出现时，`next_speaker` 必须是 `"user"`；招募不再使用 `"invite"` 表达。

`group_host_decision.py` 使用严格结构解析，`extra="forbid"`。多余字段、非 JSON、非法 `next_speaker` 都会转成系统保护决策。`speaker_task`、`reason`、`invite`、`next_prompt`、`task_done`、`announcement`、`phase`、`owner_agent_name`、`interrupt_reason`、`decision_source`、`handoff_reason`、`required_user_fields`、`suggested_order` 和 id 类字段都不是主持人 JSON 契约的一部分：

```text
next_speaker = "user"
interrupt_reason = "protocol_error"
announcement = "主持人输出格式错误，请重试或联系管理员。"
```

### 3.5 招募建议

`finalize_host_scheduler_decision()` 负责统一后处理：

| 情况 | 规则 |
| --- | --- |
| 已有场内专家且用户未明确要求加人 | 抑制模型误发的招募建议。 |
| 真实 0 成员 | 允许从主持人建议里提取可邀请专家。 |
| 招募建议被抑制 | 固定 `next_speaker="user"`，等待用户下一轮输入。 |
| 需要招募专家 | 固定 `next_speaker="user"`，并输出 `suggested_add_agent_names`。 |

因此接口层不要让前端自己猜“该不该招募”。前端只消费后端最终 `suggested_add_agent_names`。

### 3.6 专家执行循环

当 `next_speaker in agent_names` 且 `phase == executing`：

1. `build_expert_turn_runtime()` 解析本轮专家、Skill、工具和 LLM。
2. 发 `route` 事件：`run_id`、`agent_name`、`skill`。
3. 构造专家输入：讨论目标、本轮用户输入、最近讨论、路由决策 `next_action`。
4. `agent.astream(...)` 进入 `SimpleAgent` 工具循环。
5. 收集模型文本和工具调用；工具 stdout、stderr、退出码和耗时写入执行 trace 或运行日志。
6. 用 `resolve_skill_session_state()` 解析 Skill 是否 `keep` / `release`。
7. 写入专家消息、历史、记忆。
8. 根据 `skill_result.next_action`、hook、soft stop 和 Skill 状态决定 `end` 或交回主持人。

专家执行最多 32 轮；超过后用 `timeout_or_budget_exceeded` 中断并等待用户。

## 4. 字段契约矩阵

### 4.1 会话创建与更新

| 字段 | 生产方 | 消费方 | 生命周期 | 统一规则 |
| --- | --- | --- | --- | --- |
| `title` | 前端 / 后端自动标题 | 会话列表、详情 | 存入 `session.json` | 空标题使用“新对话”。 |
| `title_auto_generated` | 后端创建会话 / 用户手动改名 | 自动标题逻辑 | 存入 `session.json` | 创建时必须为 `true`；用户手动改标题后置为 `false`，之后不得自动置回 `true`。 |
| `agent_names` | 会话创建、邀请专家、移出专家 | 运行时、前端成员列表 | 存入 `session.json` | 必须是专家 `name` 数组；从场景创建时只用场景专家列表初始化，之后不再关联场景。 |
| `host` | 场景主持人 / 账号默认主持人 | 主持人运行时、前端展示 | 存入 `session.json` | 会话级主持人快照；上层对象叫 `host`，显示名叫 `host.name`。 |
| `host.name` | 场景或默认主持人 | 主持人消息、头像、调度提示 | `host` 子字段 | 原 `leader_agent_name`，旧字段删除。 |
| `host.llm_name` | 场景或默认主持人 | 主持人 LLM 解析 | `host` 子字段 | 引用模型资源 `name`。 |
| `host.system_prompt` | 场景或默认主持人 | 主持人调度 prompt | `host` 子字段 | 只影响主持人，不作为会话级通用系统提示词。 |
| `host.skill_directory` | 场景或默认主持人 | 主持人 Skill 加载 | `host` 子字段 | 引用 Skill `directory_name`。 |
| `created_at` | 后端创建会话 | 会话列表、检查点 | 存入 `session.json` | 创建时间。 |
| `updated_at` | 后端写入会话 | 会话列表排序 | 存入 `session.json` | 会话定义或消息更新时刷新。 |
| `add_agent_names` | 前端邀请条 | `update_group_session()` | 请求字段 | 只追加专家名称；成功后刷新详情。 |
| `remove_agent_names` | 前端成员管理 | `update_group_session()` | 请求字段 | 只删除专家名称。 |

会话定义不再保存 `scenario_name`、`orchestration_profile`、`system_prompt`、`leader_agent_name`、`host_config`。场景资源只在创建会话时作为初始化模板使用：复制专家名称列表并生成 `host` 快照；会话创建后不再依赖场景资源。

`sessions/index.json` 不再是会话列表契约。会话列表应扫描 `sessions/{session_id}/session.json`，按 `updated_at` 排序。

### 4.2 用户消息请求

| 字段 | 生产方 | 消费方 | 影响 |
| --- | --- | --- | --- |
| `message` | 前端输入框 | `group_chat_stream()`、专家 prompt 构造 | 用户自然语言正文；不解析文件引用、不解析目标专家。 |
| `client_message_id` | 前端 | `_record_user_message_and_refresh_title()` | 必填，用于幂等和消息关联。 |
| `attachments` | 前端文件选择 / 上传结果 | 工作区文件校验、专家上下文构造、工具文件访问 | 当前会话 workspace 内文件引用数组。 |
| `attachments[].type` | 前端 | 请求校验 | 当前只允许 `workspace_file`。 |
| `attachments[].path` | 前端文件 API 返回值 | 工作区路径校验、文件读取 | 必填，当前会话 `workspace/` 相对路径。 |
| `attachments[].name` | 前端 | 前端展示、专家上下文说明 | 可选展示名，不参与路径解析。 |
| `target_agent_name` | 前端专家选择控件 | 路由决策 | 可选；存在时必须命中当前 `agent_names`，本轮直接交给该专家。 |

请求校验规则：

1. `client_message_id` 必填且 trim 后非空。
2. `message`、`attachments`、`target_agent_name` 至少一个有效。
3. `attachments` 只能引用当前会话工作区内已存在的文件；原始文件上传不走 `/chat/stream`，先走工作区文件 API。
4. `target_agent_name` 不在当前会话成员中时直接拒绝，不自动招募、不回主持人猜测。
5. 顶层多余字段一律拒绝，不静默忽略、不兼容旧字段。
6. `message` 正文中的 `【文件引用：...】` 和 `@专家` 不再是协议字段；历史文本可保留展示，但新请求不得依赖它们触发文件或路由逻辑。

### 4.3 主持人调度结果

| 字段 | 生产方 | 消费方 | 合法值 | 统一规则 |
| --- | --- | --- | --- | --- |
| `current_phase` | 主持人 | host message、scheduler state | 非空字符串 | 阶段描述，不等于平台 `phase`。 |
| `next_speaker` | 主持人 | 运行时跳转 | 专家名称 / `user` / `end` | 专家必须在当前 `agent_names` 中；`invite` 非法。 |
| `next_action` | 主持人 | 路由决策、专家 prompt、主持人消息 | 字符串 | 当 `next_speaker` 是专家时进入专家 prompt；当 `next_speaker` 是 `user` / `end` 时转成主持人消息或前端可见提示。 |
| `suggested_add_agent_names` | 主持人 | 前端邀请条 | 专家名称数组 | 只有 `next_speaker=user` 时有效；后端可按当前成员状态抑制。 |

### 4.4 SSE route 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `type` | 后端 | 前端 | 固定 `"route"`。 |
| `run_id` | 后端 | 前端运行态关联、停止运行 | 当前回复运行编号。 |
| `agent_name` | 后端 | 前端当前专家状态 | 本轮被路由到的专家名称。 |
| `skill` | 后端 | 前端当前 Skill 状态 | 本轮解析出的 Skill 目录名。 |

`route` 事件不返回 `expert_route_debug`、`skill_route_debug`、`routing`、`route_source`。专家路由和 Skill 选型排查信息只能写入后端日志、执行 trace 或测试断言，不能进入前端 SSE 契约。

### 4.5 SSE progress 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `type` | 后端 | 前端 | 固定 `"progress"`。 |
| `run_id` | 后端 | 前端运行态关联、停止运行 | 当前回复运行编号。 |
| `phase` | `runtime.json.phase` | 前端运行态文案 | 必须等于当前 `runtime.json.phase`。 |
| `agent_name` | 后端 | 前端流状态 | 正在执行的专家名称。 |
| `skill` | 后端 | 前端流状态 | 正在执行的 Skill 目录名。 |
| `text` | 后端 | 前端运行提示 | 仅用于阶段提示，不作为最终消息正文。 |

平台不使用 `meta.phase`。运行阶段只能由后端写入 `runtime.json.phase`，再由 `progress.phase` 原样同步给前端。前端不得自定义第二套 `status` / `phase` 枚举来覆盖后端阶段。

`tool_start`、`tool_result` 不作为顶层 SSE 业务事件。工具 stdout、stderr、退出码、调用参数、结构化返回和调用耗时属于执行 trace 或运行日志；面向用户可展示的工具产物写入 `skill_result.artifacts`。

### 4.6 SSE message 事件

| 字段 | 生产方 | 消费方 | 统一规则 |
| --- | --- | --- | --- |
| `message_id` | 后端 | 前端列表、删除消息 | 后端生成。 |
| `speaker.type` | 后端 | 前端渲染 | `user` / `host` / `expert`。 |
| `speaker.agent_name` | 后端 | 前端头像、发言人 | 主持人和专家消息填写；用户消息不填写。 |
| `speaker.skill` | 后端 | 前端 Skill 标识 | 主持人和专家消息可填写本轮实际 Skill 目录名。 |
| `message.content` | 后端 | 前端展示、后续上下文 | 最终展示文本。 |
| `message.attachments` | 前端请求 / 后端落盘 | 前端附件展示、后端上下文组装 | 仅用户消息可有，只允许当前会话 workspace 文件引用。 |
| `message.target_agent_name` | 前端请求 / 后端落盘 | 路由、前端回显 | 仅用户消息可有，表示用户明确指定本轮专家。 |
| `created_at` | 后端 | 前端时间 | 后端统一格式。 |
| `client_message_id` | 前端 / 后端落盘 | 幂等、消息关联 | 仅用户消息可有。 |
| `skill_result` | Skill / 后端落盘 | 前端结果展示、续跑判断 | 仅主持人或专家 Skill 消息可有。 |

`skill_result.execution_status` 只允许 `succeeded`、`blocked`、`failed`。`blocked` 表示 Skill 或工具执行到明确等待点，需要用户补充材料、文件、链接、确认或参数；`failed` 表示本步失败，`message.content` 和 `skill_result.content` 必须给出面向用户的失败原因。

消息事件不保存 `role`、顶层 `content`、顶层 `agent_name`、顶层 `skill`、`timestamp`、`turn_id`、`debug`、`required_user_fields`、`handoff_reason`、`interrupt_reason`、`presentation_content`、`tool_raw_results`、`tool_debug`、`tool_results` 作为核心字段。需要给用户看的补充说明使用 `message.content`；需要跨刷新接续的短期状态写入 `orchestration_state.json`。工具 stdout、stderr、退出码、调用参数、结构化返回和调用耗时只属于执行 trace 或运行日志，不进入前端消息 payload，也不进入提示词字段。

SSE `message` 事件、会话详情 `messages` 和 `history.json` 必须使用同一条消息结构。实时流只是同步通道，不得为前端单独制造第二套 `role` / `agent_name` / `timestamp` 结构。

### 4.7 SSE end 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `type` | 后端 | 前端 | 固定 `"end"`。 |
| `run_id` | 后端 | 前端运行态关联、停止运行 | 当前回复运行编号。 |
| `phase` | `OrchestrationContext` / 运行态收尾 | 前端状态 | 只允许 `awaiting_user` / `completed` / `recruiting` / `stopped` / `failed`。 |
| `waiting_for_user` | 后端 | 前端等待状态 | true 表示本轮结束，等用户继续。 |
| `suggested_next_speaker` | 后端 | 前端提示 | 建议下一位，但不等于强制路由。 |
| `suggested_add_agent_names` | 后端 | 前端邀请条 | 可邀请专家名称数组。 |

`discussion_ended` 已从平台契约删除，不能由后端生成，也不能由前端读取。`end` 只表示当前回复回合结束，不表示整个会话结束；会话关闭、归档或删除必须走会话 API。

`interrupt_reason`、`required_user_fields`、`handoff_reason`、`resume_target_agent_name`、`turn_id`、`token_version`、`next_prompt`、`instruction` 不属于目标 `end` 事件契约。需要跨刷新保存的接续信息写入 `orchestration_state.json.continuation.next_action`、`continuation.owner_agent_name` 和 `continuation.skill_policy`。

### 4.8 SSE error 事件

| 字段 | 生产方 | 消费方 | 含义 |
| --- | --- | --- | --- |
| `type` | 后端 | 前端 | 固定 `"error"`。 |
| `run_id` | 后端 | 前端运行态关联 | 当前回复运行编号，可为空。 |
| `code` | 后端 | 前端错误分类 | 稳定错误码。 |
| `message` | 后端 | 前端错误提示 | 面向用户的错误文本。 |

`error.message` 不承载附件、主持人下一步、目标专家或完整消息结构。需要给用户展示恢复说明、附件或下一步建议时，后端必须另发标准 `message` 事件，再用 `end` 表达本轮结束状态。

### 4.9 会话运行态文件

会话运行态拆成两个文件，不能写入 `session.json`。

#### `runtime.json`

`runtime.json` 只保存前端显示和刷新恢复需要的运行中镜像，不作为编排决策真相源。

| 字段 | 归属 | 规则 |
| --- | --- | --- |
| `running` | 前端运行态显示 | true 表示当前会话有后端任务正在运行。 |
| `run_id` | 停止运行 / 过期判断 | 用于区分当前运行。 |
| `phase` | 前端运行态文案 | 后端生成的当前阶段；`progress.phase` 必须原样同步该值。 |
| `agent_name` | 前端运行态显示 | 当前正在执行的专家名称。 |
| `skill` | 前端运行态显示 | 当前正在执行的 Skill 目录名。 |
| `started_at` | stale runtime 判断 | 本轮运行开始时间。 |

`runtime.json` 不保存 `updated_at`、`user_id` 或任何前端不展示、不恢复 UI、不用于停止运行的字段。

`runtime.json.phase` 由后端综合 `OrchestrationPhase`、文件解析、Skill 选择、工具执行和生成阶段写入。目标取值为：

| phase | 含义 |
| --- | --- |
| `routing` | 主持人或目标专家路由中。 |
| `planning` | 编排规划中。 |
| `executing` | 专家或 Skill 主执行中。 |
| `file_resolving` | 解析本轮附件和工作区文件引用。 |
| `file_resolved` | 文件引用解析完成。 |
| `skill_selecting` | 为专家选择 Skill。 |
| `agent_routed` | 已确定执行专家和 Skill。 |
| `tool_running` | 工具调用中。 |
| `assistant_generating` | 模型生成最终回复中。 |
| `finalizing` | 收尾、落盘历史和产物登记中。 |
| `awaiting_user` | 当前回合结束，等待用户补充或确认。 |
| `recruiting` | 当前回合结束，建议补充专家。 |
| `reviewing` | 主持人或审查步骤处理中。 |
| `completed` | 当前回合正常完成。 |
| `stopped` | 用户主动停止当前运行。 |
| `failed` | 当前运行失败或 stale runtime 被清理。 |

#### `orchestration_state.json`

`orchestration_state.json` 保存刷新不能丢的短期编排状态，供下一轮路由和后续上下文组装使用。

```json
{
  "continuation": {
    "owner_agent_name": "专家名称",
    "skill_policy": "keep",
    "skill": "skill-directory",
    "next_action": "面向上下文组装的下一步动作说明"
  },
  "host_scheduler": {
    "current_phase": "主持人当前阶段",
    "next_speaker": "专家名称 | user | end",
    "next_action": "主持人给下一位的动作说明"
  }
}
```

| 分组 | 字段 | 规则 |
| --- | --- | --- |
| `continuation` | `owner_agent_name` | 下一轮用户消息优先接回的专家名称。 |
| `continuation` | `skill_policy` | 只能是 `keep` 或 `release`。 |
| `continuation` | `skill` | 仅 `skill_policy=keep` 时填写；`release` 时不写，由专家重新选择 Skill。 |
| `continuation` | `next_action` | 统一承载下一轮接回专家时要执行的动作说明。 |
| `host_scheduler` | `current_phase` | 主持人的跨轮阶段记忆。 |
| `host_scheduler` | `next_speaker` | 主持人已经确定的下一位；为场内专家时优先于 `continuation`。 |
| `host_scheduler` | `next_action` | 主持人给下一位的动作说明。 |

旧字段 `runtime_state`、`pending_owner_agent_name`、`pending_skill`、`pending_phase`、`pending_required_user_fields`、`pending_handoff_reason`、`skill_session_owner_name`、`skill_session_skill`、`speaker_task`、`instruction`、`next_prompt` 不属于当前契约。保存 `session.json` 时必须拒绝或剔除这些字段；历史数据迁移可以单独处理，但主运行时不得用它们做兜底。

### 4.10 `/events/stream` 订阅事件

`GET /api/sessions/{session_id}/events/stream` 是会话状态订阅，不是聊天编排流。它只同步会话运行态、消息落盘通知和会话生命周期变化，不返回 `/chat/stream` 的 `route`、`progress`、`end` 事件。

| 事件 | 字段 | 规则 |
| --- | --- | --- |
| `snapshot` | `session_id`、`server_time`、`runtime`、`last_message_id`、`updated_at` | 连接成功后立即发送。 |
| `runtime` | `session_id`、`runtime` | `runtime.json` 变化时推送。 |
| `message` | 与 `history.json` 相同的完整消息结构 | 新消息落盘后可选推送；也允许前端收到通知后重拉详情。 |
| `keepalive` | `server_time` | 只用于保活，不改变业务状态。 |
| `deleted` | `session_id` | 会话被删除。 |
| `error` | `code`、`message` | 订阅错误。 |

浏览器关闭、标签页刷新或网络断开只取消本次订阅，不停止后端运行。停止当前回复必须调用 `POST /api/sessions/{session_id}/chat/stop`。

后端发现 `runtime.json.running=true` 但进程内任务不存在且超过过期阈值时，必须清理运行态并推送 `runtime` 事件，目标状态为 `running=false`、`phase="failed"`。新窗口通过 `GET /api/sessions/{session_id}` 读取历史消息；`/events/stream` 不回放历史 `/chat/stream` 事件。

### 4.11 前端状态与 mock 契约

前端状态只分两类：

| 类型 | 数据来源 | 允许字段 | 规则 |
| --- | --- | --- | --- |
| 会话事实 | 会话详情、`message` SSE、`/events/stream message` | 与 `history.json` 相同的消息结构 | 不保存顶层 `role`、`content`、`agent_name`、`timestamp`。 |
| 运行镜像 | `runtime.json`、`progress` SSE、`/events/stream runtime` | `running`、`run_id`、`phase`、`agent_name`、`skill`、`started_at` | `phase` 原样保存后再映射为 UI 文案。 |
| 本地 UI 暂态 | 前端组件内部 | `_streaming`、`_streamingStatus`、本地错误提示、滚动状态 | 只能用于当前页面展示，不写回 API、mock 或历史。 |

前端可以维护一张 `phase -> 展示文案` 映射表，但映射表不是业务状态机。所有分支判断必须基于后端事件和字段：`progress.phase`、`end.phase`、`end.waiting_for_user`、`end.suggested_next_speaker`、`end.suggested_add_agent_names`。前端不得从 `message.content` 正则解析招募建议、下一位专家、文件引用或路由结果；这些内容必须来自结构化字段。

发送用户消息后，附件属于该条用户消息事实。前端本地 composer 中的附件和草稿清理以“用户消息已发送并被当前回合接收”或 `end` 事件为准，不依赖 `discussion_ended`。传输失败时可以显示本地错误提示，但不能把本地错误当作服务端 `message` 写入会话事实。

`frontend/e2e/fixtures/mockApi.ts` 是接口契约的一部分。E2E mock 必须和真实 API 使用同一组事件名、字段名和消息结构：

- `/chat/stream` mock 只发送 `start`、`route`、`progress`、`message`、`end`、`error`。
- `/events/stream` mock 只发送 `snapshot`、`runtime`、`message`、`keepalive`、`deleted`、`error`。
- mock 消息必须使用 `speaker` + `message.content`，不得使用顶层 `role` / `content` / `agent_name`。
- mock 不得保留 `discussion_ended`、`meta.phase`、`tool_start`、`tool_result`、`session_update`、`skill_route_debug`、`expert_route_debug`。
- 测试中为单个用例手写的 `page.route(.../chat/stream)` 也必须遵守同一契约，不能绕过共享 mock 复活旧字段。

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

`build_tools_for_group_chat(agent_profile, session_id, resolved_skill)` 统一组装工具：

| 工具类型 | 来源 | 规则 |
| --- | --- | --- |
| MCP | Skill frontmatter `allowed-tools.mcp` | 只有本轮 Skill 声明的 MCP server 才加载。 |
| HTTP API | Skill frontmatter `allowed-tools.http_api` | 注入 `http_api_<name>` 工具。 |
| 工作区文件 | 内置工具 | 注入读、写、编辑、重命名、建目录、列目录。 |
| Skill 脚本 | 专家 `skills[].directory_name` | 磁盘存在 `SKILL.md` 时注入 `run_skill_script_<directory>`。 |
| MCP 配置状态 | 配置缺失时 | 注入 `mcp_configuration_status`，提示用户缺环境变量或配置。 |

这里的关键边界是：专家资源不再保存工具权限主契约；本轮工具权限由当前 Skill 的 frontmatter 决定。

### 5.3 脚本执行

脚本工具由 `backend/app/tools/run_skill_script.py` 创建，执行链路是：

```text
run_skill_script_<skill>
  -> create_run_skill_script_tool()
  -> UnifiedToolGateway
  -> SandboxService / OpenSandbox
```

目标脚本 stdout 结构化契约为：

```json
{
  "execution_status": "succeeded|blocked|failed",
  "content": "脚本文本而非总结",
  "artifacts": [
    {
      "type": "file | directory | image | table | json | markdown | other",
      "name": "用户可读名称",
      "path": "相对路径或资源路径"
    }
  ],
  "next_action": {
    "agent_turn": "respond|continue",
    "skill_session": "keep|release"
  }
}
```

脚本 stdout 必须显式输出 `next_action.agent_turn` 和 `next_action.skill_session`。`agent_turn` 只控制当前专家本轮是否继续行动，`skill_session` 只控制下一条用户消息是否继续回到同一专家和同一 Skill；二者是两个维度，`continue+keep`、`continue+release`、`respond+keep`、`respond+release` 四种组合都合法。平台只校验字段枚举和结构，不把某个组合硬判为非法。

脚本 stdout 缺少 `next_action`、字段缺失、枚举非法或 JSON 结构不合法时，按脚本协议失败处理：`execution_status=failed`、`agent_turn=respond`、`skill_session=release`，并向用户展示脚本输出不符合平台协议。

### 5.4 MCP 与 HTTP

MCP 工具走 `app.mcp.manager`。保存的 HTTP API 工具走 `create_http_api_tool()`，由资源中心保存的 URL、method、默认 query/header/body 决定请求目标；后端执行时必须做 SSRF、用户级环境变量引用和 URL 安全校验。

MCP / HTTP / workspace 工具本身不要求返回 `next_action`。这些工具执行后如果还需要 LLM 判断本轮继续还是回复用户、下一轮是否锁定 Skill，专家最终回复末尾必须追加隐藏状态块，并由隐藏状态块生成消息级 `skill_result.next_action`。工具调用参数、stdout、stderr、结构化返回和耗时属于执行 trace 或运行日志，不进入前端消息 payload，也不作为跨轮路由事实源。

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
| 用户补充后没有回到预期专家 | `orchestration_state.json.continuation`、`host_scheduler.next_speaker`、`next_action` | 主持人调度覆盖了续跑状态，或 continuation 被清理。 |
| 明明指定专家却跑了主持人 | `target_agent_name`、`agent_names` | `target_agent_name` 不在当前会话成员里，或请求校验未进入目标契约。 |
| 不该出现邀请专家条 | `agent_names`、`suggested_add_agent_names` | 后端后处理未清空，或前端 mock 仍伪造建议。 |
| 主持人输出后没有专家执行 | `next_speaker`、`agent_names`、`protocol_error` | `next_speaker` 不是场内专家名称，或主持人 JSON 严格解析失败。 |
| 专家选错 Skill | 后端路由日志、执行 trace、专家 `skills[].directory_name`、Skill 是否加载 | Skill 目录不存在、内容为空、多 Skill LLM 选择失败。 |
| 工具不存在 | `tool_attempt_debug.available_tools`、Skill frontmatter `allowed-tools` | 工具没有在当前 Skill 声明，或 MCP/HTTP API 配置缺失。 |
| 文件已生成但前端看不到 | 执行 trace、工作区路径、`write_workspace_file` 返回值、`skill_result.artifacts` | 模型口头声称保存，但工具未成功写入或产物未登记到 `artifacts`。 |
| 非流式 `/chat` 返回 message 不对 | `route.agent_name`、`message_events` | 聚合逻辑会优先选与 route 专家一致的最后一条 message。 |
| 文档和代码说法冲突 | 本文入口文件 | 旧文档可能还残留 id-based 或旧路径口径。 |

## 8. 验收建议

接口统一类改动建议至少验证：

```bash
rtk python -m py_compile backend/app/api/sessions.py backend/app/agent/group_chat_runtime.py backend/app/agent/group_host_decision.py backend/app/agent/group_orchestration_fsm.py backend/app/agent/expert_runtime.py backend/app/agent/tools_for_skill.py
rtk python -m pytest backend/tests/test_group_host_decision.py backend/tests/test_group_orchestration_fsm.py backend/tests/test_group_chat_stream_protocol.py -q
rtk npm --prefix frontend run build
```

如果改动触达前端邀请、指定专家、自动切换或 mock，再补：

```bash
rtk npx --prefix frontend playwright test frontend/e2e/workspace.spec.ts frontend/e2e/resources-scenario-expert.spec.ts
```

如果本地测试文件路径有调整，以当前 `rg --files | rg 'test_.*(group|host|session|workspace)'` 的结果为准。

## 9. 文档防漂移规则

后续凡是改以下契约，必须同步更新本文：

1. `GroupChatRequest` 请求字段。
2. 主持人严格 JSON 字段：`current_phase`、`next_speaker`、`next_action`、`suggested_add_agent_names`。
3. SSE `route` / `message` / `end` payload。
4. 会话定义字段：`title`、`title_auto_generated`、`agent_names`、`host`、`created_at`、`updated_at`。
5. Skill stdout / MCP tool result 结构化契约。
6. `host.name`、`agent_names`、`suggested_add_agent_names`、`orchestration_state.json.continuation` 等 name-based 字段。

如果只改代码不改本文，后续排查会重新陷入“跳转靠猜、字段靠记”的状态。
