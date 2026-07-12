# 程序运行逻辑与接口契约统一说明

本文用于统一「一次会话请求到底怎么跑」以及「跳转和字段依赖应该由谁负责」。排查字段错位、主持人误跳转、专家续跑断链、前后端 mock 不一致时，先按本文定位。

本文记录目标运行契约；实现改造、测试和前端 mock 应以本文为准。当前改造重点入口：

- 后端会话 API：[`backend/app/api/sessions.py`](../../backend/app/api/sessions.py)
- 会话 CRUD / 事件流：[`backend/app/agent/group_session_service.py`](../../backend/app/agent/group_session_service.py)
- 会话状态存储：[`backend/app/api/group_chat_state.py`](../../backend/app/api/group_chat_state.py)
- 群聊运行时：[`backend/app/agent/group_chat_runtime.py`](../../backend/app/agent/group_chat_runtime.py)
- 入口路由与续跑状态：[`backend/app/agent/group_orchestration_fsm.py`](../../backend/app/agent/group_orchestration_fsm.py)
- 主持人严格输出与后处理：[`backend/app/agent/group_host_decision.py`](../../backend/app/agent/group_host_decision.py)
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
| 调度下一位 | `message.target_agent_name` |
| 下一步动作说明 | `message.content` |
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
4. 任何跳转问题都先查最新有效消息的 `message.target_agent_name`、`orchestration_state.json.continuation`、`orchestration_state.json.host_scheduler` 和 `history.json` 中的 Skill 结果。
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
| `message_id` | string | 前端生成的用户消息 id，用于幂等、落盘和日志关联，必填。 |
| `attachments` | array | 本轮用户附带的工作区文件引用。只引用已进入当前会话 `workspace/` 的文件，不承载原始上传流。 |
| `artifacts` | array | 用户消息主动暴露的工作区产物引用。 |
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
message?       # 主持人调度发言；用户指定专家时可省略
  -> route?    # 命中专家后发出
  -> progress* # 模型等待、工具运行、生成中等运行阶段
  -> message*  # 专家最终消息，或主持人收束消息
  -> end       # 本轮结束状态
```

异常时可能出现：

```text
message? -> error? -> end
```

前端目标契约只分发 `route`、`progress`、`message`、`end`、`error`。`progress` 是运行阶段事件，不承载最终正文；未来如需 token 级流式正文，应另定义 `delta` 事件，不能复用 `progress`。

### 2.5 黄金场景逐站数据结构（vNext）

本节按“协作写作最小黄金场景”串起一轮真实链路：用户提出创作目标，主持人生成标准消息，消息通过 `message.target_agent_name` 路由到专家，专家调用工具并由 LLM 生成最终自然语言回复，平台记录历史、日志和下一步状态。排查时优先沿本节顺序定位，不要从聊天气泡反推工具结果或路由状态。

vNext 的核心收敛点：

1. `message_id` 是唯一消息身份；用户消息由前端生成，主持人和专家消息由后端生成，不再使用 `client_message_id`。
2. `message` 是统一表达层；用户、主持人、专家都使用同一个 `MessageBody`。
3. `message.target_agent_name` 是统一路由入口；运行时优先级只决定“谁填写这个字段”，后续路由只读取这个字段。
4. `message.attachments` 表示本消息携带给后续处理的输入文件；用户、主持人、专家都可以使用。
5. `message.artifacts` 表示本消息产出或暴露给用户的产物；用户、主持人、专家都可以使用。
6. `tool_result.output` 统一承载工具输出；文本字段叫 `content`，结构化字段叫 `json_data`，产物字段叫 `artifacts`。
7. `skill_result` 不再保存 `content`；可见正文在 `message.content`，可见产物在 `message.artifacts`，工具原输出在执行日志。
8. `skill_result.next_action` 只保留 `agent_turn` 和 `skill_session` 两个维度。
9. 主持人不再输出 `next_speaker` / `next_action`；主持人输出 `current_phase`、`message`、`suggested_add_agent_names`。
10. 专家落盘只接受 `expert_final_state.v2`；工具执行后的中间 `AIMessage`、`ToolMessage`、deterministic tool summary 和 MCP 原文都不是可落盘专家回复。

```text
scenario.json
  -> session.json
  -> GroupChatRequest
  -> user ChatMessageRecord
  -> HostSchedulerDecisionPayload
  -> host ChatMessageRecord
  -> route/progress SSE
  -> expert runtime + tool_results
  -> ToolExecutionLogRecord
  -> LLM finalization
  -> expert_final_state.v2
  -> expert ChatMessageRecord(message + skill_result)
  -> orchestration_state.json
  -> message/end SSE
