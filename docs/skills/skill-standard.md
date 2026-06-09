# 书童四九 Skill 规范

本文档定义书童四九中 Skill 的编写、执行、结束点判断与上线验收规范。目标是让每个 Skill 都能被专家稳定选择、可通过脚本复现执行，并在合适时机交回主持人“四九”重新调度。

## 1. 适用范围

本规范适用于：

- 用户目录下的 `backend/data/users/<user_id>/resources/skills/<skill_id>/SKILL.md`；
- Skill 附带的 `scripts/`、`references/`、`assets/`；
- 专家在群聊中绑定和执行的 Skill；
- 需要 OpenSandbox 执行脚本的 Skill。

不适用于四九主持人本身的业务调度策略，但主持人 Skill 也应遵守基础文件结构与输出契约。

## 2. 目录结构

一个标准 Skill 目录应满足：

```text
<skill_id>/
  SKILL.md
  scripts/              # 可选，脚本型 Skill 必须有
    manifest.json       # 可选但推荐
    <script>.py|sh|bash|ps1|cmd|bat
  references/           # 可选，长参考资料
  assets/               # 可选，模板、素材、静态资源
```

约束：

- `SKILL.md` 是唯一必需入口文件；目录存在但没有 `SKILL.md` 时，不应视为可用 Skill。
- 脚本只能放在当前 Skill 的 `scripts/` 下，并通过 `run_skill_script_<skill_id>` 执行。
- 工作区文件不应写入 Skill 目录；Skill 目录是能力定义区，工作产物应写入会话工作区。
- `references/` 与 `assets/` 只放稳定资料，不放本轮会话临时文件。

## 3. `SKILL.md` Frontmatter

`SKILL.md` 顶部必须使用 YAML frontmatter：

```yaml
---
name: 示例技能
description: 用于一句话说明触发场景，帮助专家选择是否使用该 Skill。
allowed-tools:
  mcp: []
  python: ''
---
```

字段规范：

| 字段 | 是否必填 | 规范 |
| --- | --- | --- |
| `name` | 必填 | 用户可读名称，建议 2~12 个中文字符或短英文名。 |
| `description` | 必填 | 写清楚“什么时候用”，不要只写能力口号。 |
| `allowed-tools` | 必填 | 使用统一结构；没有额外工具时也保留空值。 |

`description` 应包含：

- 触发对象：处理哪类任务；
- 输入线索：用户说出什么需求时应使用；
- 结果形态：最终产出是什么。

示例：

```yaml
description: 当用户需要抓取 WebNovel 小说章节并保存为工作区文件时使用，产出章节文本与保存路径摘要。
```

## 4. 正文编写规范

正文建议包含以下章节：

1. **你是谁**：定义专家在此 Skill 下的角色。
2. **什么时候使用**：列出明确触发条件和不应使用的场景。
3. **输入要求**：说明必须向用户确认的参数。
4. **执行步骤**：按顺序写清楚分析、调用脚本、整理结果。
5. **输出格式**：规定给用户看的最终答复结构。
6. **流程控制**：脚本型 Skill 明确 stdout JSON；非脚本型 Skill 明确隐藏状态块。
7. **常见错误**：列出模型容易犯的错。

正文应避免：

- 只写抽象原则，不写可执行步骤；
- 要求用户自行执行后端内部命令；
- 混用非 `cli_args_json` 的参数说明；
- 让专家代替四九选择下一位专家；
- 把脚本路径写成工作区文件路径。

## 5. 脚本型 Skill 规范

脚本路径、工作区路径、Skill 资源路径与数据库文件设计的详细说明见 `docs/skills/skill-script-paths.md`。

### 5.1 调用契约

脚本型 Skill 统一通过 `run_skill_script_<skill_id>` 调用，输入使用 `cli_args_json`，不再支持 `input_json` 或从 stdin 读取 JSON。

推荐写法：

```text
调用 run_skill_script_<skill_id>：
- script_path: crawl_and_store.py
- cli_args_json: ["--url", "<url>", "--output", "<workspace-relative-path>"]
```

约束：

- `script_path` 写脚本文件名即可，如 `crawl_and_store.py`；不要写绝对路径。
- 文档中若写 `scripts/foo.py`，系统会尽量纠正，但规范写法仍是 `foo.py`。
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

### 5.2 `scripts/manifest.json`

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

### 5.3 给 Skill 作者的脚本函数调用建议

面向用户编写 Skill 时，建议把“模型如何调脚本”和“脚本如何返回结果”都写成固定合同，不让模型猜。

#### 5.3.1 在 `SKILL.md` 中写清楚工具调用

在执行步骤里写明实际工具名、脚本名和 argv 数组：

```text
调用 run_skill_script_<skill_id>：
- script_path: transcribe_audio.py
- cli_args_json: ["--file", "<工作区相对路径>", "--language", "zh"]
```

约定：

- `script_path` 只写 `scripts/` 下的文件名，不写 `scripts/foo.py`、工作区路径或宿主机绝对路径。
- `cli_args_json` 必须是 JSON 数组字符串，对应 Python `argparse` 的命令行参数。
- 所有用户文件路径都用工作区相对路径，例如 `uploads/audio.wav`、`outputs/result.json`。
- 多参数脚本要在 `scripts/manifest.json` 里写 `input_schema.required`，让系统能提前发现缺参。

