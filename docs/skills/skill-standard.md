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
  python: []
---
```

字段规范：

| 字段 | 是否必填 | 规范 |
| --- | --- | --- |
| `name` | 必填 | 用户可读名称，建议 2~12 个中文字符或短英文名。 |
| `description` | 必填 | 写清楚“什么时候用”，不要只写能力口号。 |
| `allowed-tools` | 必填 | 使用统一结构；没有额外工具时也保留空值。 |

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
  "execution_status": "blocked",
  "result_code": "input.confirmation_required",
  "message": "等待用户补充或确认",
  "artifacts": {
    "required_fields": ["用户回复"]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
[[/SKILL_SESSION_STATE]]
```

这里的 `release` 表示本专家已把确认问题交给用户，下一轮由主持人或入口路由重新判断。如果确认后必须回到同一专家继续处理，才使用 `skill_session=keep`。

流程型 Skill 必须避免：

- 只写“需要用户确认”，但不写隐藏状态块和等待后的会话归属。
- 只说“保存文件”，但没有明确应使用的工作区文件工具和需要填写的字段。
- 默认把过程草稿、头脑风暴、读者测试、临时摘要写成文件。
- 覆盖用户源文件；修改已有文件时应新建符合 `文件名-当前文件时间戳.扩展名` 的新文件。
- 在专家 Skill 中自行指定下一位专家或输出主持人 JSON。

### 3.2 工作区文件写入规范

专家可用的工作区文件工具是任务过程能力，不只在用户显式说“保存”时使用。只要任务需要读取上下文、检查已有文件、新建目录、沉淀阶段产物、保存可复用资料或交付最终文件，Skill 正文都应推动专家主动调用相应工具。

在 Skill 正文中应写清楚保存动作使用 `write_workspace_file`，并说明 `path` 和 `content` 的含义，避免模型只用自然语言说“已保存”。

约束：

- `path` 必须是当前会话工作区相对路径，不写 `backend/data/`、`workspaces/<会话ID>/` 或宿主机绝对路径。
- 除非用户明确指定已有路径或固定文件名，所有新建工作区文件名统一使用 `文件名-当前文件时间戳.扩展名`，例如 `materials/技术管理手感-2026070422145700.md`。
- `content` 必须是要保存的完整正文；不能只写摘要、占位符或“见上文”。
- 只有 `write_workspace_file` 或 `edit_workspace_file` 返回成功后，专家才能在最终答复中说文件已保存。
- 修改已有文件时，不覆盖源文件；读取源文件后应新建符合 `文件名-当前文件时间戳.扩展名` 的新文件，并在新文件开头记录 `source_path`。
- 网页采集、资料检索、素材整理类任务如果得到多条独立素材，应每条素材单独调用一次 `write_workspace_file`，不要把所有素材合并进一个文件。
- 最终答复只汇总文件清单、来源和简短说明，不把全部素材正文重复堆在聊天气泡里。

## 4. 脚本型 Skill 规范

脚本路径、工作区路径、Skill 资源路径与数据库文件设计的详细说明见 `docs/skills/skill-script-paths.md`。

### 4.1 调用契约

脚本型 Skill 统一通过 `run_skill_script_<directory_name>` 调用，输入固定使用 `cli_args_json`。

推荐写法：

```text
调用 run_skill_script_<directory_name>：
- script_path: crawl_and_store.py
- cli_args_json: ["--url", "<url>", "--output", "<workspace-relative-path>"]
```

约束：

- `script_path` 写脚本文件名即可，如 `crawl_and_store.py`。
- 文档示例统一使用脚本文件名，便于模型稳定复用。
- 脚本参数必须是 argv 数组 JSON，例如 `["--name", "value"]`。
- 脚本必须把结构化结果写到 stdout，错误写到 stderr，并使用退出码表达成功或失败。
- stdout JSON 必须使用标准字段：`execution_status`、`result_code`、`message`，并按需输出 `artifacts` 与 `next_action`。

成功且声明 Skill 会话结束的 stdout 示例：