```

#### 2.5.1 场景模板：`resources/scenarios/{name}/scenario.json`

场景只在创建会话时作为初始化模板。会话创建后，运行时不再回读场景文件。

| 字段 | 作用 |
| --- | --- |
| `name` | 场景身份；资源中心按名称保存、导入和查找。 |
| `description` | 场景说明；用于列表、搜索和导出，不直接驱动运行时路由。 |
| `system_prompt` | 场景级说明；作为创建会话时的初始化材料，不是会话运行时主字段。 |
| `host` | 场景主持人快照；创建会话时复制到 `session.json.host`。 |
| `host.name` | 主持人显示名。 |
| `host.llm_name` | 主持人使用的模型名称。 |
| `host.system_prompt` | 主持人专属调度提示，只影响主持人行为。 |
| `host.skill_name` | 主持人 Skill 展示名快照；不作为运行时加载键。 |
| `host.skill_directory` | 主持人 Skill 目录名；运行时真正加载只认该字段。 |
| `agent_names` | 创建会话时初始化的专家名称列表。 |

#### 2.5.2 会话定义：`sessions/{session_id}/session.json`

`session.json` 是当前会话的运行资源快照。主持人和专家调度都只读取会话自己的 `host` 和 `agent_names`。

| 字段 | 作用 |
| --- | --- |
| `title` | 会话标题，前端左侧列表展示。 |
| `title_auto_generated` | 标识标题是否仍由后端自动维护；用户手动改名后不得自动改回。 |
| `agent_names` | 当前会话内可调度专家名单；`message.target_agent_name` 必须命中这里的专家名称。 |
| `host` | 本会话主持人快照。 |
| `host.name` | 主持人显示名，写入主持人消息 `speaker.agent_name`。 |
| `host.llm_name` | 主持人调度使用的模型。 |
| `host.system_prompt` | 主持人调度提示。 |
| `host.skill_directory` | 主持人 Skill 目录。 |
| `created_at` | 会话创建时间。 |
| `updated_at` | 会话定义或消息更新时刷新，用于列表排序。 |

#### 2.5.3 用户请求：`GroupChatRequest`

前端发送到 `/api/sessions/{session_id}/chat/stream` 的请求体必须是当前契约字段。

| 字段 | 作用 |
| --- | --- |
| `message_id` | 前端生成的用户消息 id；后端用它做幂等、落盘、日志关联和回滚定位。 |
| `message` | 用户本轮自然语言正文；进入落盘消息的 `message.content`。 |
| `attachments` | 本轮引用的当前会话工作区文件数组；进入落盘消息的 `message.attachments`。 |
| `attachments[].type` | 当前只允许 `workspace_file`。 |
| `attachments[].path` | 当前会话 `workspace/` 相对路径。 |
| `attachments[].name` | 附件展示名；不参与路径解析。 |
| `artifacts` | 用户消息主动暴露的产物数组；进入落盘消息的 `message.artifacts`。 |
| `target_agent_name` | 用户显式指定本轮交给某专家；进入落盘消息的 `message.target_agent_name`，且必须在 `session.json.agent_names` 中。 |

`message`、`attachments`、`artifacts`、`target_agent_name` 至少一个有效。旧字段 `client_message_id`、`action`、`agent_name`、`next_speaker`、`host_takeover_requested`、`ignore_auto_agent_name`、`ignore_auto_skill` 不属于 vNext 请求契约。

#### 2.5.4 历史消息：`ChatMessageRecord`

`history.json`、SSE `message` 事件和会话详情里的消息都使用同一个结构。

| 字段 | 作用 |
| --- | --- |
| `message_id` | 消息唯一身份；用户消息由前端生成，主持人和专家消息由后端生成。用于历史、幂等、删除、回滚、日志关联和前端渲染。 |
| `speaker` | 发言人结构。 |
| `speaker.type` | `user`、`host` 或 `expert`。 |
| `speaker.agent_name` | 主持人或专家名称；用户消息不得填写。 |
| `speaker.skill` | 本轮主持人或专家实际使用的 Skill；有 `skill_result` 时必须填写。 |
| `message` | 统一消息表达结构。 |
| `message.content` | 前端聊天气泡可见正文；不承载工具原文、stdout、stderr 或路由状态。 |
| `message.target_agent_name` | 路由目标专家；用户和主持人可以填写，专家原则上不填写。 |
| `message.attachments` | 本消息携带给后续处理的输入文件；用户、主持人、专家都可以填写。 |
| `message.artifacts` | 本消息产出或暴露给用户的产物；用户、主持人、专家都可以填写。 |
| `created_at` | 后端 16 位时间戳，格式 `YYYYMMDDHHmmssSS`。 |
| `skill_result` | 主持人或专家本步结构化状态；用户消息通常不填写。 |

#### 2.5.5 主持人配置：`HostSnapshot`

`HostSnapshot` 是会话中的主持人配置，不是主持人 LLM 输出。

| 字段 | 作用 |
| --- | --- |
| `name` | 主持人显示名。 |
| `llm_name` | 主持人模型名称。 |
| `system_prompt` | 主持人调度提示。 |
| `skill_directory` | 主持人 Skill 目录名。 |

#### 2.5.6 主持人严格输出：`HostSchedulerDecisionPayload`

主持人 LLM 的机器可读输出只允许以下三个顶层字段。主持人调度不再输出 `next_speaker` / `next_action`；它通过标准 `message` 表达下一步。

| 字段 | 作用 |
| --- | --- |
| `current_phase` | 主持人对当前协作阶段的判断；用于跨轮阶段记忆，不等于平台运行态 `phase`。 |
| `message` | 主持人要写入历史并推送给前端的标准消息体。 |
| `message.content` | 主持人可见交接或等待说明；当调度专家时，它就是给专家的任务单。 |
| `message.target_agent_name` | 主持人指定的下一位专家；存在时必须命中当前 `agent_names`。为空时表示等待用户、招募或结束。 |
| `message.attachments` | 主持人传给下一位专家的输入文件引用。 |
| `message.artifacts` | 主持人产出或暴露给用户的产物。 |
| `suggested_add_agent_names` | 可邀请专家名称数组；只有 `message.target_agent_name` 为空并等待用户确认招募时有效。 |

多余字段、非 JSON、非法专家名和旧字段都不是主持人业务回复。`next_speaker`、`next_action`、`speaker_task`、`reason`、`invite`、`announcement`、`task_done`、`next_prompt`、`handoff_reason` 不属于 vNext 主持人输出契约。

#### 2.5.7 主持人运行态：`orchestration_state.json.host_scheduler`

主持人输出通过校验后，可进入短期调度状态。运行态保存的是可恢复的主持人阶段和标准消息，而不是另一套路由字段。

| 字段 | 作用 |
| --- | --- |
| `current_phase` | 主持人的跨轮阶段记忆。 |
| `message` | 主持人已经形成但需要跨轮恢复的标准消息体。 |
| `message.target_agent_name` | 恢复后要路由到的专家；仍需先生成主持人可见消息。 |
| `message.content` | 主持人给下一步消费者的任务或说明。 |

#### 2.5.8 主持人消息：`ChatMessageRecord`

主持人调度到专家前，平台必须写入一条标准主持人消息。

| 字段 | 作用 |
| --- | --- |
| `speaker.type="host"` | 标识主持人发言。 |
| `speaker.agent_name` | 主持人名称，例如“四九”。 |
| `speaker.skill` | 主持人本轮实际使用的 Skill 目录名。 |
| `message.content` | 主持人交接文案或任务单，例如“信息检索专家，请围绕沈腾演艺生涯搜集资料。” |
| `message.target_agent_name` | 主持人指定的下一位专家。 |
| `message.attachments` | 主持人传给下一位专家的输入文件。 |
| `message.artifacts` | 主持人产出或暴露给用户的产物。 |
| `skill_result` | 主持人本步执行状态；不复用专家的 `next_action` 交接语义。 |

主持人调度动作如需排障，应进入执行日志，不能把主持人日志塞进 `message.content`。

#### 2.5.9 路由事件：SSE `route`

调度到专家后，后端发送 `route` 事件。

| 字段 | 作用 |
| --- | --- |
| `type` | 固定为 `route`。 |
| `run_id` | 当前运行 id。 |
| `agent_name` | 本轮被路由到的专家名称。 |
| `skill` | 本轮解析出的专家 Skill 目录名，可为空。 |

`route` 只表示执行目标，不是聊天消息。

#### 2.5.10 专家资源：`resources/agents/{name}/agent.json`

专家配置决定专家身份、模型、提示词和可选 Skill。

| 字段 | 作用 |
| --- | --- |
| `name` | 专家身份字段；`message.target_agent_name` 必须匹配该名称。 |
| `llm_name` | 专家使用的模型；为空则使用默认模型。 |
| `description` | 专家职责描述，会进入专家 prompt。 |
| `system_prompt` | 专家自有规则，会进入专家 prompt。 |
| `skills[].name` | Skill 展示名快照；不作为加载键。 |
| `skills[].directory_name` | Skill 真实加载目录；专家 Skill 选择和执行只认该字段。 |

#### 2.5.11 Skill 资源：`resources/skills/{directory_name}/SKILL.md`

Skill frontmatter 和正文共同决定专家本轮能力边界。

| 字段 | 作用 |
| --- | --- |
| `directory_name` | Skill 目录名，运行时唯一加载键。 |
| `name` | Skill 展示名。 |
| `description` | Skill 描述，多 Skill 选择时作为选择依据。 |
| `allowed-tools.mcp` | 本 Skill 允许加载的 MCP 工具名称数组。 |
| `allowed-tools.http_api` | 本 Skill 允许加载的 HTTP API 工具名称数组。 |
| `allowed-tools.python` | 沙箱依赖声明。 |
| 正文 | 注入专家系统提示，约束专家执行流程和输出要求。 |

专家资源不再保存工具权限主契约。本轮工具权限由当前 Skill frontmatter 决定。

#### 2.5.12 专家回合执行准备：`build_expert_turn_runtime()`

专家执行前，平台将专家、Skill、工具、模型和当前消息组装为可执行运行时对象。它只做执行准备，不负责主持人调度、工具结果展示、最终消息落盘或下一轮归属判断。

输入来源：

| 输入 | 作用 |
| --- | --- |
| `message.target_agent_name` | 指定要执行的专家。 |
| `message.content` | 本轮任务说明；用户消息或主持人消息都走同一字段。 |
| `message.attachments` | 本轮专家可使用的输入文件。 |
| `orchestration_state.continuation` | 判断是否锁定同一专家和同一 Skill。 |
| `agent.json` | 专家配置、模型、职责和可用 Skill。 |
| `SKILL.md` | 本轮 Skill frontmatter、正文和工具权限。 |

| 字段 / 对象 | 作用 |
| --- | --- |
| `blocked` | 专家执行是否被配置缺失、模型缺失、Skill 缺失等问题阻断。 |
| `skill` | 本轮实际使用的 Skill 目录名。 |
| `skill_route_diagnostics` | Skill 路由诊断信息；只用于日志和排障。 |
| `agent` | 实际执行模型和工具循环的 Agent。 |
| `tools` | 本轮注入给 Agent 的工具集合。 |

#### 2.5.13 进度事件：SSE `progress`

专家运行期间，后端发送 `progress` 事件同步运行阶段。

| 字段 | 作用 |
| --- | --- |
| `type` | 固定为 `progress`。 |
| `run_id` | 当前运行 id。 |
| `phase` | 当前运行阶段，必须与后端运行态一致。 |
| `agent_name` | 当前执行专家名称。 |
| `skill` | 当前执行 Skill 目录名。 |
| `text` | 阶段提示文本；不是最终回复正文。 |

`progress` 不得被前端渲染为聊天消息。

#### 2.5.14 工具执行结果：`tool_results`

工具循环内部会积累结构化工具结果。它是专家 finalizer、执行日志和排障事实的输入，不是前端消息 payload，也不是 `ChatMessageRecord.message` 的输入。

`tool_results` 只能进入以下位置：

1. 回灌给 LLM，供模型判断是否继续调用工具。
2. 交给专家 finalizer，供其生成 `expert_final_state.v2`。
3. 写入执行日志，供右侧终端 / 日志面板展示。

`tool_results` 不得直接生成或拼接：

1. `ChatMessageRecord.message.content`。
2. `ChatMessageRecord.message.artifacts`。
3. `skill_result.content` 或 `skill_result.artifacts`；这两个字段在 vNext 中不存在。

| 字段 | 作用 |
| --- | --- |
| `execution_status` | 工具本次执行结果，通常为 `succeeded`、`blocked` 或 `failed`。 |
| `tool_call` | 工具调用描述。 |
| `tool_call.id` | 工具调用 id。 |
| `tool_call.name` | 平台工具名。 |
| `tool_call.kind` | 工具类型，例如 `mcp`、`workspace`、`script`。 |
| `output` | 工具输出容器；只进入日志、结构化事实或 LLM 后续决策输入，不直接进入气泡。 |
| `output.content` | 工具输出的文本内容或摘要。 |
| `output.json_data` | 工具天然返回的结构化数据；可选。 |
| `output.artifacts` | 工具产生的用户可见产物引用。 |

`tool_result` 不设置顶层 `message`。工具的可读结果统一放在 `tool_result.output.content`；失败诊断放在 `error_log`。这里的 `output.content` 仍是工具事实，不是聊天消息正文。

MCP 原始正文、网页正文、stdout、stderr、调用参数和耗时属于工具结果或日志，不属于 `message.content`。如果工具产生了文件、图片或目录，工具层只能登记到 `tool_result.output.artifacts` 或执行日志 `output.artifacts`；是否作为用户可见产物出现在聊天消息里，必须由 finalizer 显式写入 `expert_final_state.v2.message.artifacts`。

#### 2.5.14.1 `tool_result`、Skill 执行上下文与 `skill_result` 的关系

三者不是逐层嵌套的三个响应对象：

| 名称 | 出现位置 | 生命周期 | 作用 |
| --- | --- | --- | --- |
| Skill 执行上下文 | 专家运行时内部 | 从选中 Skill 开始，到本步专家执行结束 | 提供 Skill 指令、允许工具、阶段规则和当前消息上下文；它是执行环境，不是落盘返回字段。 |
| `tool_result` | 专家工具循环和执行日志 | 每次工具调用产生一条或多条 | 把一次工具执行事实返回给当前 Skill 下的专家 LLM，供模型继续判断；不进入 `history.json`。 |
| `skill_result` | 最终专家 `ChatMessageRecord` | 专家本步形成最终状态时产生一次 | 保存本步 `execution_status` 和 `next_action`；不保存工具原文、可见正文或产物正文。 |

因此，正确返回方向是：

```text
当前专家 + 当前 Skill 执行上下文
  -> LLM 发起 tool_call
  -> 工具执行并返回 tool_result
  -> tool_result 回到同一专家、同一 Skill 的 LLM 上下文
  -> LLM 判断：继续调用工具，或进入 finalizer
      -> 继续：不生成 ChatMessageRecord，也不生成 skill_result
      -> finalizer：通过 submit_expert_final_state 提交 expert_final_state.v2
  -> 平台一次性拆分为：
      -> expert_final_state.v2.message -> ChatMessageRecord.message
      -> execution_status + next_action -> ChatMessageRecord.skill_result
