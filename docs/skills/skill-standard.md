# 书童四九 Skill 规范

本文定义普通专家 Skill 的目录、Frontmatter、正文模板和平台职责边界。字段与运行语义以 `docs/contracts/runtime-interface-contract.md`、`docs/contracts/data-structure-and-field-logic.md` 和 `docs/skills/sandbox-tool-interface.md` 为准。

普通 Skill 用来描述一项可复用业务能力的执行方式和结束条件。专家长期职责写在专家资源中，场景阶段和跨专家调度写在主持人 Skill 中，平台协议不复制到普通 Skill。

## 1. 目录

```text
<directory_name>/
  SKILL.md
  scripts/              # 需要确定性脚本时可选
    manifest.json
    <entry>.py
  references/           # 可选稳定参考
  assets/               # 可选模板和静态资源
```

- `SKILL.md` 是唯一必需入口。
- 脚本只能位于当前 Skill 的 `scripts/`。
- 工作产物进入当前会话 workspace，不写入 Skill 目录。
- 没有 `scripts/manifest.json` 的脚本不作为本轮 Skill 工具加载。

## 2. Frontmatter

```yaml
---
name: 【Skill 名称】
description: 当【触发条件】时使用；不用于【近似但不适用的任务】。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---
```

| 字段 | 规则 |
| --- | --- |
| `name` | 必填，用户可读名称。 |
| `description` | 必填，只写触发条件和近似任务边界，不复述正文流程。 |
| `allowed-tools.mcp` | 本 Skill 允许调用的 MCP server 名称。 |
| `allowed-tools.http_api` | 本 Skill 允许调用的已保存 HTTP API 工具。 |
| `allowed-tools.python` | 当前 Skill 脚本所需 Python 依赖。 |

工作区能力由平台提供，不写入 `allowed-tools`。工具声明只使用以上当前字段，不增加兼容字段或通用工具入口。

## 3. 平台与 Skill 的职责边界

### 3.1 专家长期提示词与运行时负责

以下内容由专家长期提示词或运行时统一提供，不写入普通 Skill 正文：

- 项目整体提示词、专家职责和专家提示词。
- 当前专家绑定的 Skill 清单。
- 当前实际可用工具列表及通用工具调用说明。
- 工作区工具的路径、安全、版本化和真实写入合同。
- 脚本入口发现、工具命名和通用参数传递方式。
- 专家最终输出结构、字段枚举和通用流程控制语义。
- 工具结果回灌、聊天消息生成和内部流程控制映射。
- 主持人调度、跨专家交接和场景阶段推进。

普通 Skill 不复制专家最终 JSON，不解释技术流程控制字段，也不要求模型输出隐藏状态块。

### 3.2 普通 Skill 负责

普通 Skill 只定义：

- 这项业务能力特有的处理方式、顺序和质量要求。
- 业务上何时需要等待用户。
- 业务上何时已经完成或发生不可恢复失败。
- 当前能力特有的确认门禁、工具选择、文件、脚本或产物规则。

## 4. 通用模板

普通 Skill 正文只要求两个部分：`执行规则` 和 `结束条件`。

````markdown
---
name: 【Skill 名称】
description: 当【触发条件】时使用；不用于【近似但不适用的任务】。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---

# 【Skill 名称】

## 执行规则

1. 【第一项业务处理规则】。
2. 【必须遵守的业务顺序或确认门禁】。
3. 【当前 Skill 特有的工具、脚本、文件或产物规则】。
4. 【当前 Skill 特有的结果质量要求】。

## 结束条件

- 等待用户：当【缺少的输入、必须确认的事项或外部条件】时，向用户提出【最小必要问题】。
- 完成：当【可以验证的业务结果】已经形成时，向用户交付【实际结果或工作区产物】。
- 失败：当【不可恢复的业务失败条件】发生时，说明【真实失败原因和已经完成的部分】。
````

方括号内容是模板变量。创建具体 Skill 时必须替换或删除，不能把占位符带入可用资源。

`执行规则` 可以包含多条业务步骤，但不再为输入、工具、文件、脚本或产物建立固定附加章节；这些当前能力特有的要求直接写入执行规则。`结束条件` 必须写成可判断的业务事实，不能只写“任务完成后结束”。没有特殊不可恢复失败条件时可以删除“失败”一项。

## 5. 脚本资源

需要确定性执行时，使用 `scripts/manifest.json` 声明脚本：

```json
{
  "entry": "process.py",
  "description": "处理输入并生成业务结果。",
  "args": [
    {"name": "input_path", "description": "输入文件的工作区相对路径", "required": true}
  ]
}
```

- manifest 只声明 `entry`、`description` 和 `args`。
- 参数名使用 snake_case，描述业务含义，不暴露宿主机路径或底层命令行数组。
- `SKILL.md` 的执行规则只说明脚本调用时机、参数业务语义和结果要求。
- 脚本运行、结果回灌和失败日志合同统一见 `docs/skills/sandbox-tool-interface.md`，不复制进 Skill 正文。

## 6. 主持人 Skill

主持人 Skill 不使用本模板。主持人只负责具体场景的阶段判断和跨专家调度，完整规范见 `docs/skills/host-skill.md`。

## 7. 验收

上线前至少验证：

1. Frontmatter 可解析，`description` 只表达触发条件和边界。
2. `allowed-tools` 与本 Skill 真实需要的工具一致。
3. 正文包含非空的 `执行规则` 和 `结束条件`。
4. 结束条件使用自然语言说明等待用户、完成和适用时的失败事实。
5. Skill 不重复专家身份、长期职责、主持人调度、最终 JSON 或技术流程控制字段。
6. 正文不增加固定附加章节，不保留空章节或模板占位符。
7. 带脚本时，manifest 可解析，正文没有自造脚本路径、CLI 参数或工具名称。
8. 产物、工具和确认门禁可以通过真实执行场景验证。