```json
{
  "execution_status": "succeeded",
  "result_code": "completed",
  "message": "已生成结果文件。",
  "artifacts": {
    "output_path": "outputs/result.txt"
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

### 4.2 `scripts/manifest.json`

脚本型 Skill 推荐提供 `scripts/manifest.json`，用于说明脚本、参数和必填项。最小示例：

```json
{
  "crawl_and_store.py": {
    "description": "抓取章节并保存为工作区文件",
    "input_schema": {
      "type": "object",
      "required": ["url", "output"]
    }
  }
}
```

### 4.3 给 Skill 作者的脚本函数调用建议

面向用户编写 Skill 时，建议把“模型如何调脚本”和“脚本如何返回结果”都写成固定合同，不让模型猜。

#### 4.3.1 在 `SKILL.md` 中写清楚工具调用

在执行步骤里写明实际工具名、脚本名和 argv 数组：

```text
调用 run_skill_script_<directory_name>：
- script_path: transcribe_audio.py
- cli_args_json: ["--file", "<工作区相对路径>", "--language", "zh"]
```

约定：

- `script_path` 只写 `scripts/` 下的文件名，不写 `scripts/foo.py`、工作区路径或宿主机绝对路径。
- `cli_args_json` 必须是 JSON 数组字符串，对应 Python `argparse` 的命令行参数。
- 所有用户文件路径都用工作区相对路径，例如 `uploads/audio.wav`、`outputs/result.json`。
- 多参数脚本要在 `scripts/manifest.json` 里写 `input_schema.required`，让系统能提前发现缺参。

#### 4.3.2 沙箱依赖怎么声明和导入

Python 包不要在脚本里临时 `pip install`。按下面顺序处理：

1. 在 `SKILL.md` frontmatter 的 `allowed-tools.python` 中声明依赖，使用数组，每个元素一个包：

```yaml
---
name: 示例技能
description: 当用户需要处理表格并生成统计结果时使用。
allowed-tools:
  mcp: []
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
        "execution_status": "failed",
        "result_code": "dependency.missing",
        "message": "缺少 Python 依赖 pandas，请先加入沙箱 requirements.txt。",
        "artifacts": {
            "missing_dependencies": ["pandas>=2.2"]
        },
        "next_action": {
            "agent_turn": "respond",
            "skill_session": "release"
        }
    }, ensure_ascii=False))
    raise SystemExit(2)
