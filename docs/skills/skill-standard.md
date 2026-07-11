# 书童四九 Skill 规范

本文档定义书童四九中 Skill 的编写、执行、结束点判断与上线验收规范。目标是让每个 Skill 都能被专家稳定选择、可通过脚本复现执行，并在合适时机交回主持人“四九”重新调度。

## 1. 目录结构

一个标准 Skill 目录应满足：

```text
<directory_name>/
  SKILL.md
  scripts/              # 可选，脚本型 Skill 必须有
    manifest.json       # 可选但推荐
    <script>.py|sh|bash|ps1|cmd|bat
  references/           # 可选，长参考资料
  assets/               # 可选，模板、素材、静态资源
```

约束：

- `SKILL.md` 是唯一必需入口文件；目录存在但没有 `SKILL.md` 时，不应视为可用 Skill。
- 脚本只能放在当前 Skill 的 `scripts/` 下，并通过 `run_skill_script_<directory_name>` 执行。
- 工作区文件不应写入 Skill 目录；Skill 目录是能力定义区，工作产物应写入会话工作区。
- `references/` 与 `assets/` 只放稳定资料，不放本轮会话临时文件。

## 2. `SKILL.md` Frontmatter

`SKILL.md` 顶部必须使用 YAML frontmatter：

```yaml
---
name: 示例技能
description: 用于一句话说明触发场景，帮助专家选择是否使用该 Skill。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---
```

字段规范：

| 字段 | 是否必填 | 规范 |
| --- | --- | --- |
| `name` | 必填 | 用户可读名称，建议 2~12 个中文字符或短英文名。 |
| `description` | 必填 | 写清楚“什么时候用”，不要只写能力口号。 |
| `allowed-tools` | 必填 | 使用统一结构；没有额外工具时也保留空值。 |

`allowed-tools` 只描述外部工具依赖和脚本依赖：

| 字段 | 规范 |
| --- | --- |
| `mcp` | 本 Skill 允许调用的 MCP server 名称列表。 |
| `http_api` | 本 Skill 允许调用的保存型 HTTP API 工具名称列表。 |
| `python` | 本 Skill 脚本运行所需 Python 依赖列表，不是 LLM 工具授权。 |

工作区 CRUD 是平台默认能力，不写入 `allowed-tools`。当前 Skill 的脚本工具由 `scripts/manifest.json` 决定，也不写入 `allowed-tools`。通用 `call_api` 不再作为 LLM 可见工具，不允许在 Skill 中声明。

实现层必须按该结构删除旧兜底逻辑：不要兼容旧 `mcp_server_ids`、`api`、`workspace`、`skill_script` 声明；不要把未声明的通用 `call_api` 或无 manifest 脚本注入给模型。

`description` 只用于帮助平台和专家判断“什么时候用”，不应总结完整流程。它应包含：

- 触发对象：处理哪类任务；
- 输入线索：用户说出什么需求时应使用；
- 关键边界：哪些近似任务也应或不应使用。

示例：

```yaml
description: 当用户需要抓取 WebNovel 小说章节、整理公开网页资料或保存章节文本到工作区时使用；不用于正文创作或图片生成。
```

## 3. 正文编写规范

正文应先判断 Skill 类型，再选择结构。不要把所有 Skill 都写成脚本模板。

| 类型 | 适用场景 | 正文重点 |
| --- | --- | --- |
| 流程型 Skill | 长文合著、主持调度、资料确认、逐阶段创作、多人协作、需要用户多轮确认的任务。 | 触发边界、阶段门禁、状态块、工作区文件规则、何时等待用户、何时交回主持人。 |
| 脚本型 Skill | 表格分析、爬虫、转换、校验、批处理、确定性计算等需要稳定工具执行的任务。 | 非交互式脚本、参数 schema、stdout JSON、stderr 诊断、产物路径和校验。 |

通用正文建议包含以下章节：