#### 5.3.2 沙箱依赖怎么声明和导入

Python 包不要在脚本里临时 `pip install`。按下面顺序处理：

1. 在 `SKILL.md` frontmatter 的 `allowed-tools.python` 中声明依赖，每行一个包：

```yaml
---
name: 示例技能
description: 当用户需要处理表格并生成统计结果时使用。
allowed-tools:
  mcp: []
  python: |
    pandas>=2.2
    openpyxl>=3.1
---
```

2. 用户导入 Skill 时，系统会把这些依赖合并到当前账号的 `config/sandbox/requirements.txt` 并预热沙箱。
3. 已存在的 Skill，可在资源中心的 Skill 详情页查看 Python 依赖；红色依赖表示尚未加入“设置 - 沙箱 - requirements.txt”，可一键添加并等待安装完成。
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

#### 5.3.3 stdout 字段怎么写

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

#### 5.3.4 Python 脚本最小模板

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

## 6. Skill 会话锁

专家在群聊中使用某个 Skill 后，系统会记录 Skill 会话锁：

- `skill_session_owner_id`：当前继续处理该 Skill 的专家；
- `skill_session_skill_id`：当前继续使用的 Skill。

会话锁存在且仍有效时，下一条用户消息默认直接交给该专家继续处理，四九不会参与本轮调度。只有满足以下条件之一时才回到四九：

- 脚本或 MCP 工具 stdout JSON 输出 `next_action.skill_session=release`；
- 非脚本 Skill 的专家正文末尾追加隐藏状态块，且其中 `next_action.skill_session=release`；
- 用户明确说“结束 skill / 退出技能 / 交给主持人 / 请下一位专家”等；
- 用户 `@` 或点名其他专家；
- 平台入口路由收到明确的 `host_takeover_requested` 或 `ignore_auto_agent_id` 字段；
- 当前专家或 Skill 已不在会话有效范围内。

## 7. 结束点判断规范

Skill 的“结束点”不是单轮回复结束，而是当前 Skill 在群聊中的整体流程是否完成。

### 7.1 标准流程控制

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

### 7.2 `release` 的判定

满足任一条件时，脚本 stdout 或专家隐藏状态块输出 `next_action.skill_session=release`：

- 已交付用户请求的最终结果，且不需要同一 Skill 继续追问或处理；
- 脚本成功执行，已总结结果、文件路径、下一步建议；
- 当前 Skill 判断后续应由四九重新选择专家；
- 任务无法继续且已给出明确失败原因和替代建议。

### 7.3 `keep` 的判定

满足任一条件时，脚本 stdout 或专家隐藏状态块输出 `next_action.skill_session=keep`：

- 还缺少必填参数，需要用户补充；
- 任务设计为多轮流程，当前只完成其中一步；
- 已产出草稿，但需要用户确认方向后继续修改；
- 脚本执行失败但可由用户补充信息或换参数后继续；
- 正在等待用户选择、确认、上传文件或提供链接。

### 7.4 不应释放的情况

以下情况输出 `next_action.skill_session=keep`：

- 只是向用户提出一个必要问题；
- 只完成了计划、提纲、参数确认中的一环；
- 工具刚返回原始结果，但尚未整理给用户；
- 用户明显希望“继续生成 / 继续修改 / 继续抓取”；
- 需要保持同一专家上下文才能完成后续步骤。

## 8. 主持人与专家边界

四九负责调度，专家负责执行。Skill 编写时必须保持边界：

- 专家可以说明“建议交回四九重新安排”，但不要自行指定下一位专家。
- 专家不输出主持人 JSON，不写 `next_speaker`、`suggested_add_agent_ids` 等主持人字段。
- 主持人 Skill 不代写专家正文，只选择专家、说明原因、给出 `next_prompt`。
- Skill 会话未结束时，专家应继续沿同一 Skill 推进，不把用户消息重新交给四九。

## 9. 上线验收清单

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

## 10. 最小模板

```markdown
---
name: <技能名称>
description: 当用户需要<任务>时使用，输入为<输入>，产出<结果>。
allowed-tools:
  mcp: []
  python: ''
---

## 你是谁

你是负责<任务>的专家。

## 什么时候使用

- 用户明确要求<触发条件>时使用。
- 用户只是闲聊、调度或需要其他专家时不要使用。

## 输入要求

- 必填：<参数>。
- 缺少必填参数时，先向用户追问；脚本 stdout 或隐藏状态块返回 `next_action.skill_session=keep`。

## 执行步骤

1. 检查输入是否完整。
2. 必要时调用脚本或工具。
3. 整理结果并给出用户可执行的下一步。

## 输出格式

- 结果摘要：
- 产物路径：
- 下一步建议：

## 结束点判断

- 已交付最终结果：脚本 stdout 或隐藏状态块输出 `next_action.skill_session=release`。
- 仍需用户补充或确认：脚本 stdout 或隐藏状态块输出 `next_action.skill_session=keep`。

脚本型 Skill 使用 stdout JSON 的 `next_action` 控制流程；非脚本型 Skill 使用隐藏状态块控制流程。隐藏状态块不是用户可见正文，实际输出时不要放入 Markdown 代码块。

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