```

系统命令、浏览器、Playwright 这类不是普通 Python 包的能力，不要写进后端 `requirements.txt`；应选择合适沙箱版本或由管理员维护沙箱镜像。

#### 4.3.3 stdout 字段怎么写

脚本 stdout 必须只输出一个 JSON 对象。新脚本使用以下标准字段：

| 字段 | 建议 | 说明 |
| --- | --- | --- |
| `execution_status` | 必填 | 枚举：`succeeded`、`blocked`、`failed`。 |
| `result_code` | 必填 | 稳定机器码，如 `completed`、`input.missing`、`dependency.missing`。 |
| `message` | 必填 | 给专家和用户看的短说明。 |
| `artifacts` | 按需 | 结构化结果。文件路径、计数、明细数组都放在这里。 |
| `next_action.agent_turn` | 按需 | 枚举：`continue`、`respond`。控制当前专家回合是否继续行动。 |
| `next_action.skill_session` | 按需 | 枚举：`keep`、`release`。控制下一条用户消息是否回到同一专家和 Skill。 |

如果你说的“短接数”是音频/视频切片或分段数，字段建议命名为 `segment_count` 或 `chunk_count`，并同时给出 `segments` 明细：

```json
{
  "execution_status": "succeeded",
  "result_code": "transcribed",
  "message": "转写完成。",
  "artifacts": {
    "text": "完整转写文本……",
    "chunk_seconds": 120,
    "segment_count": 3,
    "segments": [
      {"index": 1, "total": 3, "text": "第一段……"},
      {"index": 2, "total": 3, "text": "第二段……"},
      {"index": 3, "total": 3, "text": "第三段……"}
    ]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

计数字段要遵守：

- 用整数，不要写成“3段”“共三段”。
- 名称稳定，避免同一个脚本有时叫 `count`，有时叫 `num`。
- 如果有明细数组，`segment_count` 应等于 `len(segments)`。
- 失败时也可以给 `processed_count`、`failed_count`，方便模型说明完成了多少、哪里失败。

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
            "execution_status": "blocked",
            "result_code": "file.missing",
            "message": f"找不到输入文件：{args.input}",
            "artifacts": {
                "required_fields": ["input"]
            },
            "next_action": {
                "agent_turn": "respond",
                "skill_session": "keep"
            }
        }, code=2)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {"source": args.input}
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    emit({
        "execution_status": "succeeded",
        "result_code": "completed",
        "message": "处理完成。",
        "artifacts": {
            "output_path": str(output_path),
            "result": result
        },
        "next_action": {
            "agent_turn": "respond",
            "skill_session": "release"
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
            "execution_status": "failed",
            "result_code": "runtime.failed",
            "message": str(exc),
            "next_action": {
                "agent_turn": "respond",
                "skill_session": "release"
            }
        }, code=1)
```

## 5. Skill 会话锁

专家在群聊中使用某个 Skill 后，系统会记录 Skill 会话锁：

- `skill_session_owner_name`：当前继续处理该 Skill 的专家名称；
- `skill_session_skill`：当前继续使用的 Skill 目录名。

会话锁存在且仍有效时，下一条用户消息默认直接交给该专家继续处理，四九不会参与本轮调度。只有满足以下条件之一时才回到四九：

- 脚本或 MCP 工具 stdout JSON 输出 `next_action.skill_session=release`；
- 非脚本 Skill 的专家正文末尾追加隐藏状态块，且其中 `next_action.skill_session=release`；
- 用户明确说“结束 skill / 退出技能 / 交给主持人 / 请下一位专家”等；
- 用户 `@` 或点名其他专家；
- 平台入口路由收到明确的 `host_takeover_requested` 或 `ignore_auto_agent_name` 字段；
- 当前专家或 Skill 已不在会话有效范围内。

## 6. 结束点判断规范

Skill 的“结束点”不是单轮回复结束，而是当前 Skill 在群聊中的整体流程是否完成。

### 6.1 标准流程控制

脚本型 Skill 和返回 JSON 的 MCP 工具通过 stdout JSON 的 `next_action` 控制流程。非脚本 Skill 通过专家正文末尾的隐藏状态块表达同一组字段。

规则：

- `next_action.agent_turn=continue`：当前专家回合继续行动，例如继续编辑文件或调用下一个工具。
- `next_action.agent_turn=respond`：当前专家基于脚本结果生成最终答复。
- `next_action.skill_session=keep`：下一条用户消息继续回到同一专家和同一 Skill。
- `next_action.skill_session=release`：释放 Skill 会话锁，下一轮交回主持人调度。

完整字段与允许值见 `docs/skills/skill-session-flow.md`。

普通非脚本专家没有结构化工具结果或隐藏状态块时，单轮发言结束后默认释放 Skill 会话。场景协作中的阶段成员建议显式写出隐藏状态块，让平台可以记录本轮 Skill 已完成、等待用户补充或需要继续锁定。

隐藏状态块示例：

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

实际专家输出时，状态块必须直接追加到正文末尾，不要放入 Markdown 代码块。平台会读取并移除该状态块，用户只看到专家正文。

### 6.2 `release` 的判定

满足任一条件时，脚本 stdout 或专家隐藏状态块输出 `next_action.skill_session=release`：

- 已交付用户请求的最终结果，且不需要同一 Skill 继续追问或处理；
- 脚本成功执行，已总结结果和文件路径；
- 当前 Skill 判断后续应由四九重新选择专家；
- 已向用户提出确认问题，且下一轮应由主持人根据用户回复重新调度；
- 任务无法继续且已给出明确失败原因和替代建议。

### 6.3 `keep` 的判定

满足任一条件时，脚本 stdout 或专家隐藏状态块输出 `next_action.skill_session=keep`：

- 还缺少必填参数，需要用户补充；
- 任务设计为多轮流程，当前只完成其中一步；
- 已产出草稿，但需要用户确认方向后继续修改；
- 脚本执行失败但可由用户补充信息或换参数后继续；
- 正在等待用户选择、确认、上传文件或提供链接，且下一轮必须回到同一专家继续处理。

### 6.4 不应释放的情况

以下情况不要输出 `release`，应输出 `next_action.skill_session=keep`：

- 向用户提出的问题只有同一专家继续处理才有意义；
- 只完成了计划、提纲、参数确认中的一环，且下一轮必须回到同一专家；
- 工具刚返回原始结果，但尚未整理给用户；
- 用户明显希望“继续生成 / 继续修改 / 继续抓取”；
- 需要保持同一专家上下文才能完成后续步骤。

## 7. 主持人与专家边界

四九负责调度，专家负责执行。Skill 编写时必须保持边界：

- 专家可以说明“建议交回四九重新安排”，但不要自行指定下一位专家。
- 专家回复使用自然语言、工具结果总结、隐藏状态块或脚本 stdout JSON；主持人调度字段只出现在主持人 Skill 中。
- 主持人 Skill 不代写专家正文；流程型主持人 Skill 只输出 `current_phase`、`next_speaker`、`speaker_task`，由平台负责展示主持消息并把 `speaker_task` 交给下一位专家。
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
- 需要参数时通过 stdout JSON 或隐藏状态块输出 `next_action.skill_session=keep`，并继续锁定同一专家；
- 最终交付后通过 stdout JSON 或隐藏状态块输出 `next_action.skill_session=release`，并回到四九调度；
- 用户说“结束 skill / 交给主持人”时能退出锁定；
- 脚本型 Skill 的 `script_path`、`cli_args_json`、stdout/stderr 与退出码符合约定；
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
  "execution_status": "blocked",
  "result_code": "input.confirmation_required",
  "message": "等待用户补充或确认",
  "artifacts": {
    "required_fields": ["用户回复"]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
[[/SKILL_SESSION_STATE]]

### 完成状态块

当最终产物已经真实保存，且不需要继续等待用户时，追加：

[[SKILL_SESSION_STATE]]
{
  "execution_status": "succeeded",
  "result_code": "<稳定结果码>",
  "message": "<完成说明>",
  "artifacts": {
    "workspace_path": "<工作区相对路径>"
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
[[/SKILL_SESSION_STATE]]

## 阶段流程

1. <阶段一>：目标是<目标>；输入是<输入>；完成条件是<完成条件>。
2. <阶段二>：目标是<目标>；输入是<输入>；完成条件是<完成条件>。
3. <收束>：整理最终结果和产物路径。

## 工作区文件规则

- 过程产物默认只在聊天中确认；用户明确要求保存或流程进入最终交付阶段时，写入工作区文件。
- 保存文件必须使用 `write_workspace_file`，并提供 `path` 与完整 `content`。
- `content` 必须是完整交付内容。
- 只有 `write_workspace_file` 返回成功后，才能说明文件已保存并使用完成状态块。
- 修改已有文件时，读取源文件后新建带时间戳的新文件，并在新文件开头记录 `source_path`。
- 读取工作区素材前，先使用 `list_workspace_directory` 确认真实路径，再按真实返回路径使用 `read_workspace_file`。

## 输出格式

- 结果摘要：
- 产物路径：

## 结束点判断

- 已交付最终结果时，正文末尾追加完成状态块。
- 已向用户提出确认问题，且下一轮应由主持人重新判断时，等待用户状态块使用 `skill_session:"release"`。
- 下一轮必须回到同一专家继续处理时，等待用户状态块使用 `skill_session:"keep"`。
```

### 9.2 脚本型 Skill 最小模板

````markdown
---
name: <技能名称>
description: 当用户需要<确定性处理任务>时使用；输入为<输入>，产出<结果>。
allowed-tools:
  mcp: []
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
- script_path: <script-name>.py
- cli_args_json: ["--input", "<工作区相对路径>", "--output", "outputs/<结果文件>"]

## scripts/manifest.json

```json
{
  "<script-name>.py": {
    "description": "<脚本用途>",
    "input_schema": {
      "type": "object",
      "required": ["input", "output"]
    },
    "examples": [
      ["--input", "uploads/input.txt", "--output", "outputs/result.md"]
    ]
  }
}
```

## 脚本输出

脚本 stdout 输出一个 JSON 对象，stderr 只放诊断信息。

成功示例：

{
  "execution_status": "succeeded",
  "result_code": "completed",
  "message": "处理完成。",
  "artifacts": {
    "output_path": "outputs/<结果文件>"
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}

缺少输入示例：

{
  "execution_status": "blocked",
  "result_code": "input.missing",
  "message": "缺少输入文件路径。",
  "artifacts": {
    "required_fields": ["input"]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "keep"
  }
}

失败示例：

{
  "execution_status": "failed",
  "result_code": "runtime.failed",
  "message": "<失败原因>",
  "artifacts": {
    "stderr_tail": "<关键错误信息>"
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}

## 关键规则

- 脚本必须是非交互式，输入固定来自 `cli_args_json`。
- `script_path` 只写脚本文件名，例如 `analyze_table.py`。
- stdout 只输出一个 JSON 对象。
- 只有脚本 stdout 中的 `artifacts` 或实际文件检查确认产物存在后，才能向用户说明已生成文件。
- Python 依赖统一写在 frontmatter 的 `allowed-tools.python` 数组中。

## 输出格式

- 处理结果：
- 产物路径：
- 失败原因或待补信息：

## 结束点判断

- 脚本返回 `execution_status=succeeded` 时，总结 `artifacts` 并交付结果。
- 脚本返回 `execution_status=blocked` 时，说明缺少什么。
- 脚本返回 `execution_status=failed` 时，说明失败原因和可修正方式。
````