1. **你是谁**：定义专家在此 Skill 下的角色。
2. **什么时候使用**：列出明确触发条件和不应使用的场景。
3. **输入要求**：说明必须向用户确认的参数。
4. **执行步骤**：按顺序写清楚分析、调用脚本、整理结果。
5. **输出格式**：规定给用户看的最终答复结构。
6. **流程控制**：脚本型 Skill 明确 stdout JSON；非脚本型 Skill 明确隐藏状态块。
7. **常见错误**：列出模型容易犯的错。

### 3.1 流程型 Skill 规范

流程型 Skill 适合文章合著、资料工作流、图片确认、读者测试、专家协作等长流程任务。这类 Skill 的核心不是“调用一个脚本”，而是让专家在真实对话中稳定遵守阶段、确认点和文件产物规则。

必须写清：

- **角色边界**：专家只负责哪类任务，遇到搜索、写作、生图、审阅等相邻职责时如何交回主持人。
- **阶段流程**：每个阶段的目标、输入、退出条件，以及是否允许落盘。
- **确认门禁**：什么时候必须等待用户确认，用户说“直接来”时是否仍需列出默认假设。
- **状态块**：需要用户补充、任务无关、最终完成时分别追加什么隐藏状态块。
- **文件规则**：哪些内容只在聊天中确认，哪些最终产物必须真实调用工作区写入工具保存。

流程型 Skill 的常见状态块：

```text
[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "blocked",
  "artifacts": [],
  "next_action": {
    "handoff": "user",
    "resume": "same_skill",
    "reason": "user_confirmation",
    "instruction": "当前阶段：<当前阶段>。请用户补充或确认：<具体问题>。用户回复后继续。"
  }
}
[[/SKILL_SESSION_STATE]]
```

这里的 `handoff=user` 表示当前 stream 等用户，`resume=same_skill` 表示下一条用户消息到来时保留同一专家同一 Skill 的续跑意图。若用户回复后应由主持人重新判断专家或阶段，使用 `resume=host`；若流程已完成，使用 `handoff=end`、`resume=none`。

流程型 Skill 必须避免：

- 只写“需要用户确认”，但不写隐藏状态块和等待后的会话归属。
- 只说“保存文件”，但没有明确应使用的工作区文件工具和需要填写的字段。
- 默认把过程草稿、头脑风暴、读者测试、临时摘要写成文件。
- 覆盖用户源文件；修改已有文件时应使用 `create_workspace_artifact` 新建版本化产物。
- 在专家 Skill 中自行指定下一位专家或输出主持人 JSON。

### 3.2 工作区文件写入规范

专家可用的工作区文件工具是任务过程能力，不只在用户显式说“保存”时使用。只要任务需要读取上下文、检查已有文件、新建目录、沉淀阶段产物、保存可复用资料或交付最终文件，Skill 正文都应推动专家主动调用相应工具。

在 Skill 正文中应写清楚保存动作使用 `write_workspace_file`，并说明 `path` 和 `content` 的含义，避免模型只用自然语言说“已保存”。

约束：

- `path` 必须是当前会话工作区相对路径，不写 `backend/data/`、`workspaces/<会话ID>/` 或宿主机绝对路径。
- 除非用户明确指定已有路径或固定文件名，所有新建工作区产物都使用 `create_workspace_artifact`，由平台生成安全文件名、时间戳和同名版本后缀。
- `content` 必须是要保存的完整正文；不能只写摘要、占位符或“见上文”。
- 只有 `write_workspace_file` 或 `edit_workspace_file` 返回成功后，专家才能在最终答复中说文件已保存。
- 修改已有文件时，不覆盖源文件；读取源文件后应使用 `create_workspace_artifact` 新建版本化产物，并在新文件开头记录 `source_path`。
- 网页采集、资料检索、素材整理类任务如果得到多条独立素材，应每条素材单独调用一次 `write_workspace_file`，不要把所有素材合并进一个文件。
- 最终答复只汇总文件清单、来源和简短说明，不把全部素材正文重复堆在聊天气泡里。

## 4. 脚本型 Skill 规范

