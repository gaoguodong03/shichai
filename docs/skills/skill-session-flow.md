# Skill 流程控制协议

本文定义 Skill 的流程控制协议。平台支持两种结构化信号：

- 脚本型 Skill：脚本 stdout 输出标准 JSON。
- 非脚本或模型直接发言的 Skill：专家正文末尾追加平台隐藏状态块。

两种信号使用同一组字段和枚举值；普通用户聊天内容中不应出现这些协议字段。

`next_action` 的生成位置必须明确：

- 脚本型 Skill 由脚本 stdout 手动返回 `next_action`。
- 非脚本 Skill、MCP / HTTP / workspace 工具后的专家判断，由专家最终回复末尾的隐藏状态块返回 `next_action`。
- 平台运行时消费这些信号后，统一沉淀为消息级 `skill_result.next_action`。工具执行记录只保存工具事实，不作为跨轮路由的第二个事实源。
- 脚本 stdout 缺少 `next_action`、字段缺失、枚举非法或 JSON 结构不合法时，按协议失败处理：`execution_status=failed`、`agent_turn=respond`、`skill_session=release`，并向用户展示脚本输出不符合平台协议。

## 1. 脚本 stdout 结构

脚本 stdout 必须输出一个 JSON 对象：

```json
{
  "execution_status": "succeeded",
  "content": "Skill 模板目录已新建。",
  "artifacts": [
    {
      "type": "directory",
      "name": "Skill 模板目录",
      "path": "skills/demo"
    }
  ],
  "next_action": {
    "agent_turn": "continue",
    "skill_session": "keep"
  }
}
```

脚本 stdout 必须只输出 JSON 对象，不要混入解释性文字、Markdown 或日志。日志应写入 stderr。

## 2. 专家隐藏状态块

非脚本 Skill、场景协作成员 Skill 或需要由模型直接判断结束点的 Skill，可以在专家正文末尾追加平台隐藏状态块。平台会读取状态块并从用户可见正文中移除。

实际输出时，状态块必须直接追加到正文末尾，不要放进 Markdown 代码块。

完成并交回主持人调度：

```text
[[SKILL_SESSION_STATE]]
{
  "execution_status": "succeeded",
  "content": "处理完成。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
[[/SKILL_SESSION_STATE]]
```

仍需用户补充且下一轮必须回到同一专家继续处理：

```text
[[SKILL_SESSION_STATE]]
{
  "execution_status": "blocked",
  "content": "缺少继续处理所需的信息。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "keep"
  }
}
[[/SKILL_SESSION_STATE]]
```

隐藏状态块只表达当前专家本轮是否继续行动，以及下一条用户消息是否继续回到同一专家和同一 Skill；它不负责指定下一位专家。场景调度仍由主持人根据阶段、最近正文和会话状态决定。

如果专家只是把确认问题交给用户，且用户回复后应由主持人重新判断下一阶段或重新选择专家，隐藏状态块应使用 `skill_session=release`。只有下一轮必须回到同一专家和同一 Skill 才使用 `skill_session=keep`。

## 3. 字段规范

| 字段 | 必填 | 类型 | 允许值 | 含义 |
| --- | --- | --- | --- | --- |
| `execution_status` | 是 | string | `succeeded` / `blocked` / `failed` | 当前步骤的执行结果。 |
| `content` | 是 | string | 任意文本 | 脚本或专家产出的正文结果；平台不做 LLM 总结或改写。 |
| `artifacts` | 是 | array | artifact item 数组 | 产物索引，只记录类型、用户可读名称和工作区路径；无产物时写 `[]`。 |
| `next_action` | 是 | object | 见下方枚举 | 明确控制后续流程。 |

`artifacts` 中每一项必须使用固定结构：

```json
{
  "type": "file | directory | image | table | json | markdown | other",
  "name": "用户可读名称",
  "path": "相对路径或资源路径"
}
```

`artifacts` 不内嵌正文、表格或 JSON 数据。即使产物类型是 `json`、`table` 或 `markdown`，真实内容也必须写入 workspace 文件，并通过 `path` 读取。

### `execution_status`

| 值 | 使用场景 |
| --- | --- |
| `succeeded` | 当前步骤执行成功。成功不等于整个 Skill 工作流结束。 |
| `blocked` | 当前步骤没有完成目标，但用户补充参数、文件、确认后可以继续。 |
| `failed` | 当前步骤失败，当前参数下不能继续；需要专家说明原因或替代方案。 |

### `next_action.agent_turn`

控制当前专家本轮是否继续行动，只影响本轮工具执行循环，不直接决定下一条用户消息归属。

| 值 | 平台动作 | 使用场景 |
| --- | --- | --- |
| `continue` | 继续让专家模型读取结果、编辑文件、调用下一个工具或做下一步。 | 初始化模板后还要写 `SKILL.md`、查询 manifest 后还要选择脚本。 |
| `respond` | 结束当前专家回合并把 `content` 作为本轮文本结果。 | 脚本已产出用户需要的正文结果，或需要把问题、失败原因、阶段结果交给用户。 |

### `next_action.skill_session`

控制下一条用户消息是否继续回到同一专家和同一 Skill，只影响跨轮路由，不决定当前专家本轮是否继续行动。

