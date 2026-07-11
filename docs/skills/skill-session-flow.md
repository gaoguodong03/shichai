# Skill 流程控制协议

本文定义 Skill 在专家回合结束时如何向平台声明结果、阶段边界和下一步交接。协议目标是让 workspace、MCP、HTTP API 和脚本工具后的专家回复都能进入同一条可验证链路：

```text
工具执行事实 -> 专家最终回复 -> 隐藏状态块或脚本 stdout -> skill_result -> 编排状态
```

工具执行记录只保存工具事实，不作为跨轮路由或阶段门禁的第二个事实源。跨阶段暂停、下一轮续跑、最终结束都必须通过消息级 `skill_result.next_action` 表达。

## 1. 结构化信号来源

平台支持两种结构化信号，它们使用同一组字段：

- 脚本型 Skill：脚本 stdout 输出标准 JSON。
- 非脚本 Skill、MCP / HTTP / workspace 工具后的专家最终回复：正文末尾追加平台隐藏状态块。

普通用户聊天内容中不应出现这些协议字段。

脚本 stdout 缺少 `next_action`、字段缺失、枚举非法或 JSON 结构不合法时，按协议失败处理：`execution_status=failed`、`next_action.handoff=host`、`next_action.resume=none`，并向用户展示协议错误。

## 2. 标准结果结构

脚本 stdout 和专家隐藏状态块都使用同一个 JSON 对象：

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "markdown",
      "name": "结果文件",
      "path": "outputs/result.md"
    }
  ],
  "next_action": {
    "handoff": "user",
    "resume": "same_skill",
    "reason": "stage_gate",
    "instruction": "当前阶段：资料搜集。请用户确认资料范围是否足够；确认后继续进入大纲生成阶段。"
  }
}
```

字段规范：

| 字段 | 必填 | 类型 | 含义 |
| --- | --- | --- | --- |
| `schema_version` | 是 | string | 固定为 `expert_final_state.v2`。 |
| `execution_status` | 是 | string | 当前专家步骤结果：`succeeded` / `blocked` / `failed`。 |
| `artifacts` | 是 | array | 产物索引，只记录类型、用户可读名称和工作区路径；无产物时写 `[]`。 |
| `next_action` | 是 | object | 专家回合结束后的交接、下一轮续跑和动作说明。 |

`content` 不再写入隐藏状态块。专家给用户看的正文就是 `message.content`；脚本型 Skill 的 stdout 可通过上层封装把用户可见正文写入消息内容，再把状态 JSON 写入结构化结果。平台不得在隐藏状态块中维护第二份正文，避免正文与控制状态漂移。

## 3. `artifacts`

`artifacts` 中每一项必须使用固定结构：

```json
{
  "type": "file | directory | image | table | json | markdown | other",
  "name": "用户可读名称",
  "path": "相对路径或资源路径"
}
```

`artifacts` 不内嵌正文、表格或 JSON 数据。即使产物类型是 `json`、`table` 或 `markdown`，真实内容也必须写入 workspace 文件，并通过 `path` 读取。

同一专家回合可以产生多个 artifact。平台不限制同一阶段内的写入次数；平台限制的是跨阶段推进必须经过明确交接。

## 4. `execution_status`

| 值 | 使用场景 |
| --- | --- |
| `succeeded` | 当前专家步骤成功。成功不等于整个 Skill 工作流结束。 |
| `blocked` | 当前步骤没有完成目标，但用户补充参数、文件、确认后可以继续。 |
| `failed` | 当前步骤失败，当前参数下不能继续；需要专家说明原因或替代方案。 |

`execution_status` 只说明当前步骤结果，不决定下一位发言者。下一步由 `next_action` 明确表达。

## 5. `next_action`

`next_action` 是专家回合结束后的唯一流程控制字段。它不控制工具循环内部是否继续调用工具；工具循环内部的继续、重试和最终合成由运行时负责。

```json
{
  "handoff": "user",
  "resume": "same_skill",
  "reason": "stage_gate",
  "instruction": "请用户确认资料范围是否足够，确认后继续进入大纲生成阶段。"
}
```

### `next_action.handoff`

控制当前专家回合结束后交给谁。

| 值 | 平台动作 | 使用场景 |
| --- | --- | --- |
| `user` | 当前 stream 结束，`waiting_for_user=true`。 | 等用户补充、选择、确认、上传文件或决定是否进入下一阶段。 |
| `host` | 当前专家完成发言后交回主持人调度。 | 专家完成本阶段，应由主持人判断下一专家、下一阶段或是否结束。 |
| `end` | 当前任务完成，结束本轮流程。 | 最终交付完成，不需要继续调度。 |

### `next_action.resume`

控制下一条用户消息到来时的续跑意图。

| 值 | 平台动作 | 使用场景 |
| --- | --- | --- |
| `same_skill` | 在 `orchestration_state.json.continuation` 中记录同一专家同一 Skill。 | 用户确认后应回到同一专家继续该流程。 |
| `same_agent` | 记录同一专家，但允许重新选择 Skill。 | 用户补充后仍应由同一专家处理，但不要求锁定当前 Skill。 |
| `host` | 不锁定专家或 Skill，下一轮交主持人判断。 | 用户回复后可能需要换专家或重新拆分任务。 |
| `none` | 无续跑意图。 | 任务完成或失败收束。 |

`handoff=user` 与 `resume` 不是同一件事：`handoff=user` 表示当前 stream 等用户；`resume` 表示下一条用户消息来时应如何进入编排。

### `next_action.reason`

说明本次交接原因，供运行时、日志和主持人提示使用。

允许值：

- `stage_gate`：阶段门禁，例如资料搜集完成后等确认再进入写作。
- `missing_input`：缺参数、链接、文件、字段或选择。
- `user_confirmation`：等待用户确认当前结果或修改意见。
- `stage_completed`：当前专家阶段完成，交回主持人判断。
- `final_delivery`：最终产物已交付。
- `failure`：失败收束。
- `protocol_error`：结构化协议错误。

### `next_action.instruction`

面向下一步消费者的自包含动作说明：

- `handoff=user` 时，它是给用户看的补充/确认提示。
- `handoff=host` 时，它是主持人判断下一步的依据。
- `handoff=end` 时，它是完成说明。

`instruction` 不是第二套正文；用户可见正文仍以 `message.content` 为准。`instruction` 应短、明确、可路由。

阶段名、当前等待点、用户需要确认的问题和确认后的下一步，不单独新增字段；统一写入 `next_action.instruction`。跨轮续跑意图由 `next_action.resume` 推导到 `orchestration_state.continuation`。

## 6. 专家隐藏状态块

非脚本 Skill、场景协作成员 Skill 或需要由模型判断结束点的 Skill，应在专家最终回复末尾追加隐藏状态块。平台会读取状态块并从用户可见正文中移除。

实际输出时，状态块必须直接追加到正文末尾，不要放进 Markdown 代码块。

等待用户确认并保持同一 Skill：

```text
我已经把资料整理保存到工作区：

