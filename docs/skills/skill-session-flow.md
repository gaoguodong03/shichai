# Skill 脚本流程控制协议

本文定义 Skill 脚本 stdout 的标准 JSON 协议。Skill 脚本只应使用本文的字段名和枚举值。

## 标准输出结构

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

## 字段规范

| 字段 | 必填 | 类型 | 允许值 | 含义 |
| --- | --- | --- | --- | --- |
| `execution_status` | 是 | string | `succeeded` / `blocked` / `failed` | 当前脚本步骤的执行结果。 |
| `result_code` | 是 | string | 稳定机器码，见下方命名规则 | 当前结果类型，不承担流程控制语义。 |
| `message` | 是 | string | 任意简短文本 | 给专家和用户看的说明。 |
| `artifacts` | 否 | object | JSON 对象 | 文件路径、统计数、结构化结果等。 |
| `next_action` | 否 | object | 见下方枚举 | 明确控制后续流程；缺省按 `respond` + `release` 处理。 |

### `execution_status`

| 值 | 使用场景 |
| --- | --- |
| `succeeded` | 脚本步骤执行成功。成功不等于整个 Skill 工作流结束。 |
| `blocked` | 脚本没有完成目标，但用户补充参数、文件、确认后可以继续。 |
| `failed` | 脚本失败，当前参数下不能继续；需要专家说明原因或替代方案。 |

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

## `result_code` 命名规则

`result_code` 只描述“发生了什么”，不直接控制流程。推荐使用点分命名：

| 类型 | 示例 | 含义 |
| --- | --- | --- |
| 完成类 | `completed`、`file.generated` | 已生成最终结果。 |
| 中间步骤类 | `skill.initialized`、`manifest.loaded` | 成功完成一个中间步骤，通常配合 `agent_turn=continue`。 |
| 缺输入类 | `input.missing`、`file.missing` | 缺少用户输入或工作区文件，通常配合 `skill_session=keep`。 |
| 失败类 | `dependency.missing`、`runtime.failed` | 环境、依赖、运行时错误。 |

不要通过 `result_code` 暗示流程控制。例如 `skill.initialized` 本身不等于继续；真正的继续由 `next_action.agent_turn="continue"` 表达。

## 推荐组合

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

## 冲突处理

脚本只允许用 `next_action` 表达流程控制。同一份 stdout 中不要给出互相矛盾的 `next_action.agent_turn` 或 `next_action.skill_session`。

## 专家回复规则

专家回复只负责把 `artifacts` 中的业务结果整理给用户。流程控制由脚本或 MCP 工具返回的 `next_action` 决定。

| 场景 | 专家应该怎么写 |
| --- | --- |
| `execution_status=succeeded` | 读取 `artifacts` 中的业务结果，直接交付结论、文本、路径、图片链接或统计摘要。 |
| `execution_status=blocked` | 说明 `message` 中缺少什么，并请用户补充。 |
| `execution_status=failed` | 说明 `message` 中的失败原因和可修正方式。 |
| `next_action.skill_session=keep` | 本轮回复面向用户补充或确认，下一条用户消息继续交给同一专家和 Skill。 |
| `next_action.skill_session=release` | 本轮回复交付完成，下一条用户消息交回主持人正常调度。 |

普通非脚本专家没有结构化工具结果时，单轮发言结束后默认释放 Skill 会话。
