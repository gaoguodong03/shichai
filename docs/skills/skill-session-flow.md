# Skill 流程控制协议

本文定义 Skill 的流程控制协议。平台支持两种结构化信号：

- 脚本型 Skill：脚本 stdout 输出标准 JSON。
- 非脚本或模型直接发言的 Skill：专家正文末尾追加平台隐藏状态块。

两种信号使用同一组字段和枚举值；普通用户聊天内容中不应出现这些协议字段。

## 1. 脚本 stdout 结构

脚本 stdout 必须输出一个 JSON 对象：

```json
{
  "execution_status": "succeeded",
  "result_code": "skill.initialized",
  "message": "Skill 模板目录已创建。",
  "artifacts": {
    "workspace_path": "skills/demo"
  },
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
  "result_code": "completed",
  "message": "处理完成。",
  "artifacts": {},
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
[[/SKILL_SESSION_STATE]]
```

仍需用户补充或当前专家继续处理：

```text
[[SKILL_SESSION_STATE]]
{
  "execution_status": "blocked",
  "result_code": "input.missing",
  "message": "缺少继续处理所需的信息。",
  "artifacts": {
    "required_fields": ["<需要补充的信息>"]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "keep"
  }
}
[[/SKILL_SESSION_STATE]]
```

隐藏状态块只表达当前 Skill 会话是否释放，不负责指定下一位专家。场景调度仍由主持人根据阶段、最近正文和会话状态决定。

## 3. 字段规范

| 字段 | 必填 | 类型 | 允许值 | 含义 |
| --- | --- | --- | --- | --- |
| `execution_status` | 是 | string | `succeeded` / `blocked` / `failed` | 当前步骤的执行结果。 |
| `result_code` | 是 | string | 稳定机器码，见下方命名规则 | 当前结果类型，不承担流程控制语义。 |
| `message` | 是 | string | 任意简短文本 | 给专家和平台看的简短说明。 |
| `artifacts` | 否 | object | JSON 对象 | 文件路径、统计数、结构化结果等。 |
| `next_action` | 否 | object | 见下方枚举 | 明确控制后续流程；缺省按 `respond` + `release` 处理。 |

### `execution_status`

| 值 | 使用场景 |
| --- | --- |
| `succeeded` | 当前步骤执行成功。成功不等于整个 Skill 工作流结束。 |
| `blocked` | 当前步骤没有完成目标，但用户补充参数、文件、确认后可以继续。 |
| `failed` | 当前步骤失败，当前参数下不能继续；需要专家说明原因或替代方案。 |

### `next_action.agent_turn`

控制当前专家回合内是否继续让模型行动。

| 值 | 平台动作 | 使用场景 |
| --- | --- | --- |
| `continue` | 继续让专家模型读取结果、编辑文件、调用下一个工具或做下一步。 | 初始化模板后还要写 `SKILL.md`、查询 manifest 后还要选择脚本。 |
| `respond` | 让专家模型基于脚本结果生成最终答复。 | 脚本已产出用户需要的结果，专家只需总结。 |

### `next_action.skill_session`

控制下一条用户消息是否继续回到同一专家和同一 Skill。

| 值 | 平台动作 | 使用场景 |
| --- | --- | --- |
| `keep` | 保留 Skill 会话锁。 | 需要用户补充、确认、继续上传文件，或多轮工作流尚未完成。 |
| `release` | 释放 Skill 会话锁，下一轮交回主持人调度。 | 当前 Skill 流程已完成，或后续应由主持人重新选择专家。 |

缺省规则：如果脚本未输出 `next_action`，平台按 `agent_turn=respond`、`skill_session=release` 处理。

## 4. `result_code` 命名规则

`result_code` 只描述“发生了什么”，不直接控制流程。推荐使用点分命名：

| 类型 | 示例 | 含义 |
| --- | --- | --- |
| 完成类 | `completed`、`file.generated` | 已生成最终结果。 |
| 中间步骤类 | `skill.initialized`、`manifest.loaded` | 成功完成一个中间步骤，通常配合 `agent_turn=continue`。 |
| 缺输入类 | `input.missing`、`file.missing` | 缺少用户输入或工作区文件，通常配合 `skill_session=keep`。 |
| 失败类 | `dependency.missing`、`runtime.failed` | 环境、依赖、运行时错误。 |

不要通过 `result_code` 暗示流程控制。例如 `skill.initialized` 本身不等于继续；真正的继续由 `next_action.agent_turn="continue"` 表达。

## 5. 推荐组合

### 最终完成

```json
{
  "execution_status": "succeeded",
  "result_code": "completed",
  "message": "结果文件已生成。",
  "artifacts": {
    "output_path": "outputs/result.md"
  },
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
  "result_code": "skill.initialized",
  "message": "Skill 模板目录已创建，请继续编辑 SKILL.md 并运行校验。",
  "artifacts": {
    "workspace_path": "skills/demo"
  },
  "next_action": {
    "agent_turn": "continue",
    "skill_session": "keep"
  }
}
```

### 输入阻塞

```json
{
  "execution_status": "blocked",
  "result_code": "input.missing",
  "message": "缺少目标文件路径。",
  "artifacts": {
    "required_fields": ["input_path"]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "keep"
  }
}
```

### 不可继续失败

```json
{
  "execution_status": "failed",
  "result_code": "runtime.failed",
  "message": "脚本运行失败，请查看错误信息。",
  "artifacts": {
    "stderr_tail": "..."
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

## 6. 冲突处理

脚本 stdout 和专家隐藏状态块只允许用 `next_action` 表达流程控制。同一份输出中不要给出互相矛盾的 `next_action.agent_turn` 或 `next_action.skill_session`。

当同一轮同时出现多个信号时，平台按“继续优先”处理：任一明确信号要求 `skill_session=keep` 时保留 Skill 会话锁；只有没有 `keep` 信号且存在 `release` 信号时才释放。

## 7. 专家回复规则

专家回复只负责把 `artifacts` 中的业务结果整理给用户。流程控制由脚本或 MCP 工具返回的 `next_action` 决定。

| 场景 | 专家应该怎么写 |
| --- | --- |
| `execution_status=succeeded` | 读取 `artifacts` 中的业务结果，直接交付结论、文本、路径、图片链接或统计摘要。 |
| `execution_status=blocked` | 说明 `message` 中缺少什么，并请用户补充。 |
| `execution_status=failed` | 说明 `message` 中的失败原因和可修正方式。 |
| `next_action.skill_session=keep` | 本轮回复面向用户补充或确认，下一条用户消息继续交给同一专家和 Skill。 |
| `next_action.skill_session=release` | 本轮回复交付完成，下一条用户消息交回主持人正常调度。 |

普通非脚本专家没有结构化工具结果或隐藏状态块时，单轮发言结束后默认释放 Skill 会话。对场景协作中的关键阶段成员，建议显式追加隐藏状态块，避免主持人无法区分“已完成本阶段”和“仍需同一专家继续”。
