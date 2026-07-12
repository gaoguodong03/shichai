# 书童四九 Skill 规范

本文定义 Skill 的目录、工具授权、专家最终输出、阶段门禁和上线验收。字段与运行语义以 `docs/contracts/runtime-interface-contract.md` 和 `docs/contracts/data-structure-and-field-logic.md` 为准。

## 1. 目录

```text
<directory_name>/
  SKILL.md
  scripts/              # 脚本型 Skill 可选
    manifest.json
    <entry>.py
  references/           # 可选稳定参考
  assets/               # 可选模板和静态资源
```

- `SKILL.md` 是唯一必需入口。
- 脚本只能位于当前 Skill 的 `scripts/`。
- 工作产物写入会话 workspace，不写入 Skill 目录。
- 没有 `scripts/manifest.json` 的脚本不注入为模型工具。

## 2. Frontmatter

```yaml
---
name: 示例技能
description: 当用户需要处理某类明确任务时使用；写清近似任务边界。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---
```

| 字段 | 规则 |
| --- | --- |
| `name` | 必填，用户可读名称。 |
| `description` | 必填，只写触发场景和边界，不复述完整流程。 |
| `allowed-tools.mcp` | 允许调用的 MCP server 名称。 |
| `allowed-tools.http_api` | 允许调用的已保存 HTTP API 工具。 |
| `allowed-tools.python` | 脚本所需 Python 依赖。 |

工作区 CRUD 是平台默认能力，不写入 `allowed-tools`。不要兼容旧 `mcp_server_ids`、`api`、`workspace`、`skill_script` 或通用 `call_api` 声明。

## 3. 正文结构

流程型 Skill 建议包含：角色边界、触发条件、输入要求、阶段与门禁、工具和文件规则、最终输出合同、常见错误。

脚本型 Skill 建议包含：调用时机、manifest 参数、stdout 合同、stderr 和退出码、产物规则、失败处理。

Skill 正文应给出可复制的当前合同，不用旧字段黑名单代替正向模板。

## 4. 工作区规则

- 新建产物优先使用 `create_workspace_artifact`；用户明确指定固定路径时才使用 `write_workspace_file`。
- `path` 是当前 workspace 相对路径，不写宿主机绝对路径或 `backend/data/`。
- `content` 是完整文件内容，不写“见上文”、摘要占位或路径说明。
- 修改已有文件前先列目录并读取真实路径；修改稿另存版本，不覆盖源文件。
- 只有工具成功后才能说文件已保存。
- 同一阶段允许一次写入多个必要产物。
- 工具级产物进入 `tool_result.output.artifacts`；用户可见产物由 finalizer 写入 `message.artifacts`。

## 5. 专家最终输出

所有专家 Skill 最终只输出一个严格 JSON 对象：

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "message": {
    "content": "给用户看的自然语言或 Markdown。",
    "attachments": [],
    "artifacts": [
      {"type": "markdown", "name": "结果文件", "path": "outputs/result.md"}
    ]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

字段规则：

| 字段 | 规则 |
| --- | --- |
| `schema_version` | 固定 `expert_final_state.v2`。 |
| `execution_status` | `succeeded`、`blocked`、`failed`。 |
| `message.content` | 面向用户的最终正文，不复制 MCP 原文、stdout、stderr 或工具 JSON。 |
| `message.attachments` | 传给后续处理的输入文件。 |
| `message.artifacts` | 本轮向用户暴露的产物，可为多个。 |
| `next_action.agent_turn` | `continue` 或 `respond`。 |
| `next_action.skill_session` | `keep` 或 `release`。 |

不得输出隐藏状态块、顶层 `content`、顶层 `artifacts`、`handoff`、`resume`、`reason`、`instruction`、`result_code` 或 `workflow_state`。

## 6. 工具后决策与 finalizer

MCP、HTTP 和 workspace 工具只返回工具事实，不返回专家最终消息或 `next_action`。

```text
LLM 决定调用工具
  -> 工具返回 output.content / json_data / artifacts
  -> LLM 判断继续调用工具或进入 finalizer
      -> 继续调用工具：不落最终专家消息
      -> 进入 finalizer：调用 submit_expert_final_state 提交 expert_final_state.v2
  -> 平台校验并生成 message + skill_result
```

`submit_expert_final_state` 是平台内部最终回复提交接口，不是 Skill 可声明或执行的业务工具，不产生 `tool_result`。模型只负责填写 `expert_final_state.v2`；平台按 Pydantic schema 校验并映射字段。平台不得把工具原文、工具摘要或中间 AIMessage 拼成 `message.content`。finalizer 缺失或结构非法时按协议失败，并保留执行日志。

## 7. 流程控制

- 当前专家还需行动：`agent_turn=continue`。
- 当前专家回复用户：`agent_turn=respond`。
- 下一条用户消息继续当前专家和 Skill：`skill_session=keep`。
- 下一轮回正常入口和主持人调度：`skill_session=release`。

等待用户确认并继续当前 Skill 的标准组合：

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "blocked",
  "message": {"content": "请用户确认具体事项。", "attachments": [], "artifacts": []},
  "next_action": {"agent_turn": "respond", "skill_session": "keep"}
}
```

阶段完成并释放 Skill 的标准组合：

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "message": {"content": "阶段完成说明。", "attachments": [], "artifacts": []},
  "next_action": {"agent_turn": "respond", "skill_session": "release"}
}
```

流程型 Skill 可在同一阶段连续执行多项动作，但在资料转写作、方案转生成、草稿转下一章节等跨阶段点必须暂停。详见 `docs/skills/skill-session-flow.md`。

## 8. 脚本型 Skill

脚本工具统一由 `scripts/manifest.json` 声明：

```json
{
  "entry": "process.py",
  "description": "处理输入并生成工作区产物。",
  "args": [
    {"name": "input_path", "description": "工作区相对路径", "required": true}
  ]
}
```

- manifest 只写 `entry`、`description`、`args`。
- 参数名使用 snake_case，平台转换为 CLI 参数。
- stdout 只输出 `expert_final_state.v2`；stderr 保存诊断；退出码表达成功或失败。
- 脚本 stdout 与 LLM finalizer 同时存在时必须一致，不允许按优先级猜测。
- 缺字段、非法枚举、额外旧字段或非 JSON 输出均按协议失败。

## 9. 主持人 Skill

主持人 Skill 使用 `HostSchedulerDecisionPayload`，不使用专家最终状态：

```json
{
  "current_phase": "当前阶段",
  "message": {
    "content": "给用户或下一位专家的说明。",
    "target_agent_name": "场内专家名称",
    "attachments": [],
    "artifacts": []
  },
  "suggested_add_agent_names": []
}
```

主持人不调用工具，不代替专家完成任务。完整规范见 `docs/skills/host-skill.md`。

## 10. 验收

上线前至少验证：

1. Frontmatter 可解析，工具授权使用当前字段。
2. 所有 JSON 示例可通过严格模型校验。
3. Skill 不含旧控制字段或隐藏状态块。
4. 工具执行后有 LLM finalizer，工具原文不会进入聊天气泡。
5. 产物真实存在，`message.artifacts` 使用 workspace 相对路径。
6. 等待点能写入 continuation，下一条用户消息回到同一 Skill。
7. release 后下一轮回到主持人或正常入口。
8. 跨阶段门禁不会被同一专家回合静默越过。