| 值 | 平台动作 | 使用场景 |
| --- | --- | --- |
| `keep` | 保留 Skill 会话锁。 | 需要用户补充、确认、继续上传文件，或多轮工作流尚未完成。 |
| `release` | 释放 Skill 会话锁，下一轮交回主持人调度。 | 当前 Skill 流程已完成，或后续应由主持人重新选择专家。 |

脚本 stdout 和专家隐藏状态块必须显式输出 `next_action`。平台不通过自然语言、`execution_status`、`content` 或文件产物反推 `agent_turn` / `skill_session`。

`agent_turn` 和 `skill_session` 是两个维度，四种组合都合法。平台只校验字段枚举和结构，不把某个组合硬判为非法。

| `agent_turn` | `skill_session` | 含义 |
| --- | --- | --- |
| `continue` | `keep` | 本轮继续让专家行动；下一条用户消息仍回到同一专家和 Skill。 |
| `continue` | `release` | 本轮继续让专家行动；本轮完成后不锁定下一条用户消息。 |
| `respond` | `keep` | 本轮回复用户；下一条用户消息继续回到同一专家和 Skill。 |
| `respond` | `release` | 本轮回复用户；下一条用户消息交回主持人或正常入口调度。 |

推荐语义：

- `blocked + respond + keep`：向用户补充参数、文件、链接或确认，并在用户回复后继续同一 Skill。
- `blocked + respond + release`：向用户说明等待或确认事项，但用户回复后应由主持人或入口路由重新判断。
- `failed + respond + release`：当前参数下不可继续，告知失败并释放 Skill 会话。
- `succeeded` 可以与四种组合搭配，取决于当前 Skill 是否还要继续本轮处理、以及是否需要跨轮锁定。

## 4. 推荐组合

### 最终完成

```json
{
  "execution_status": "succeeded",
  "content": "结果文件已生成。",
  "artifacts": [
    {
      "type": "markdown",
      "name": "结果文件",
      "path": "outputs/result.md"
    }
  ],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

### 工作流中间步骤

```json
{
  "execution_status": "succeeded",
  "content": "Skill 模板目录已新建，请继续编辑 SKILL.md 并运行校验。",
  "artifacts": [
    {
      "type": "directory",
      "name": "Skill 模板目录",
      "path": "skills/demo"
    }
  ],
  "next_action": {
    "agent_turn": "continue",
    "skill_session": "keep"
  }
}
```

### 本轮继续但不锁定下一轮

```json
{
  "execution_status": "succeeded",
  "content": "资料已读取，正在继续整理最终摘要。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "continue",
    "skill_session": "release"
  }
}
```

### 输入阻塞

```json
{
  "execution_status": "blocked",
  "content": "缺少目标文件路径。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "keep"
  }
}
```

### 等待用户且交回主持人

```json
{
  "execution_status": "blocked",
  "content": "等待用户确认下一步。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

### 不可继续失败

```json
{
  "execution_status": "failed",
  "content": "脚本运行失败，请查看 stderr 或执行 trace。",
  "artifacts": [],
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

## 5. 冲突处理

脚本 stdout 和专家隐藏状态块只允许用 `next_action` 表达流程控制。同一份输出中不要通过自然语言、额外字段或互相矛盾的隐藏状态块表达第二套流程控制。

同一轮最终只能沉淀一个消息级 `skill_result.next_action`。如果脚本 stdout、MCP / HTTP / workspace 工具后的专家隐藏状态块、或其他结构化信号之间互相冲突，平台应按协议失败处理，而不是按“继续优先”“释放优先”之类规则猜测。

与主持人调度、入口路由的合成规则见 [运行逻辑与接口契约](../contracts/runtime-interface-contract.md)。

## 6. 专家回复规则

脚本型 Skill 的流程控制由脚本 stdout 中的 `next_action` 决定。MCP / HTTP / workspace 工具本身不要求返回 `next_action`；这些工具执行后如果还需要 LLM 判断下一步，专家最终回复末尾必须追加隐藏状态块，由隐藏状态块决定 `skill_result.next_action`。

| 场景 | 专家应该怎么写 |
| --- | --- |
| `execution_status=succeeded` | 直接交付 `content`，并展示 `artifacts` 中的产物名称和路径。 |
| `execution_status=blocked` | 直接交付 `content`，请用户补充继续所需信息。 |
| `execution_status=failed` | 直接交付 `content`，必要时提示查看执行 trace 或 stderr。 |
| `next_action.skill_session=keep` | 本轮回复面向用户补充或确认，下一条用户消息继续交给同一专家和 Skill。 |
| `next_action.skill_session=release` | 本轮回复交付完成，下一条用户消息交回主持人正常调度。 |

未绑定流程型 Skill、也没有工具后续判断的普通自然语言专家，单轮发言结束后可默认释放 Skill 会话。绑定 Skill、场景协作关键阶段成员，或 MCP / HTTP / workspace 工具执行后需要决定本轮继续和跨轮锁定时，专家最终回复必须追加隐藏状态块，避免主持人无法区分“已完成本阶段”和“仍需同一专家继续”。