脚本路径、工作区路径、Skill 资源路径与数据库文件设计的详细说明见 `docs/skills/skill-script-paths.md`。

### 4.1 调用契约

脚本型 Skill 统一通过 `run_skill_script_<directory_name>` 调用。模型看到的参数由 `scripts/manifest.json` 的 `args` 生成，模型按结构化字段传参，平台负责转换为 CLI 参数。

推荐写法：

```text
调用 run_skill_script_<directory_name>：
- url: <url>
- output_path: <workspace-relative-path>
```

约束：

- 脚本入口只写在 `scripts/manifest.json` 的 `entry` 字段中，Skill 正文不再要求模型传 `script_path`。
- Skill 正文应使用 manifest 中的参数名，例如 `url`、`output_path`，不要让模型直接传 `cli_args`。
- 平台将模型传入的结构化参数转换为 CLI 参数，例如 `output_path` 转为 `--output-path <value>`。
- 脚本必须把结构化结果写到 stdout，错误写到 stderr，并使用退出码表达成功或失败。
- stdout JSON 必须使用标准字段：`schema_version`、`execution_status`、`artifacts`、`next_action`。阶段名、等待点和下一步说明写入 `next_action.instruction`，不要新增阶段状态字段。

成功且声明 Skill 会话结束的 stdout 示例：

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "file",
      "name": "结果文件",
      "path": "outputs/result.txt"
    }
  ],
  "next_action": {
    "handoff": "end",
    "resume": "none",
    "reason": "final_delivery",
    "instruction": "已生成结果文件。"
  }
}
```

### 4.2 `scripts/manifest.json`

脚本型 Skill 必须提供 `scripts/manifest.json`，用于说明脚本入口、工具说明和 CLI 参数。manifest 只写 `entry`、`description`、`args`；不要手写 `input_schema`、`cli_args` 或 `invocation`。平台会根据 `args` 自动生成 LLM 可见的 `input_schema`。

没有 `scripts/manifest.json` 的脚本型 Skill 不是标准 Skill，平台不应注入脚本工具，也不应回退到默认 `cli_args`、`script_path` 或其他兼容入口。

```json
{
  "entry": "crawl_and_store.py",
  "description": "抓取章节并保存为工作区文件。",
  "args": [
    {
      "name": "url",
      "description": "要抓取的网页 URL。",
      "required": true
    },
    {
      "name": "output_path",
      "description": "保存结果的工作区相对路径。",
      "required": true
    }
  ]
}
```

字段规范：

| 字段 | 是否必填 | 规范 |
| --- | --- | --- |
| `entry` | 必填 | 脚本入口，相对 `scripts/` 目录；禁止绝对路径、`../`、shell 管道。 |
| `description` | 必填 | 给 LLM 看的脚本工具说明，说明脚本做什么、产出什么。 |
| `args` | 必填 | CLI 参数定义数组；无参数脚本也写空数组。 |
| `args[].name` | 必填 | 参数名，使用 snake_case；平台执行时转换为 `--kebab-case`。 |
| `args[].description` | 必填 | 给 LLM 的参数说明。 |
| `args[].required` | 可选 | 是否必填，默认 `false`。 |
| `args[].default` | 可选 | 默认值。 |
| `args[].repeatable` | 可选 | 是否可重复，默认 `false`；值为数组时平台展开为多次同名 CLI 参数。 |

模型调用工具时传入结构化参数：

```json
{
  "url": "https://example.com/chapter/1",
  "output_path": "materials/chapter-1.md"
}
```

平台执行时转换为：

```bash
python scripts/crawl_and_store.py --url https://example.com/chapter/1 --output-path materials/chapter-1.md
```

### 4.3 给 Skill 作者的脚本函数调用建议

面向用户编写 Skill 时，建议把“模型如何调脚本”和“脚本如何返回结果”都写成固定合同，不让模型猜。

#### 4.3.1 在 `SKILL.md` 中写清楚工具调用

在执行步骤里写明实际工具名和 manifest 参数名：

```text
调用 run_skill_script_<directory_name>：
- file_path: <工作区相对路径>
- language: zh
```

约定：

- 脚本入口只在 `scripts/manifest.json` 中声明，Skill 正文不让模型传 `script_path`。
- 参数名必须来自 manifest 的 `args[].name`。
- 所有用户文件路径都用工作区相对路径，例如 `uploads/audio.wav`、`outputs/result.json`。
- 必填参数要在 `scripts/manifest.json` 里写 `required: true`，让系统能提前发现缺参。

#### 4.3.2 沙箱依赖怎么声明和导入

Python 包不要在脚本里临时 `pip install`。按下面顺序处理：

1. 在 `SKILL.md` frontmatter 的 `allowed-tools.python` 中声明依赖，使用数组，每个元素一个包：

```yaml
---
name: 示例技能
description: 当用户需要处理表格并生成统计结果时使用。
allowed-tools:
  mcp: []
  http_api: []
  python:
    - pandas>=2.2
    - openpyxl>=3.1