```

这里不存在“工具先返回 `skill_result`，再由 `skill_result` 返回 `message`”的链路。`skill_result` 不是工具结果聚合容器，也不是 `message.content` 的素材仓库；它与 `message` 是同一个 `expert_final_state.v2` 经严格校验后生成的两个并列落盘结果。

平台必须遵守以下边界：

1. 工具执行器只能生产 `tool_result` 和执行日志，不能生产 `ChatMessageRecord.message`。
2. 专家工具循环只能把 `tool_result` 回灌给 LLM，不能用程序模板、字符串拼接或摘要函数把它转换成聊天正文。
3. 专家最终 LLM 必须同时决定面向用户的 `message` 与本步控制状态 `execution_status / next_action`，并输出 `expert_final_state.v2`。
4. 平台 finalizer 只负责结构化调用、严格校验和字段映射，不负责代替模型撰写自然语言。
5. finalizer 缺失、超时、返回空正文或结构非法时，本轮按协议失败；工具事实保留在日志中，不生成“工具已执行完成”之类的补丁消息。

`submit_expert_final_state` 是 finalizer 阶段的平台内部结构化提交接口，不是业务工具：它不执行 MCP、HTTP、workspace 或脚本动作，不生成 `tool_result`，也不写工具执行日志。平台把 `ExpertFinalStatePayload` 的 Pydantic schema 作为该接口参数 schema，要求模型恰好调用一次；参数校验通过后再映射为 `message + skill_result`。首次参数未通过 schema 校验时，只允许按同一 schema 重问一次，不允许从普通文本、Markdown 或工具原文中猜测和拼装字段。

#### 2.5.15 执行日志：`ToolExecutionLogRecord`

消息右侧终端日志读取执行日志，不读取聊天气泡。

| 字段 | 作用 |
| --- | --- |
| `log_id` | 日志记录 id。 |
| `message_id` | 关联的聊天消息 id；右侧终端按该字段拉取日志。 |
| `created_at` | 日志创建时间。 |
| `source` | 日志来源，只允许 `mcp`、`script`、`workspace`、`api`、`host`。 |
| `agent_name` | 产生该日志的主持人或专家名称。 |
| `skill` | 产生该日志的 Skill 目录名。 |
| `status` | 执行状态：`succeeded`、`blocked`、`failed`。 |
| `tool_call` | 工具调用详情。 |
| `tool_call.id` | 工具调用 id。 |
| `tool_call.name` | 平台工具名。 |
| `tool_call.provider` | MCP server、workspace、host 等提供方。 |
| `tool_call.provider_tool` | 提供方内部工具名。 |
| `tool_call.arguments` | 工具参数；前端应摘要或折叠展示。 |
| `output.content` | 工具输出的文本内容或摘要；前端应摘要或折叠展示。 |
| `output.json_data` | 工具结构化返回；前端可在详情中展示。 |
| `output.artifacts` | 本次工具调用产生的产物引用。 |
| `duration_ms` | 工具执行耗时。 |

#### 2.5.16 `message.content` 的组装规则

`message.content` 不是平台从工具原文拼出来的字段。它只来自明确的消息生产者：

1. 用户消息：由请求体 `message` 原样进入 `message.content`。
2. 主持人消息：由 `HostSchedulerDecisionPayload.message.content` 进入 `message.content`。
3. 专家消息：由专家最终 LLM 或脚本最终状态的 `message.content` 进入 `message.content`。

专家工具链路中的组装过程是：

```text
LLM 读取当前 message.content / attachments / 历史上下文
  -> LLM 决定调用工具
  -> 工具返回 tool_result.output.content / json_data / artifacts
  -> LLM 读取工具结果并判断是否继续调用工具或进入 finalizer
      -> 继续调用工具：不落最终专家消息
      -> 进入 finalizer：产出 expert_final_state.v2
  -> 平台校验 expert_final_state.v2
  -> 从 expert_final_state.v2.message 生成 ChatMessageRecord.message
  -> 从 expert_final_state.v2.execution_status / next_action 生成 ChatMessageRecord.skill_result
  -> 平台落盘 ChatMessageRecord
