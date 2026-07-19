# Skill 会话流程控制协议

专家最终输出的唯一结构是 `expert_final_state.v2`。模型结构保持不变；平台严格校验后，把 `message`、`execution_status`、`agent_turn` 和 `skill_session` 投影给不同内部模块。工具结果、隐藏状态块和 deterministic summary 都不是消息来源。

## 1. 标准结构

```json
{
  "execution_status": "succeeded",
  "message": {
    "content": "给用户看的自然语言或 Markdown。",
    "attachments": [],
    "artifacts": []
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

| 字段 | 作用 |
| --- | --- |
| `execution_status` | `succeeded`、`blocked` 或 `failed`。 |
| `message` | 最终消息体，是专家消息落盘唯一入口。 |
| `message.content` | 前端气泡正文；不得直接复制工具原文。 |
| `message.attachments` | 传给后续处理的输入文件。 |
| `message.artifacts` | 本轮需要向用户暴露的产物引用，可包含多个。 |
| `next_action.agent_turn` | 下一次执行权是否继续给当前专家。 |
| `next_action.skill_session` | 同一专家后续被调用时是否沿用当前 Skill。 |

## 2. 两个控制维度

### `agent_turn`

- `continue`：当前专家仍需继续处理；平台先发布非空 `message`，再调度同一专家进入下一次 `agent_turn`。
- `respond`：当前专家结束本次执行；平台先发布非空 `message`，再把控制权交回主持人/编排层。

每次 `agent_turn` 内可以执行多个有依赖关系的工具步骤。MCP、HTTP、workspace 工具不输出 `next_action`；每批工具事实作为 `ToolMessage` 返回同一模型上下文，模型继续选择工具或输出最终状态。`next_action.agent_turn` 只决定是否进入下一次独立业务阶段，不用于补完当前工具链。

### `skill_session`

- `keep`：保留当前专家的当前 Skill 绑定；同一专家后续被调用时继续使用原 Skill。
- `release`：释放当前专家的当前 Skill 绑定；同一专家后续被调用时重新选择 Skill。

`agent_turn` 不决定 Skill 是否复用，`skill_session` 不决定下一次执行权归属。`agent_turn=respond` 交回主持人后，如果主持人再次选择同一专家，`skill_session=keep` 仍然要求沿用原 Skill。

平台内部按固定顺序处理：发布专家输出、更新 `skill_sessions`、应用 Agent Turn。消息 `skill_result` 只保存 `execution_status`，不保存 `next_action`。

## 3. 状态选择

等待用户且下一轮继续当前 Skill：

```json
{
  "execution_status": "blocked",
  "message": {"content": "请用户补充或确认具体事项。", "attachments": [], "artifacts": []},
  "next_action": {"agent_turn": "respond", "skill_session": "keep"}
}
```

阶段完成并交回正常调度：

```json
{
  "execution_status": "succeeded",
  "message": {"content": "阶段完成说明和产物路径。", "attachments": [], "artifacts": []},
  "next_action": {"agent_turn": "respond", "skill_session": "release"}
}
```

执行失败：

```json
{
  "execution_status": "failed",
  "message": {"content": "用户可理解的失败原因和可采取的下一步。", "attachments": [], "artifacts": []},
  "next_action": {"agent_turn": "respond", "skill_session": "release"}
}
```

如果失败只缺用户输入，并且补充后应继续当前 Skill，可以使用 `failed` 或 `blocked` 配合 `skill_session=keep`；Skill 正文必须明确选择规则。

## 4. 产物边界

产物引用结构：

```json
{"type": "markdown", "name": "报告", "path": "reports/report.md"}
```

- 真实内容写入 workspace 文件，不内嵌到产物引用。
- 工具产物先进入 `tool_result.output.artifacts` 和执行日志。
- 只有 finalizer 明确写入 `message.artifacts` 后，产物才显示在聊天消息上。
- 同一阶段允许一次产生多个产物。

## 5. 跨阶段门禁

流程型 Skill 可以在同一阶段连续调用多个工具、写入多个必要产物，但遇到以下门禁必须输出最终状态并暂停，不能静默跨阶段：

- 需要用户确认资料范围、方案、大纲、图片或草稿。
- 下一阶段会改变任务性质，例如从资料搜集进入写作。
- 下一阶段需要不同专家。
- 用户输入会实质影响下一阶段产物。

需要当前 Skill 继续时使用 `blocked + respond + keep`；阶段已经完成并应由主持人重新调度时使用 `succeeded + respond + release`。

## 6. 脚本 stdout

脚本型 Skill 的 stdout 可以直接输出 `expert_final_state.v2`，字段与非脚本 finalizer 完全一致。脚本输出与 LLM finalizer 同时存在时必须一致；冲突、缺字段、非法枚举或额外旧字段均按协议失败，不做兼容映射或程序合成回复。

禁止字段：`schema_version`、顶层 `content`、顶层 `artifacts`、`handoff`、`resume`、`reason`、`instruction`、`result_code`、`workflow_state` 和隐藏状态块标记。