---
```

2. 用户导入 Skill 时，系统会把这些依赖合并到当前账号的 `config/sandbox/requirements.txt` 并预热沙箱。
3. 已存在的 Skill，可在资源中心的 Skill 详情页查看 Python 依赖；红色依赖表示未被“设置 - 沙箱 - requirements.txt”的 pip 解析闭包覆盖，可一键添加并等待安装完成。
4. 脚本里按普通 Python 方式 `import pandas` 即可；如果依赖缺失，要返回结构化错误，而不是输出 traceback 给用户。

推荐缺依赖写法：

```
try:
    import pandas as pd
except ImportError:
    print(json.dumps({
        "schema_version": "expert_final_state.v2",
        "execution_status": "failed",
        "artifacts": [],
        "next_action": {
            "handoff": "host",
            "resume": "none",
            "reason": "failure",
            "instruction": "缺少 Python 依赖 pandas，请先加入沙箱 requirements.txt。"
        }
    }, ensure_ascii=False))
    raise SystemExit(2)
```

系统命令、浏览器、Playwright 这类不是普通 Python 包的能力，不要写进后端 `requirements.txt`；应选择合适沙箱版本或由管理员维护沙箱镜像。

#### 4.3.3 stdout 字段怎么写

脚本 stdout 必须只输出一个 JSON 对象。新脚本使用以下标准字段：

| 字段 | 建议 | 说明 |
| --- | --- | --- |
| `schema_version` | 必填 | 固定为 `expert_final_state.v2`。 |
| `execution_status` | 必填 | 枚举：`succeeded`、`blocked`、`failed`。 |
| `artifacts` | 必填 | 产物索引数组。无产物时写 `[]`。 |
| `next_action.handoff` | 必填 | 枚举：`user`、`host`、`end`。控制专家回合结束后交给谁。 |
| `next_action.resume` | 必填 | 枚举：`same_skill`、`same_agent`、`host`、`none`。控制下一条用户消息的续跑意图。 |
| `next_action.reason` | 必填 | 枚举见 `docs/skills/skill-session-flow.md`。说明交接原因。 |
| `next_action.instruction` | 必填 | 面向下一步消费者的自包含动作说明。 |

`artifacts` 中每一项固定为：

```json
{
  "type": "file | directory | image | table | json | markdown | other",
  "name": "用户可读名称",
  "path": "相对路径或资源路径"
}
```

不要在 `artifacts` 内嵌 `data`、长文本、表格行或 JSON 明细。即使产物类型是 `json`、`table` 或 `markdown`，真实内容也写入 workspace 文件，并通过 `path` 读取。

如果你说的“短接数”是音频/视频切片或分段数，脚本应把完整明细写入工作区文件，并在 `artifacts` 中返回该文件：

```json
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "json",
      "name": "转写明细",
      "path": "outputs/transcript.json"
    },
    {
      "type": "markdown",
      "name": "转写正文",
      "path": "outputs/transcript.md"
    }
  ],
  "next_action": {
    "handoff": "end",
    "resume": "none",
    "reason": "final_delivery",
    "instruction": "转写完成，共 3 段，完整结果已保存。"
  }
}
```

产物文件内的计数字段要遵守：

- 用整数，不要写成“3段”“共三段”。
- 名称稳定，避免同一个脚本有时叫 `count`，有时叫 `num`。
- 如果产物文件里有明细数组，`segment_count` 应等于 `len(segments)`。
- 失败时如需记录 `processed_count`、`failed_count`，也写入产物文件或执行 trace；stdout 只保留 `schema_version`、`execution_status`、`artifacts`、`next_action`。

#### 4.3.4 Python 脚本最小模板

```
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def emit(payload: dict, code: int = 0) -> None:
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(code)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="outputs/result.json")
    args = parser.parse_args()

    input_path = Path(args.input)
	    if not input_path.exists():
	        emit({
	            "schema_version": "expert_final_state.v2",
	            "execution_status": "blocked",
	            "artifacts": [],
	            "next_action": {
	                "handoff": "user",
	                "resume": "same_skill",
	                "reason": "missing_input",
	                "instruction": f"找不到输入文件：{args.input}，请提供正确的工作区相对路径。"
	            }
	        }, code=2)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {"source": args.input}
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

	    emit({
	        "schema_version": "expert_final_state.v2",
	        "execution_status": "succeeded",
	        "artifacts": [
            {
                "type": "json",
                "name": "处理结果",
                "path": str(output_path)
            }
	        ],
	        "next_action": {
	            "handoff": "host",
	            "resume": "none",
	            "reason": "stage_completed",
	            "instruction": "处理完成，请主持人判断下一步。"
	        }
	    })


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        print(str(exc), file=sys.stderr)
	        emit({
	            "schema_version": "expert_final_state.v2",
	            "execution_status": "failed",
	            "artifacts": [],
	            "next_action": {
	                "handoff": "host",
	                "resume": "none",
	                "reason": "failure",
	                "instruction": str(exc)
	            }
	        }, code=1)