```

专家运行时不得把工具循环中的中间 `AIMessage.content` 通过累积、拼接、去重等方式组装成最终气泡。带 `tool_calls` 的 `AIMessage` 只表示模型决定调用工具；工具后的普通 `AIMessage` 也不能默认成为专家回复，除非它通过 finalizer 校验为 `expert_final_state.v2.message.content`。

deterministic tool summary 只属于平台内部失败诊断或日志摘要，不是专家自然语言回复。实现中不得用“工具已执行完成。以下是本轮工具返回摘要”或类似文本填充 `message.content`。

平台职责是校验、落盘和关联日志，不负责硬编码生成专家自然语言回复。若专家 finalizer 没有产出合格 `message.content`，平台按协议失败处理：保留执行日志，返回稳定错误码或失败状态，不把 MCP 原文、stdout、stderr 或 deterministic tool summary 拼成聊天气泡。

| 字段 | 作用 |
| --- | --- |
| `message.content` | 专家气泡可见正文。 |

#### 2.5.17 专家结构化结果：`skill_result`

专家消息的 `skill_result` 是 Skill 本步状态和控制信号，不承载可见正文和产物正文。

| 字段 | 作用 |
| --- | --- |
| `execution_status` | 专家 / Skill 本步结果：`succeeded`、`blocked`、`failed`。 |
| `next_action` | 当前专家回合结束后的结构化控制信号。 |

`skill_result` 不保存 `content`。可见回复读取 `message.content`，可见产物读取 `message.artifacts`，工具原始输出读取执行日志和 `tool_result.output`。

#### 2.5.18 产物引用：`ArtifactRef`

`message.artifacts`、`message.attachments`、`tool_result.output.artifacts` 和执行日志 `output.artifacts` 都使用公开产物引用。

| 字段 | 作用 |
| --- | --- |
| `type` | 产物类型：`file`、`directory`、`image`、`table`、`json`、`markdown`、`other`。 |
| `name` | 用户可读名称。 |
| `path` | 当前会话 workspace 相对路径。 |

`path` 不得指向 `memory/`、`checkpoints/` 或执行日志目录。前端可以把 `message.artifacts` 渲染为正文前的产物按钮，点击后在右侧预览；工具级产物仍在执行日志详情中展示。

#### 2.5.19 专家下一步控制：`SkillNextAction`

`skill_result.next_action` 只包含两个正交维度：当前专家本轮是否继续行动，以及下一条用户消息是否保持 Skill 会话。

| 字段 | 作用 |
| --- | --- |
| `agent_turn` | `continue` 或 `respond`；控制当前专家本轮是否继续行动。 |
| `skill_session` | `keep` 或 `release`；控制下一条用户消息是否继续回到同一专家和同一 Skill。 |

取值规则：

| 组合 | 含义 |
| --- | --- |
| `agent_turn=continue` | 当前专家本轮继续行动，例如继续调用工具、继续编辑文件或继续分析；不落最终专家消息。 |
| `agent_turn=respond` | 当前专家本轮停止工具行动并生成面向用户的消息；可以落专家消息。 |
| `skill_session=keep` | 下一条用户消息继续回到同一专家和同一 Skill。 |
| `skill_session=release` | 释放 Skill 会话锁，下一轮走正常入口或主持人调度。 |

#### 2.5.20 脚本 stdout / 专家 finalizer：`expert_final_state.v2`

脚本型 Skill stdout 或非脚本专家 finalizer 都必须直接产出同一个最终状态协议；不再解析隐藏状态块。

`expert_final_state.v2` 是专家消息落盘的唯一入口。无论专家使用 MCP、HTTP、workspace、脚本还是不调用工具，最终都必须归一到该结构。平台只从该结构生成 `ChatMessageRecord.message` 和 `ChatMessageRecord.skill_result`。

| 字段 | 作用 |
| --- | --- |
| `schema_version` | 固定为 `expert_final_state.v2`，用于协议版本校验。 |
| `execution_status` | 专家本步状态：`succeeded`、`blocked`、`failed`。 |
| `message` | 专家最终消息体；`agent_turn=respond` 时必须有非空 `message.content`。 |
| `message.content` | 专家最终自然语言回复。 |
| `message.attachments` | 专家传给后续处理的输入文件。 |
| `message.artifacts` | 专家本步产出或暴露给用户的产物。 |
| `next_action` | 专家回合结束后的控制信号。 |
| `next_action.agent_turn` | 当前专家本轮继续行动还是回复用户。 |
| `next_action.skill_session` | 下一条用户消息是否保持同一专家和同一 Skill。 |

缺字段、字段非法、枚举非法或出现冲突状态块，都按协议失败处理。

映射规则：

| `expert_final_state.v2` 字段 | 落盘字段 |
| --- | --- |
| `message` | `ChatMessageRecord.message` |
| `execution_status` | `ChatMessageRecord.skill_result.execution_status` |
| `next_action` | `ChatMessageRecord.skill_result.next_action` |

`expert_final_state.v2` 不允许携带 `tool_results`、`tool_raw_results`、`stdout`、`stderr`、MCP 原始正文或网页全文。需要排障的原始事实必须从执行日志读取。

#### 2.5.21 跨轮续跑：`orchestration_state.json.continuation`

当 `skill_result.next_action.skill_session=keep` 时，平台写入 `continuation`。

| 字段 | 作用 |
| --- | --- |
| `owner_agent_name` | 下一轮用户消息优先接回的专家名称。 |
| `skill_session` | 固定为 `keep`，表示保持同一专家和同一 Skill。 |
| `skill` | 记录继续使用的 Skill 目录名。 |
| `message` | 下一轮恢复时提供给主持人或专家的标准消息上下文。 |

`continuation` 不是当前轮消息，也不是主持人输出；它只在下一轮入口路由和上下文组装时生效。

#### 2.5.22 结束事件：SSE `end`

当前回复回合结束时，后端发送 `end`。

| 字段 | 作用 |
| --- | --- |
| `type` | 固定为 `end`。 |
| `run_id` | 当前运行 id。 |
| `phase` | 本轮结束状态：`awaiting_user`、`completed`、`recruiting`、`stopped`、`failed`、`timeout_or_budget_exceeded`。 |
| `waiting_for_user` | 是否等待用户继续输入或确认。 |
| `suggested_next_speaker` | 建议下一位；不是强制路由字段。 |
| `suggested_add_agent_names` | 推荐添加的专家名称数组。 |

`end` 表示当前回复回合结束，不表示整个会话关闭、归档或删除。

#### 2.5.23 字段边界速查

| 字段路径 | 正确职责 | 禁止职责 |
| --- | --- | --- |
| `message.content` | 聊天气泡正文 | 工具日志、MCP 原文、stdout、stderr、路由状态。 |
| `message.target_agent_name` | 统一路由入口 | 多套 `next_speaker` / `target_agent_name` 优先级分支。 |
| `message.attachments` | 本消息携带的输入文件 | 工具输出或执行日志。 |
| `message.artifacts` | 本消息对用户可见的产物 | 工具原始输出替代品。 |
| `skill_result.next_action.agent_turn` | 当前专家本轮继续行动或回复用户 | 下一条用户消息归属。 |
| `skill_result.next_action.skill_session` | 下一条用户消息是否保持同一专家和 Skill | 当前工具循环是否继续。 |
| `HostSchedulerDecisionPayload.message` | 主持人标准消息 | 旧 `next_speaker` / `next_action`。 |
| `tool_execution.output.content` | 右侧终端日志文本输出 | 聊天气泡正文。 |
| `tool_execution.output.json_data` | 工具结构化输出 | 聊天气泡正文。 |
| `tool_execution.source` / `provider` / `provider_tool` | 日志来源和工具归因 | 路由、Skill 选择或消息事实。 |
| `artifacts[].path` | workspace 产物路径 | 日志正文替代品。 |
| `orchestration_state.continuation` | 下一轮续跑意图 | 当前轮可见消息。 |

## 3. 跳转规则

跳转核心在 `group_chat_runtime.py::run_events()`，不是 API 层。

### 3.1 统一路由入口

路由执行阶段只读取一个字段：最新有效消息的 `message.target_agent_name`。所谓“优先级”只发生在进入路由前：平台需要决定由谁填写下一条标准消息。

| 填写来源 | 规则 | 产物 |
| --- | --- | --- |
| 用户显式选择专家 | 请求中的 `target_agent_name` 写入用户消息 `message.target_agent_name`。 | 用户消息直接成为路由消息。 |
| `continuation` 续跑 | 如果上一轮要求保持同一专家和 Skill，平台用 `continuation` 构造或提示主持人构造标准消息。 | 标准消息带 `message.target_agent_name`。 |
| 主持人调度 | 主持人输出 `HostSchedulerDecisionPayload.message`。 | 主持人消息带或不带 `message.target_agent_name`。 |
| 0 专家或需要招募 | 主持人消息不带 `target_agent_name`，并通过 `suggested_add_agent_names` 表达邀请建议。 | 等待用户确认。 |

`message` 正文不再承担路由控制职责。`@专家`、自然语言点名、`host_takeover_requested`、`ignore_auto_agent_name`、`ignore_auto_skill`、`action` 都不是当前请求契约；如出现在请求体顶层，应按非法字段拒绝。

主持人是多专家体系的控制平面。除用户通过 `target_agent_name` 明确指定本轮专家外，用户输入、专家交付、专家等待用户后的继续、阶段推进和结束判断都应先回到主持人。主持人调度到专家时必须生成一条标准主持人消息，例如“信息检索专家，请围绕沈腾演艺生涯搜集资料。”；该消息进入 `history.json`，并使用普通 `message` 事件推给前端。

统一路由决策的派生结果只允许以下内部字段：

```json
{
  "next_speaker": "专家名称 | user | end | invite",
  "next_action": "下一步动作说明",
  "route_source": "empty_group | target_agent | host_scheduler_state | continuation | host_scheduler",
  "skill_session": "none | keep",
  "skill": "skill-directory 或 null"
}
```

| 字段 | 规则 |
| --- | --- |
| `next_speaker` | 从 `message.target_agent_name` 派生的内部执行目标。专家名称必须在当前 `agent_names` 中；`user` 表示等待用户，`end` 表示结束，`invite` 只用于内部表达招募入口。 |
| `next_action` | 从 `message.content` 派生的内部任务说明。进入专家时作为专家 prompt 的任务文本。 |
| `route_source` | 仅后端内部和测试断言使用，不进入前端 API、SSE payload 或持久化业务数据。 |
| `skill_session` | `none` 表示正常选 Skill；`keep` 表示继续 `skill` 指定的 Skill。 |
| `skill` | 仅 `skill_session=keep` 时有值。 |

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

### 3.3 短期续跑状态

跨请求续跑意图由 `orchestration_state.json` 的 `continuation` 表示：

```json
{
  "continuation": {
    "owner_agent_name": "专家名称",
    "skill_session": "keep",
    "skill": "skill-directory",
    "message": {
      "content": "用户回复后继续由该专家使用该 Skill 处理。",
      "target_agent_name": "专家名称",
      "attachments": [],
      "artifacts": []
    }
  }
}
```

入口规则在 `resolve_group_entry_route()`：

| 条件 | 结果 |
| --- | --- |
| 请求指定了 `target_agent_name` | 写入用户消息 `message.target_agent_name`，并清理冲突的 `continuation`。 |
| `host_scheduler.message.target_agent_name` 是场内专家 | 先恢复主持人阶段，再由主持人发出可见交接消息后进入该专家。 |
| `continuation.owner_agent_name` 为空 | 走主持人。 |
| `continuation.owner_agent_name` 不在当前 `agent_names` | 走主持人，并清理 `continuation`。 |
| `continuation.skill_session == "keep"` | 把 owner、Skill 和 `message` 作为主持人调度提示；主持人通常应继续交给同一专家同一 Skill，但不得跳过主持人消息。 |
| 没有 `continuation` | 走主持人；主持人重新判断专家、用户或结束。 |

`message.content` 文本不清理 `continuation`。需要指定本轮专家时使用 `message.target_agent_name`；需要跨轮锁定或释放 Skill 时，由后端根据 `skill_result.next_action.skill_session` 和 `orchestration_state.json` 的结构化字段把状态交给主持人判断。

这表示：没有 `message.target_agent_name` 和存在 `continuation` 不是一回事。前者只是当前消息不路由专家；后者表示下一轮用户消息到来时，主持人应看到的续跑锁定意图和上下文依据。

### 3.4 主持人调度

主持人调度路径：

```text
_host_decide_by_agent(...)
  -> parse_strict_host_scheduler_output(...)
  -> finalize_host_scheduler_decision(...)
  -> _apply_decision_to_ctx(...)
