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

### 3.1 平台负责

以下内容由平台统一提供，不写入普通 Skill 正文：

- 项目整体提示词、专家职责和专家提示词。
- 当前专家绑定的 Skill 清单。
- 当前实际可用工具列表及通用工具调用说明。
- 工作区工具的路径、安全、版本化和真实写入合同。
- 脚本入口发现、工具命名和通用参数传递方式。
- 专家最终输出结构、字段枚举、校验和协议失败处理。
- 工具结果回灌、聊天消息生成和内部流程控制映射。
- 主持人调度、跨专家交接和场景阶段推进。

普通 Skill 不复制平台 JSON 示例，不解释平台流程控制字段，不列旧字段黑名单，也不要求模型输出隐藏状态块。

### 3.2 普通 Skill 负责

普通 Skill 只定义：

- 这项业务能力特有的处理方式、顺序和质量要求。
- 业务上何时需要等待用户并保留当前 Skill。
- 业务上何时已经完成并释放当前 Skill。
- 确有必要时的阶段门禁、工具选择、文件、脚本或产物规则。

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

- 【本 Skill 特有的处理方式】。
- 【必须遵守的业务顺序或质量要求】。
- 【需要时在这里写输入、工具、文件或脚本规则】。

## 结束条件

- 当【需要用户补充或确认的条件】时，向用户提出具体问题，并保留当前 Skill。
- 当【本 Skill 的业务结果完成条件】满足时，说明实际结果，并释放当前 Skill。
````

方括号内容是模板变量。创建具体 Skill 时必须替换或删除，不能把占位符带入可用资源。

`执行规则` 可以包含多条业务步骤，但不为输入、工具或文件机械拆分空章节。`结束条件` 必须写成可判断的业务事实，不能只写“任务完成后结束”。

## 5. 按需章节

只有真实业务需要时，才在两段式模板中增加以下章节：

| 章节 | 使用条件 | 只写什么 |
| --- | --- | --- |
| `阶段门禁` | 存在不能同轮跨越的确认点 | 进入条件、退出条件和必须等待用户的事实。 |
| `工具与文件` | 某个工具、路径或文件组织方式是业务要求 | 本 Skill 特有的选择、命名、内容或顺序要求。 |
| `脚本调用` | 当前 Skill 带有确定性脚本 | 何时调用、业务参数含义和业务结果要求。 |
| `产物要求` | 交付物有固定格式或组成 | 真实产物应包含的内容和验收标准。 |
| `失败处理` | 某类业务失败需要特殊处置 | 可恢复条件、需要用户补充的事实或终止条件。 |

按需章节不复制通用工作区规则、工具 schema、脚本命令行、平台输出字段或协议错误处理。

## 6. 脚本资源

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
- `SKILL.md` 的按需“脚本调用”章节只说明调用时机、参数业务语义和结果要求。
- 脚本运行、结果回灌和失败日志合同统一见 `docs/skills/sandbox-tool-interface.md`，不复制进 Skill 正文。

## 7. 主持人 Skill

主持人 Skill 不使用本模板。主持人只负责具体场景的阶段判断和跨专家调度，完整规范见 `docs/skills/host-skill.md`。

## 8. 验收

上线前至少验证：

1. Frontmatter 可解析，`description` 只表达触发条件和边界。
2. `allowed-tools` 与本 Skill 真实需要的工具一致。
3. 正文包含非空的 `执行规则` 和 `结束条件`。
4. 结束条件分别说明等待用户并保留 Skill、完成业务并释放 Skill 的可判断事实。
5. Skill 不重复专家身份、长期职责、主持人调度或平台固定协议。
6. 按需章节均对应真实业务要求，不保留空章节或模板占位符。
7. 带脚本时，manifest 可解析，正文没有自造脚本路径、CLI 参数或工具名称。
8. 产物、工具和阶段门禁可以通过真实执行场景验证。