```

## 5. Skill 续跑状态

专家在群聊中使用某个 Skill 且需要跨轮继续时，专家最终状态块或脚本 stdout 通过 `next_action.resume` 声明续跑意图。平台再把该意图沉淀到 `orchestration_state.json.continuation`：

- `owner_agent_name`：下一轮主持人应优先参考的专家名称；
- `skill_policy`：`keep` 表示保留同一 Skill 的续跑意图，`release` 表示不锁定当前 Skill；
- `skill`：`resume=same_skill` 时继续使用的 Skill 目录名；
- `next_action`：来自 `next_action.instruction` 的接续动作说明。

`continuation` 存在、仍有效且 `skill_policy=keep` 时，下一条用户消息会带着同一专家和同一 Skill 的续跑意图交给四九判断。四九通常应继续交给该专家，但必须先生成主持人调度，不能静默直达专家。满足以下条件之一时应释放或忽略该续跑意图：

- 脚本 stdout JSON 或专家隐藏状态块输出 `next_action.resume=host` 或 `next_action.resume=none`；
- 用户明确说“结束 skill / 退出技能 / 交给主持人 / 请下一位专家”等；
- 用户消息请求中的 `target_agent_name` 指向其他会话成员；
- 当前专家或 Skill 已不在会话有效范围内。

## 6. 结束点判断规范

Skill 的“结束点”不是单轮回复结束，而是当前 Skill 在群聊中的整体流程是否完成。

### 6.1 标准流程控制

脚本型 Skill 通过 stdout JSON 的 `next_action` 控制专家回合结束后的交接。MCP / HTTP / workspace 工具本身不要求返回 `next_action`；这些工具执行后必须进入专家最终回复阶段，绑定 Skill 或场景协作专家的最终回复必须追加隐藏状态块。非脚本 Skill 也通过专家正文末尾的隐藏状态块表达同一组字段。

规则：

- `next_action.handoff=user`：当前 stream 结束并等待用户。
- `next_action.handoff=host`：当前专家发言结束后交回主持人调度。
- `next_action.handoff=end`：流程完成，结束本轮。
- `next_action.resume=same_skill`：下一条用户消息保留同一专家同一 Skill 的续跑意图。
- `next_action.resume=same_agent`：下一条用户消息保留同一专家，但允许重新选择 Skill。
- `next_action.resume=host` 或 `none`：下一条用户消息不锁定当前专家 Skill。

工具循环内部是否继续调用工具由运行时决定，不再由最终隐藏状态块的字段表达。具体语义见 `docs/skills/skill-session-flow.md`。

完整字段与允许值见 `docs/skills/skill-session-flow.md`。

脚本 stdout 缺少 `next_action`、字段缺失、枚举非法或 JSON 结构不合法时，按协议失败处理：`execution_status=failed`、`next_action.handoff=host`、`next_action.resume=none`、`next_action.reason=protocol_error`，并向用户展示脚本输出不符合平台协议。

未绑定流程型 Skill、也没有工具后续判断的普通自然语言专家，单轮发言结束后可默认交回主持人。绑定 Skill、场景协作关键阶段成员，或 MCP / HTTP / workspace 工具执行后需要决定阶段门禁、等待用户、交回主持人或最终结束时，专家最终回复必须追加隐藏状态块。

隐藏状态块示例：

```text
[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [],
  "next_action": {
    "handoff": "host",
    "resume": "none",
    "reason": "stage_completed",
    "instruction": "处理完成，请主持人判断下一步。"
  }
}
[[/SKILL_SESSION_STATE]]
```

实际专家输出时，状态块必须直接追加到正文末尾，不要放入 Markdown 代码块。平台会读取并移除该状态块，用户只看到专家正文。

### 6.2 `handoff` 的判定

满足以下条件时选择对应 `next_action.handoff`：

| `handoff` | 选择条件 |
| --- | --- |
| `user` | 已提出确认问题、需要用户补充参数/文件/链接/选择、或跨阶段前必须等待用户确认。 |
| `host` | 当前专家阶段完成，后续应由四九判断下一位专家、下一阶段或是否结束。 |
| `end` | 最终结果已经交付，流程不需要继续。 |

### 6.3 `resume` 的判定

满足以下条件时选择对应 `next_action.resume`：

| `resume` | 选择条件 |
| --- | --- |
| `same_skill` | 用户回复后必须回到同一专家同一 Skill，例如继续合著、继续修改、继续补齐参数。 |
| `same_agent` | 用户回复后仍应由同一专家处理，但可重新选择 Skill。 |
| `host` | 用户回复后应交回主持人重新判断专家或阶段。 |
| `none` | 任务已完成、失败收束，或没有跨轮续跑需求。 |

### 6.4 跨阶段门禁

平台允许同一阶段内写入多个工作区产物。以下情况必须通过 `handoff=user` 或 `handoff=host` 暂停，不得在同一专家回合中静默跨阶段：

- 资料搜集完成后进入大纲或正文；
- 大纲生成后进入正文起草；
- 一个 section 草稿完成后进入下一个 section；
- 初稿完成后进入审阅或发布；
- 任何需要用户确认方向、范围、风格或文件内容的阶段切换。

## 7. 主持人与专家边界

四九负责调度，专家负责执行。Skill 编写时必须保持边界：

- 专家可以说明“建议交回四九重新安排”，但不要自行指定下一位专家。
- 专家回复使用自然语言、脚本 `content`、隐藏状态块或脚本 stdout JSON；主持人调度字段只出现在主持人 Skill 中。
- 主持人 Skill 不代写专家正文；流程型主持人 Skill 只输出 `current_phase`、`next_speaker`、`next_action`，由平台负责展示主持消息并把 `next_action` 交给下一位专家。
- Skill 会话未结束时，专家应继续沿同一 Skill 推进，不把用户消息重新交给四九。

主持人 Skill 的专门写法、运行链路和禁区见 [主持人 Skill 规范](host-skill.md)。

## 8. 上线验收清单

新增或修改 Skill 后，至少完成：

```bash
cd backend
python -m pytest tests/test_group_chat_skill_script_cli_flow.py -q
python scripts/validate_skill_cli_contract.py
```

如本次改动影响核心链路，还需回到项目根目录执行：

```bash
./scripts/test-layer1.sh
```

人工验收至少覆盖：

- Skill 能被专家按 `description` 正确选择；
- 需要参数或用户确认时通过 stdout JSON 或隐藏状态块输出 `next_action.handoff=user`，并按需要设置 `resume=same_skill`；
- 最终交付后通过 stdout JSON 或隐藏状态块输出 `next_action.handoff=end`、`resume=none`；
- 用户说“结束 skill / 交给主持人”时能退出锁定；
- 脚本型 Skill 的 `scripts/manifest.json`、manifest 参数、stdout/stderr 与退出码符合约定；
- 工作产物写入会话工作区，而不是写入 Skill 目录。

## 9. 最小模板

根据 Skill 的运行方式选择一套模板。模板必须直接写入书童四九的运行约束，避免把流程型和脚本型规则混在同一个模板里。

### 9.1 流程型 Skill 最小模板

```markdown
---
name: <技能名称>
description: 当用户需要<流程任务>时使用；边界是<相邻任务如何交回主持人或其他专家>。
allowed-tools:
  mcp: []
  http_api: []
  python: []