```

主持人调度到专家时，平台先写入一条主持人可见消息，再进入专家执行。主持人消息仍使用标准消息结构：

```json
{
  "speaker": {
    "type": "host",
    "agent_name": "四九"
  },
  "message": {
    "content": "请文档合著专家发言。"
  }
}
```

主持人消息的正文来自平台对严格调度结果的展示化处理，不允许依赖旧字段 `announcement`、`speaker_task`、`next_prompt` 或 `handoff_reason`。主持人消息只负责说明交接，不承载工具日志、专家产物或隐藏状态块。

如果没有会话 `host` 或主持人失败，则进入协议错误或等待用户状态，不再回退到旧 `leader` 路径：

```text
message.target_agent_name = ""
interrupt_reason = "protocol_error"
```

主持人的结构化输出只允许：

```json
{
  "current_phase": "阶段",
  "message": {
    "content": "下一步动作说明",
    "target_agent_name": "专家名称",
    "attachments": [],
    "artifacts": []
  },
  "suggested_add_agent_names": ["可邀请专家名称"]
}
```

`current_phase` 和 `message` 必填，`suggested_add_agent_names` 可选。`suggested_add_agent_names` 出现时，`message.target_agent_name` 必须为空；招募不再使用 `"invite"` 表达。

平台所有要求 LLM 返回机器可读控制结构的调用，都必须经统一结构化输出入口完成严格 schema 校验。普通 JSON 输出走 `LLM raw output -> strict JSON object -> Pydantic model_validate`；专家 finalizer 走 `submit_expert_final_state arguments -> Pydantic model_validate`。该规则适用于主持人调度、专家 Skill 选择、专家 finalizer，以及以后新增的任何会驱动平台分支、路由、状态、工具、落盘或前端结构展示的 LLM 输出字段。专家最终正文虽然是自然语言，但必须作为 `expert_final_state.v2.message.content` 的字段通过结构化入口返回；普通标题、摘要和展示文案只有在不驱动平台落盘或状态机时，才不使用该入口。

`group_host_decision.py` 使用严格结构解析，`extra="forbid"`。多余字段、非 JSON、非法 `message.target_agent_name` 都不是可展示的主持人业务回复。主持人模型第一次输出未通过结构校验时，平台只允许按同一字段 schema 做一次协议重问；重问仍未通过时才转成系统保护决策，等待用户或管理员重试。平台不得从非标准文本中抽取字段、不得把模型解释文字当主持人消息展示，也不得把旧字段补丁化映射成当前字段。`next_speaker`、`next_action`、`speaker_task`、`reason`、`invite`、`next_prompt`、`task_done`、`announcement`、`phase`、`owner_agent_name`、`interrupt_reason`、`decision_source`、`handoff_reason`、`required_user_fields`、`suggested_order` 和 id 类字段都不是主持人 JSON 契约的一部分：

```text
message.target_agent_name = ""
interrupt_reason = "protocol_error"
announcement = "主持人输出格式错误，请重试或联系管理员。"
```

### 3.5 招募建议

`finalize_host_scheduler_decision()` 负责统一后处理：

| 情况 | 规则 |
| --- | --- |
| 已有场内专家且用户未明确要求加人 | 抑制模型误发的招募建议。 |
| 真实 0 成员 | 允许从主持人建议里提取可邀请专家。 |
| 招募建议被抑制 | 固定清空 `message.target_agent_name`，等待用户下一轮输入。 |
| 需要招募专家 | 固定清空 `message.target_agent_name`，并输出 `suggested_add_agent_names`。 |

因此接口层不要让前端自己猜“该不该招募”。前端只消费后端最终 `suggested_add_agent_names`。

### 3.6 专家执行循环

当最新有效消息的 `message.target_agent_name in agent_names` 且 `phase == executing`：

1. `build_expert_turn_runtime()` 解析本轮专家、Skill、工具和 LLM。
2. 发 `route` 事件：`run_id`、`agent_name`、`skill`。
3. 构造专家输入：讨论目标、当前 `message.content`、`message.attachments`、最近讨论。
4. `agent.astream(...)` 进入 `SimpleAgent` 工具循环。
5. 收集工具调用和结构化 `tool_results`；工具 stdout、stderr、退出码和耗时写入执行 trace 或运行日志。
6. 每次工具返回后回到 LLM 决策；LLM 可以继续调用工具，也可以进入 finalizer。
7. 从脚本 stdout 或专家 finalizer 解析 `expert_final_state.v2`，并校验 `message`、`execution_status`、`next_action`。
8. 从 `expert_final_state.v2.message` 写入专家消息，从 `expert_final_state.v2.execution_status / next_action` 写入 `skill_result`。
9. 根据 `skill_result.next_action.agent_turn` 判断当前专家本轮是否继续；根据 `skill_result.next_action.skill_session` 更新下一轮 `continuation`。

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
| `message_id` | 前端 | `_record_user_message_and_refresh_title()`、日志关联、回滚、删除 | 必填；用户消息唯一 id，用于幂等和消息事实身份。 |
| `attachments` | 前端文件选择 / 上传结果 | 工作区文件校验、专家上下文构造、工具文件访问 | 当前会话 workspace 内文件引用数组。 |
| `attachments[].type` | 前端 | 请求校验 | 当前只允许 `workspace_file`。 |
| `attachments[].path` | 前端文件 API 返回值 | 工作区路径校验、文件读取 | 必填，当前会话 `workspace/` 相对路径。 |
| `attachments[].name` | 前端 | 前端展示、专家上下文说明 | 可选展示名，不参与路径解析。 |
| `artifacts` | 前端 / 工作区文件选择 | 前端展示、后续上下文组装 | 用户消息主动暴露的产物数组。 |
| `target_agent_name` | 前端专家选择控件 | 写入 `message.target_agent_name`，再由统一路由读取 | 可选；存在时必须命中当前 `agent_names`。 |

请求校验规则：

1. `message_id` 必填且 trim 后非空。
2. `message`、`attachments`、`artifacts`、`target_agent_name` 至少一个有效。
3. `attachments` 只能引用当前会话工作区内已存在的文件；原始文件上传不走 `/chat/stream`，先走工作区文件 API。
4. `target_agent_name` 不在当前会话成员中时直接拒绝，不自动招募、不回主持人猜测。
5. 顶层多余字段一律拒绝，不静默忽略、不兼容旧字段。
6. `message` 正文中的 `【文件引用：...】` 和 `@专家` 不再是协议字段；历史文本可保留展示，但新请求不得依赖它们触发文件或路由逻辑。

### 4.3 主持人调度结果

| 字段 | 生产方 | 消费方 | 合法值 | 统一规则 |
| --- | --- | --- | --- | --- |
| `current_phase` | 主持人 | host message、scheduler state | 非空字符串 | 阶段描述，不等于平台 `phase`。 |
| `message` | 主持人 | host message、统一路由、专家 prompt | 标准 `MessageBody` | 主持人通过 `message.content` 表达任务，通过 `message.target_agent_name` 指定下一位专家。 |
| `message.content` | 主持人 | 前端展示、专家 prompt | 非空字符串 | 主持人可见交接说明；调度专家时就是专家本轮任务。 |
| `message.target_agent_name` | 主持人 | 统一路由 | 专家名称或空 | 专家必须在当前 `agent_names` 中；为空表示等待用户、招募或结束。 |
| `message.attachments` | 主持人 | 专家上下文组装 | workspace 文件引用数组 | 主持人转交给下一步的输入文件。 |
| `message.artifacts` | 主持人 | 前端展示、后续上下文 | 产物引用数组 | 主持人产出或暴露给用户的产物。 |
| `suggested_add_agent_names` | 主持人 | 前端邀请条 | 专家名称数组 | 只有 `message.target_agent_name` 为空时有效；后端可按当前成员状态抑制。 |

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

`tool_start`、`tool_result` 不作为顶层 SSE 业务事件。工具 stdout、stderr、退出码、调用参数、结构化返回和调用耗时属于执行 trace 或运行日志；面向用户可展示的最终产物写入 `message.artifacts`，工具级产物写入 `tool_result.output.artifacts` 或执行日志 `output.artifacts`。前端可以在消息右侧展示折叠的“终端/日志”入口，但该入口读取的是按 `message_id` 关联的运行日志，不改变 SSE 事件类型，也不把工具细节塞进 `message.content`。

工作区写入分两层：

- `create_workspace_artifact` 是模型优先使用的高层产物写入工具。模型只提供 `title`、`content`、可选 `kind` / `directory` / `extension`，平台负责生成安全文件名、附加当前时间戳、检测同名冲突并自动追加版本后缀（如 `-02`）。该工具用于新建大纲、正文、资料包、报告、阶段产物和最终产物。
- `write_workspace_file` 是低层路径写入工具。只有用户明确指定已有路径、固定文件名或确需 `overwrite=true` 时才使用；它按传入 `path` 原样写入，默认不覆盖同名文件。

模型不得为了规避冲突自行猜测时间戳、循环改文件名或在同名错误后随意传 `overwrite=true`。新产物的唯一命名和版本化是平台职责。

### 4.6 SSE message 事件

| 字段 | 生产方 | 消费方 | 统一规则 |
| --- | --- | --- | --- |
| `message_id` | 前端 / 后端 | 前端列表、删除消息、回滚、日志关联 | 用户消息由前端生成；主持人和专家消息由后端生成。 |
| `speaker.type` | 后端 | 前端渲染 | `user` / `host` / `expert`。 |
| `speaker.agent_name` | 后端 | 前端头像、发言人 | 主持人和专家消息填写；用户消息不填写。 |
| `speaker.skill` | 后端 | 前端 Skill 标识 | 主持人和专家消息可填写本轮实际 Skill 目录名。 |
| `message.content` | 后端 | 前端展示、后续上下文 | 最终展示文本。 |
| `message.target_agent_name` | 前端请求 / 主持人输出 / 后端落盘 | 统一路由、前端回显 | 用户和主持人可有；专家原则上不填写。 |
| `message.attachments` | 前端请求 / 主持人或专家输出 / 后端落盘 | 前端附件展示、后端上下文组装 | 用户、主持人、专家都可有，只允许当前会话 workspace 文件引用。 |
| `message.artifacts` | 前端请求 / 主持人或专家输出 / 后端落盘 | 前端产物按钮、右侧预览、后续上下文 | 用户、主持人、专家都可有，只允许公开 workspace 产物引用。 |
| `created_at` | 后端 | 前端时间 | 后端统一格式。 |
| `skill_result` | Skill / 后端落盘 | 执行状态、续跑判断 | 仅主持人或专家 Skill 消息可有；不保存可见正文或产物正文。 |

`skill_result.execution_status` 只允许 `succeeded`、`blocked`、`failed`。`blocked` 表示 Skill 或工具执行到明确等待点，需要用户补充材料、文件、链接、确认或参数；`failed` 表示本步失败。面向用户的失败原因写入 `message.content`，排障信息写入执行日志，`skill_result` 不保存 `content`。

消息事件不保存 `role`、顶层 `content`、顶层 `agent_name`、顶层 `skill`、`timestamp`、`turn_id`、`debug`、`required_user_fields`、`handoff_reason`、`interrupt_reason`、`presentation_content`、`tool_raw_results`、`tool_debug`、`tool_results` 作为核心字段。需要给用户看的补充说明使用 `message.content`；需要跨刷新接续的短期状态写入 `orchestration_state.json`。工具 stdout、stderr、退出码、调用参数、结构化返回和调用耗时只属于执行 trace 或运行日志，不进入前端消息 payload，也不进入提示词字段。

同名字段必须按命名空间读取：

| 字段路径 | 可进入 `message` 事件 | 可驱动路由 / 会话状态 | 说明 |
| --- | --- | --- | --- |
| `message.content` | 是 | 否 | 可见正文和上下文来源；不解析文件引用、专家路由或工具结果。 |
| `message.target_agent_name` | 是 | 是，统一路由入口 | 用户和主持人可填写；后续路由只读取该字段。 |
| `message.attachments` | 是 | 是，限上下文和文件读取 | 本消息携带给后续处理的输入文件。 |
| `message.artifacts` | 是 | 是，限前端产物展示和后续上下文 | 本消息产出或暴露给用户的产物。 |
| `tool_call.arguments.content` | 否 | 否 | 只属于工具调用参数；日志面板可摘要显示。 |
| `skill_result.execution_status` | 随 `skill_result` 进入 | 是，限 Skill 本步结果 | 不等于工具日志 `status` 或 SSE `phase`。 |
| `skill_result.next_action.agent_turn` | 随 `skill_result` 进入 | 是，限当前专家本轮是否继续 | 不决定下一条用户消息归属。 |
| `skill_result.next_action.skill_session` | 随 `skill_result` 进入 | 是，限下一条用户消息是否保持同专家同 Skill | 不决定当前工具循环是否继续。 |
| `tool_execution.status` | 否 | 否 | 只属于消息右侧工具日志。 |
| `progress.phase` / `end.phase` | 各自事件内 | 是，限前端运行态 | 不等于接口 `status` 或 Skill `execution_status`。 |
| `tool_execution.source` / `provider` / `provider_tool` | 否 | 否 | 只属于日志和 trace；不得作为路由、Skill 选择或消息事实。 |

工具日志 UI 以 `message_id` 为入口：消息右侧的终端图标只表示该消息有关联执行日志。点击后先展示折叠的工具日志列表，例如 `list_workspace_directory`、`write_workspace_file`；继续点击某一条日志，才展开该次工具调用的参数摘要、输出摘要、产物路径、错误和耗时。长参数或正文内容默认折叠，不在聊天气泡内直接展开。

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

`interrupt_reason`、`required_user_fields`、`handoff_reason`、`resume_target_agent_name`、`turn_id`、`token_version`、`next_prompt`、`instruction` 不属于目标 `end` 事件契约。需要跨刷新保存的接续信息写入 `orchestration_state.json.continuation.message`、`continuation.owner_agent_name`、`continuation.skill_session` 和 `continuation.skill`。

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
| `timeout_or_budget_exceeded` | 专家自动执行超过预算，当前回合中断并等待用户确认。 |

#### `orchestration_state.json`

`orchestration_state.json` 保存刷新不能丢的短期编排状态，供下一轮路由和后续上下文组装使用。

```json
{
  "continuation": {
    "owner_agent_name": "专家名称",
    "skill_session": "keep",
    "skill": "skill-directory",
    "message": {
      "content": "面向上下文组装的下一步动作说明",
      "target_agent_name": "专家名称",
      "attachments": [],
      "artifacts": []
    }
  },
  "host_scheduler": {
    "current_phase": "主持人当前阶段",
    "message": {
      "content": "主持人给下一位的动作说明",
      "target_agent_name": "专家名称",
      "attachments": [],
      "artifacts": []
    }
  }
}
```

| 分组 | 字段 | 规则 |
| --- | --- | --- |
| `continuation` | `owner_agent_name` | 下一轮用户消息优先接回的专家名称。 |
| `continuation` | `skill_session` | 固定为 `keep`；由 `skill_result.next_action.skill_session=keep` 推导。 |
| `continuation` | `skill` | 保持同一 Skill 时填写。 |
| `continuation` | `message` | 统一承载下一轮给主持人或专家判断的接续消息。 |
| `host_scheduler` | `current_phase` | 主持人的跨轮阶段记忆。 |
| `host_scheduler` | `message` | 主持人已经形成的标准消息；为场内专家时仍需先生成主持人交接消息。 |

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

- `/chat/stream` mock 只发送 `route`、`progress`、`message`、`end`、`error`。
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

多 Skill 选择属于机器可读 LLM 控制结构，必须通过统一结构化输出入口解析为 `ExpertSkillSelectionPayload` 后才能读取 `selected_skill`。运行时不得在专家 Skill 选择调用点手写 `ainvoke + raw.content + json.loads`，也不得从自然语言中猜测 Skill 名称。

### 5.2 工具组装

`build_tools_for_group_chat(agent_profile, session_id, resolved_skill)` 统一组装工具：

| 工具类型 | 来源 | 规则 |
| --- | --- | --- |
| MCP | Skill frontmatter `allowed-tools.mcp` | 只有本轮 Skill 声明的 MCP server 才加载。 |
| HTTP API | Skill frontmatter `allowed-tools.http_api` | 注入 `http_api_<name>` 工具。 |
| 工作区文件 | 内置工具 | 注入读、写、编辑、重命名、建目录、列目录。 |
| Skill 脚本 | 专家 `skills[].directory_name` + `scripts/manifest.json` | 同时存在 `SKILL.md` 和标准 `scripts/manifest.json` 时注入 `run_skill_script_<directory>`；模型只传 manifest `args` 生成的业务参数。 |
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
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded|blocked|failed",
  "message": {
    "content": "专家最终自然语言回复",
    "attachments": [],
    "artifacts": [
      {
        "type": "file | directory | image | table | json | markdown | other",
        "name": "用户可读名称",
        "path": "相对路径或资源路径"
      }
    ]
  },
  "next_action": {
    "agent_turn": "continue|respond",
    "skill_session": "keep|release"
  }
}
```

