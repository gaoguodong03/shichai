# 主持人 Skill 规范

主持人 Skill 只负责阶段判断和跨专家调度，不执行专家任务、不调用工作区或外部工具。

## 1. 主持人与专家的边界

| 维度 | 主持人 Skill | 专家 Skill |
| --- | --- | --- |
| 职责 | 判断阶段并生成标准主持人消息。 | 执行任务、调用工具、生成自然语言回复和产物。 |
| 输出 | `HostSchedulerDecisionPayload`。 | `expert_final_state.v2`。 |
| 路由 | 通过 `message.target_agent_name` 指定场内专家。 | 不指定下一位专家。 |
| 工作区 | 不读、不写。 | 按 Skill 需要读写。 |
| 续跑 | 不写专家续跑状态。 | 通过 `next_action.skill_session` 表达是否保留同一 Skill。 |

## 2. Frontmatter

```yaml
---
name: <场景名称>主持人
description: 当<场景>需要协调多个专家、管理确认点或推进阶段时使用；不用于执行专家任务。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---
```

一个场景只绑定一个主要主持人 Skill。主持人 Skill 正文使用专家名称，不使用 agent id。

## 3. 输出合同

主持人只输出一个 JSON 对象：

```json
{
  "current_phase": "当前协作阶段",
  "message": {
    "content": "给用户或下一位专家的自包含说明。",
    "target_agent_name": "场内专家名称",
    "attachments": [],
    "artifacts": []
  },
  "suggested_add_agent_names": []
}
```

字段含义：

| 字段 | 作用 |
| --- | --- |
| `current_phase` | 主持人的跨轮阶段记忆；不等于 SSE `phase`。 |
| `message.content` | 主持人可见说明，也是交给下一位专家的任务单。 |
| `message.target_agent_name` | 下一位场内专家名称；等待用户、招募或结束时省略。 |
| `message.attachments` | 主持人传给下一位专家的工作区附件。 |
| `message.artifacts` | 主持人需要向用户暴露的产物。通常为空。 |
| `suggested_add_agent_names` | 可邀请专家名称；出现时 `message.target_agent_name` 必须为空。 |

结束整个任务时，`current_phase` 写 `end`，并在 `message.content` 中给出完成说明。等待用户时保留当前阶段名，不填写 `target_agent_name`。

不得输出 `next_speaker`、`next_action`、`speaker_task`、`handoff`、`resume`、`reason`、`instruction`、`invite`、`announcement`、`task_done`、`next_prompt` 或任何 id 字段。

## 4. 调度规则

1. 先根据用户目标、最近消息和 `current_phase` 判断当前阶段。
2. 需要场内专家执行时，把完整任务单写入 `message.content`，把专家名称写入 `message.target_agent_name`。
3. 需要用户补充或确认时，不填写目标专家，并在正文中问清一个可回答的问题。
4. 需要新增专家时，不填写目标专家，通过 `suggested_add_agent_names` 给出建议并等待用户确认。
5. 专家结果已满足阶段退出条件时推进阶段；不要重复安排已经完成的动作。
6. 主持人只读取消息和结构化状态，不从工具日志、MCP 原文或文件名猜测业务状态。

## 5. 标准模板

主持人 Skill 正文至少包含：角色边界、场景角色、阶段表、调度规则、输出合同和常见错误。

阶段表建议：

| 阶段 | 目标 | 允许目标 | 退出条件 |
| --- | --- | --- | --- |
| 入口 | 判断任务类型和信息是否充分。 | 专家或用户 | 已确定下一步。 |
| 执行 | 安排一个专家完成一个明确阶段。 | 场内专家 | 专家已交付阶段结果。 |
| 确认 | 等待用户确认或补充。 | 用户 | 用户给出明确答复。 |
| 收束 | 确认最终产物已保存。 | 用户或结束 | `current_phase=end`。 |

常见错误：

- 用固定“下面由某专家发言”替代主持人真实任务单。
- 把路由信息写在自然语言里，却不填写 `message.target_agent_name`。
- 同时填写招募建议和目标专家。
- 主持人自行执行搜索、写作、生图或文件操作。
- 输出旧控制字段或解释文字，导致严格结构解析失败。

相关合同：`docs/contracts/runtime-interface-contract.md`、`docs/contracts/data-structure-and-field-logic.md`。