---

# <技能名称>

## 你是谁

你是负责<任务边界>的专家。你的核心任务是按阶段推进<流程目标>。

## 什么时候使用

- 用户明确要求<触发条件>时使用。
- 边界：<哪些相邻需求应交给主持人或其他专家处理>。

## 输入要求

- 必填：<用户需要提供的信息、文件、链接或确认项>。
- 信息不足时，只提出继续所需的最少问题。

## 平台状态块

### 等待用户状态块

当你提出问题、让用户选择、让用户确认、让用户反馈修改，或任何需要用户协助才能继续的位置，都必须在可见回复末尾追加：

[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "blocked",
  "artifacts": [],
  "next_action": {
    "handoff": "user",
    "resume": "same_skill",
    "reason": "user_confirmation",
    "instruction": "当前阶段：<当前阶段>。请用户补充或确认：<具体问题>。用户回复后继续。"
  }
}
[[/SKILL_SESSION_STATE]]

### 完成状态块

当最终产物已经真实保存，且不需要继续等待用户时，追加：

[[SKILL_SESSION_STATE]]
{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "file | directory | image | table | json | markdown | other",
      "name": "<用户可读名称>",
      "path": "<工作区相对路径>"
    }
  ],
  "next_action": {
    "handoff": "end",
    "resume": "none",
    "reason": "final_delivery",
    "instruction": "<完成说明>"
  }
}
[[/SKILL_SESSION_STATE]]