脚本 stdout 必须显式输出 `schema_version`、`execution_status`、`message` 和 `next_action`。`next_action.agent_turn` 控制当前专家本轮继续行动还是回复用户；`next_action.skill_session` 控制下一条用户消息是否保留同一专家和同一 Skill。`agent_turn=respond` 时 `message.content` 必须非空；`agent_turn=continue` 时不落最终专家消息。

脚本 stdout 缺少 `message` 或 `next_action`、字段缺失、枚举非法或 JSON 结构不合法时，按脚本协议失败处理：不合成专家回复，保留执行日志，并返回稳定协议错误。

### 5.4 MCP 与 HTTP

MCP 工具走 `app.mcp.manager`。保存的 HTTP API 工具走 `create_http_api_tool()`，由资源中心保存的 URL、method、默认 query/header/body 决定请求目标；后端执行时必须做 SSRF、用户级环境变量引用和 URL 安全校验。

MCP / HTTP / workspace 工具本身不要求返回 `next_action`。这些工具执行后回到 LLM 决策：LLM 可以继续调用工具，也可以进入专家 finalizer。最终进入聊天气泡的必须是 finalizer 生成并通过校验的 `expert_final_state.v2.message.content`，不是工具原始返回，也不是工具循环中的中间 `AIMessage.content`。工具调用参数、stdout、stderr、结构化返回、MCP 原始正文和调用耗时属于执行 trace 或运行日志，不进入前端消息 payload，也不作为跨轮路由事实源。

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
| 用户补充后没有回到预期专家 | `orchestration_state.json.continuation`、`host_scheduler.message.target_agent_name`、`message.target_agent_name` | 主持人调度覆盖了续跑状态，或 continuation 被清理。 |
| 明明指定专家却跑了主持人 | `target_agent_name`、`agent_names` | `target_agent_name` 不在当前会话成员里，或请求校验未进入目标契约。 |
| 不该出现邀请专家条 | `agent_names`、`suggested_add_agent_names` | 后端后处理未清空，或前端 mock 仍伪造建议。 |
| 主持人输出后没有专家执行 | `message.target_agent_name`、`agent_names`、`protocol_error` | `message.target_agent_name` 不是场内专家名称，或主持人 JSON 严格解析失败。 |
| 专家选错 Skill | 后端路由日志、执行 trace、专家 `skills[].directory_name`、Skill 是否加载 | Skill 目录不存在、内容为空、多 Skill LLM 选择失败。 |
| 工具不存在 | `tool_attempt_debug.available_tools`、Skill frontmatter `allowed-tools` | 工具没有在当前 Skill 声明，或 MCP/HTTP API 配置缺失。 |
| 文件已生成但前端看不到 | 执行 trace、工作区路径、`write_workspace_file` 返回值、`message.artifacts`、`tool_result.output.artifacts` | 模型口头声称保存，但工具未成功写入或最终消息未登记到 `message.artifacts`。 |
| 非流式 `/chat` 返回 message 不对 | `route.agent_name`、`message_events` | 聚合逻辑会优先选与 route 专家一致的最后一条 message。 |
| 文档和代码说法冲突 | 本文入口文件 | 旧文档可能还残留 id-based 或旧路径口径。 |

## 8. 验收建议

接口统一类改动建议至少验证：

```bash
rtk python -m py_compile backend/app/api/sessions.py backend/app/agent/group_chat_runtime.py backend/app/agent/group_chat_expert_turn.py backend/app/agent/group_host_decision.py backend/app/agent/group_orchestration_fsm.py backend/app/agent/expert_runtime.py backend/app/agent/tools_for_skill.py
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
2. 主持人严格 JSON 字段：`current_phase`、`message`、`suggested_add_agent_names`。
3. SSE `route` / `message` / `end` payload。
4. 会话定义字段：`title`、`title_auto_generated`、`agent_names`、`host`、`created_at`、`updated_at`。
5. Skill stdout / MCP tool result 结构化契约。
6. `host.name`、`agent_names`、`suggested_add_agent_names`、`orchestration_state.json.continuation` 等 name-based 字段。

如果只改代码不改本文，后续排查会重新陷入“跳转靠猜、字段靠记”的状态。