- 沈腾演艺生涯资料.md

请确认资料范围是否足够；确认后我再继续生成大纲。

[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "markdown",
      "name": "沈腾演艺生涯资料",
      "path": "沈腾演艺生涯资料.md"
    }
  ],
  "next_action": {
    "handoff": "user",
    "resume": "same_skill",
    "reason": "stage_gate",
    "instruction": "当前阶段：资料搜集。请用户确认资料范围是否足够；确认后继续生成大纲。"
  }
}
[[/SKILL_SESSION_STATE]]
```

交回主持人判断：

```text
我已经完成资料整理，文件已保存。接下来适合由主持人判断是否进入写作专家。

[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [],
  "next_action": {
    "handoff": "host",
    "resume": "none",
    "reason": "stage_completed",
    "instruction": "资料整理阶段已完成，请主持人判断是否进入写作阶段。"
  }
}
[[/SKILL_SESSION_STATE]]
```

最终交付：

```text
文章已完成并保存到工作区。

[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "markdown",
      "name": "最终文章",
      "path": "沈腾演艺生涯介绍-最终稿.md"
    }
  ],
  "next_action": {
    "handoff": "end",
    "resume": "none",
    "reason": "final_delivery",
    "instruction": "文章合著流程完成。"
  }
}
[[/SKILL_SESSION_STATE]]
```

## 8. 脚本 stdout 结构

脚本 stdout 必须输出单个 JSON 对象。脚本日志写入 stderr，不要混入 stdout。

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "file",
      "name": "处理结果",
      "path": "outputs/result.json"
    }
  ],
  "next_action": {
    "handoff": "host",
    "resume": "none",
    "reason": "stage_completed",
    "instruction": "脚本处理已完成，请主持人判断下一步。"
  }
}
```

脚本 stdout 只表达结构化结果；用户可见正文由专家或运行时基于脚本结果生成。平台不得把 stdout/stderr、调用参数、耗时或调试字段写入 `history.json` 的业务消息结构。

## 9. 冲突处理

同一轮最终只能沉淀一个消息级 `skill_result.next_action`。如果脚本 stdout、专家隐藏状态块或其他结构化信号之间互相冲突，平台按协议失败处理，而不是按“继续优先”“释放优先”之类规则猜测。

协议失败时：

- `execution_status=failed`
- `next_action.handoff=host`
- `next_action.resume=none`
- `next_action.reason=protocol_error`
- `next_action.instruction` 说明协议错误

## 10. 工具后最终回复

MCP / HTTP / workspace 工具本身不要求返回 `next_action`。这些工具执行后必须进入专家最终回复阶段：

1. 运行时把工具结果交给模型或平台 finalizer。
2. finalizer 禁止再次调用工具。
3. finalizer 必须产生用户可见正文。
4. 对绑定 Skill 或场景协作专家，finalizer 必须产生合法隐藏状态块。
5. 如果模型只返回工具摘要、空文本或继续请求工具，平台应生成协议失败或安全兜底回复，不得把裸工具摘要当成专家消息。

## 11. 典型流程组合

| 场景 | `execution_status` | `handoff` | `resume` | `reason` |
| --- | --- | --- | --- | --- |
| 资料搜集完成，等用户确认再写大纲 | `succeeded` | `user` | `same_skill` | `stage_gate` |
| 缺少目标文件路径 | `blocked` | `user` | `same_skill` | `missing_input` |
| 当前专家阶段完成，交回主持人判断 | `succeeded` | `host` | `none` | `stage_completed` |
| 最终产物完成 | `succeeded` | `end` | `none` | `final_delivery` |
| 当前参数下失败且无法继续 | `failed` | `host` | `none` | `failure` |

流程型 Skill 的阶段门禁应使用 `handoff=user` 或 `handoff=host` 表达。平台允许同一阶段内生成多个工作区产物；不允许在已经声明阶段门禁后继续静默跨到下一阶段。