## 阶段流程

1. <阶段一>：目标是<目标>；输入是<输入>；完成条件是<完成条件>。
2. <阶段二>：目标是<目标>；输入是<输入>；完成条件是<完成条件>。
3. <收束>：整理最终结果和产物路径。

## 工作区文件规则

- 过程产物默认只在聊天中确认；用户明确要求保存或流程进入最终交付阶段时，写入工作区文件。
- 新建工作区产物优先使用 `create_workspace_artifact`，并提供 `title` 与完整 `content`；平台负责生成唯一文件名和版本后缀。
- 只有用户明确指定路径、固定文件名或要求覆盖时，才使用 `write_workspace_file`，并提供 `path` 与完整 `content`。
- `content` 必须是完整交付内容。
- 只有 `write_workspace_file` 返回成功后，才能说明文件已保存并使用完成状态块。
- 修改已有文件时，读取源文件后新建带时间戳的新文件，并在新文件开头记录 `source_path`。
- 读取工作区素材前，先使用 `list_workspace_directory` 确认真实路径，再按真实返回路径使用 `read_workspace_file`。

## 输出格式

- 结果摘要：
- 产物路径：

## 结束点判断

- 已交付最终结果时，正文末尾追加完成状态块，使用 `handoff:"end"`、`resume:"none"`。
- 已向用户提出确认问题时，等待用户状态块使用 `handoff:"user"`。
- 下一轮应优先延续同一专家同一 Skill 时，使用 `resume:"same_skill"`。
- 下一轮应由主持人重新判断时，使用 `resume:"host"`。
- 跨阶段前必须通过状态块暂停，不能在同一专家回合里静默进入下一阶段。
```

### 9.2 脚本型 Skill 最小模板

````markdown
---
name: <技能名称>
description: 当用户需要<确定性处理任务>时使用；输入为<输入>，产出<结果>。
allowed-tools:
  mcp: []
  http_api: []
  python:
    - <需要的 Python 依赖>
---

# <技能名称>

## 你是谁

你是负责<确定性处理任务>的专家。你的核心任务是检查输入、调用脚本、解释脚本结果。

## 什么时候使用

- 用户明确要求<触发条件>时使用。
- 边界：<哪些相邻需求应交给主持人或其他专家处理>。

## 输入要求

- 必填：<参数或工作区相对路径>。
- 文件路径必须是当前工作区相对路径。
- 参数不足时，先说明缺少哪些字段。

## 脚本调用

调用 run_skill_script_<directory_name>：
- input_path: <工作区相对路径>
- output_path: outputs/<结果文件>

## scripts/manifest.json

```json
{
  "entry": "<script-name>.py",
  "description": "<脚本用途>",
  "args": [
    {
      "name": "input_path",
      "description": "工作区内输入文件相对路径。",
      "required": true
    },
    {
      "name": "output_path",
      "description": "工作区内输出文件相对路径。",
      "required": true
    }
  ]
}
```

## 脚本输出

脚本 stdout 输出一个 JSON 对象，stderr 只放诊断信息。

成功示例：

{
  "schema_version": "expert_final_state.v2",
  "execution_status": "succeeded",
  "artifacts": [
    {
      "type": "markdown",
      "name": "结果文件",
      "path": "outputs/<结果文件>"
    }
  ],
  "next_action": {
    "handoff": "host",
    "resume": "none",
    "reason": "stage_completed",
    "instruction": "处理完成，请主持人判断下一步。"
  }
}

缺少输入示例：

{
  "schema_version": "expert_final_state.v2",
  "execution_status": "blocked",
  "artifacts": [],
  "next_action": {
    "handoff": "user",
    "resume": "same_skill",
    "reason": "missing_input",
    "instruction": "缺少输入文件路径，请补充后继续。"
  }
}

失败示例：

{
  "schema_version": "expert_final_state.v2",
  "execution_status": "failed",
  "artifacts": [],
  "next_action": {
    "handoff": "host",
    "resume": "none",
    "reason": "failure",
    "instruction": "<失败原因>"
  }
}

## 关键规则

- 脚本必须是非交互式，输入固定来自 manifest `args` 对应的 CLI 参数。
- `entry` 只写脚本文件名，例如 `analyze_table.py`。
- stdout 只输出一个 JSON 对象。
- 只有脚本 stdout 中的 `artifacts` 或实际文件检查确认产物存在后，才能向用户说明已生成文件。
- Python 依赖统一写在 frontmatter 的 `allowed-tools.python` 数组中。

## 输出格式

- 处理结果：
- 产物路径：
- 失败原因或待补信息：

## 结束点判断

- 脚本返回 `execution_status=succeeded` 时，直接交付 `content`，并列出 `artifacts` 里的产物名称和路径。
- 脚本返回 `execution_status=blocked` 时，直接交付 `content`，请用户补充继续所需信息。
- 脚本返回 `execution_status=failed` 时，直接交付 `content`，必要时提示查看执行 trace 或 stderr。
````
