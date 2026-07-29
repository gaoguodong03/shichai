# Skill 文件操作方式

Skill 执行过程中有两层独立的文件操作方式。它们适用于不同的执行粒度，不是替代关系。

| | Agent 工作区工具调用 | 脚本级文件操作 |
|---|---|---|
| 执行者 | LLM 模型（函数调用） | 脚本进程（Python / Bash） |
| 调用方式 | 模型发起 `write_workspace_file` 等工具调用 | 脚本使用语言原生文件 API |
| 适用场景 | 模型一步一决策的交互式编辑 | 批量处理、确定性计算、大文件 |
| 文件范围 | 当前会话工作区 | 当前会话工作区 |
| 结果反馈 | 工具返回值回灌模型上下文 | 脚本 stdout 输出标准 JSON 协议 |

---

## 方式一：Agent 工作区工具调用

LLM 推理过程中可以直接调用以下内置工作区工具（不需要用户特说说明）：

| 工具 | 作用 |
|---|---|
| `read_workspace_file` | 读取工作区文本文件 |
| `write_workspace_file` | 新建/覆写文件 |
| `edit_workspace_file` | 按文本片段替换编辑 |
| `rename_workspace_file` | 重命名或移动 |
| `mkdir_workspace` | 新建目录 |
| `list_workspace_directory` | 列出工作区文件 |

这些是 first-class 函数调用，由平台根据当前 expert 的 `file_capabilities` 注入。每个工具有结构化参数、路径校验和错误返回。SKILL.md 正文通过执行规则说明模型何时调用哪个工具。

---

## 方式二：脚本级文件操作

脚本型 Skill 把确定性逻辑封装到 `scripts/` 下的可执行文件中。脚本以独立进程运行（OpenSandbox 沙箱），通过语言自带 API 读写工作区文件。

```
#!/usr/bin/env python3
"""脚本级文件 CRUD 完整示例（含协议输出）。"""
import json, os, shutil, sys
from pathlib import Path

ws = Path(os.environ["SKILL_WORKSPACE_ROOT"])

try:
    # READ — 先检查文件存在
    src = ws / "input.json"
    if not src.exists():
        raise FileNotFoundError(f"文件不存在: {src}")

    data = json.loads(src.read_text(encoding="utf-8"))

    # CREATE — 写结果
    (ws / "output.json").write_text(
        json.dumps({"result": data}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # DELETE / MOVE / MKDIR
    (ws / "temp").unlink(missing_ok=True)
    shutil.move(str(ws / "old.txt"), str(ws / "new.txt"))
    (ws / "subdir").mkdir(parents=True, exist_ok=True)

    # stdout 协议
    print(json.dumps({
        "execution_status": "succeeded",
        "message": {"content": "文件操作完成。", "attachments": [], "artifacts": [
            {"type": "json", "name": "处理结果", "path": "output.json"}
        ]},
        "next_action": {"agent_turn": "respond", "skill_session": "release"}
    }))

except Exception as exc:
    print(json.dumps({
        "execution_status": "failed",
        "message": {"content": f"操作失败: {exc}", "attachments": [], "artifacts": []},
        "next_action": {"agent_turn": "respond", "skill_session": "release"}
    }))
    sys.exit(0)  # 注意：业务失败也要 exit(0)，让平台看 stdout 里的 execution_status
```

---

## 脚本型 Skill 的开发者使用方式

### 目录结构

```
<skill-name>/
  SKILL.md
  scripts/
    manifest.json
    process.py
```

### manifest.json

`scripts/manifest.json` 是脚本的入口声明，定义条目文件、描述、参数和超时。

```json
{
  "entry": "process.py",
  "description": "处理输入文件并生成业务结果。",
  "timeout_sec": 120,
  "args": [
    {
      "name": "input_path",
      "description": "工作区内输入文件相对路径。",
      "required": true,
      "type": "string"
    },
    {
      "name": "output_path",
      "description": "工作区内输出文件相对路径。",
      "required": true,
      "type": "string"
    },
    {
      "name": "format",
      "description": "输出格式，默认 markdown。",
      "required": false,
      "type": "string",
      "default": "markdown"
    }
  ]
}
```

#### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `entry` | 是 | 相对 `scripts/` 的脚本路径。支持 `.py`、`.sh`、`.bash` 等 |
| `description` | 是 | 工具描述，LLM 可见，决定模型何时选择此工具 |
| `timeout_sec` | 否 | 超时秒数，默认 60；设为 0 或负数表示不限 |
| `args` | 是 | 参数数组 |

#### 参数规则

- `name` 使用 **snake_case**，平台自动转换为 `--kebab-case` CLI 标识传递给脚本。
- `type` 支持 `string`、`integer`、`number`、`boolean`、`array`。
- `boolean` 类型参数为 `true` 时只传 `--flag`，为 `false` 时不传标识。
- `default` 可以省略；模型不传必填参数时会收到验证错误。
- 参数名不得重复。

#### 命名与工具名映射

目录名 `travel-expense-calculator` 对应的脚本工具名为 `run_skill_script_travel_expense_calculator`。
manifest 参数 `input_path` 对应的 CLI 标识为 `--input-path`。

### 环境变量

脚本运行时可以读取以下环境变量：

| 变量 | 说明 | 沙箱内示例值 |
|---|---|---|
| `SKILL_ID` | 当前 Skill 目录名 | `travel-expense` |
| `SKILL_WORKSPACE_ID` | 当前会话工作区 ID | `session-uuid` |
| `SKILL_WORKSPACE_ROOT` | 工作区根目录（即脚本工作目录） | `/workspace` |
| `SKILL_SCRIPT_ROOT` | 脚本所在目录 | `/skills/travel-expense/scripts` |
| `SKILL_HOME` | Skill 家目录 | `/skills/travel-expense` |
| `SKILL_WRITE_MODE` | 写入权限 | `workspace_all` |
| `SKILL_REQUIREMENTS_B64` | Base64 编码的用户级依赖 | 用于沙箱安装 |

`SKILL_WORKSPACE_ROOT` 就是脚本的当前工作目录。脚本在此目录内读写文件。

### 标准 stdout 协议

脚本的 stdout **必须**输出一个 JSON 对象，遵循 `expert_final_state.v2` 协议：

```json
{
  "execution_status": "succeeded",
  "message": {
    "content": "给用户看到的结论或摘要，支持 Markdown。",
    "attachments": [],
    "artifacts": [
      {
        "type": "markdown",
        "name": "分析报告",
        "path": "outputs/report.md"
      }
    ]
  },
  "next_action": {
    "agent_turn": "respond",
    "skill_session": "release"
  }
}
```

字段含义见 `docs/skills/skill-session-flow.md`。JSON 必须包含 `execution_status`、`message.content` 和 `next_action` 三个必要部分，缺一不可。不在协议中的字段如 `schema_version`、顶层 `content`、顶层 `artifacts` 会被拒绝。

stderr 可以输出运行日志，不影响执行结果判断，但脚本失败时会随错误信息一起返回。

### 退出码

- 退出码为 0：正常执行，按 stdout JSON 判断结果。
- 退出码非 0：视为脚本异常退出，即使 stdout 是合法 JSON 也按失败处理。

---

## 脚本开发示例

### Python 示例：完整 CRUD

```python
#!/usr/bin/env python3
"""演示脚本内使用语言原生 API 做文件 CRUD。"""
import json
import os
import shutil
from pathlib import Path

ws = Path(os.environ["SKILL_WORKSPACE_ROOT"])

# CREATE — 新建目录和文件
out_dir = ws / "outputs"
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "result.md").write_text("# 结果\n\n生成成功。", encoding="utf-8")

# READ — 读已有文件
src = ws / "uploads" / "data.txt"
if src.exists():
    data = src.read_text(encoding="utf-8")

# UPDATE — 局部修改
target = ws / "notes" / "draft.md"
if target.exists():
    content = target.read_text(encoding="utf-8")
    content = content.replace("旧内容", "新内容")
    target.write_text(content, encoding="utf-8")

# DELETE — 删除文件
temporary = ws / "tmp" / "temp.txt"
temporary.unlink(missing_ok=True)

# RENAME / MOVE — 重命名或移动
shutil.move(str(ws / "old.md"), str(ws / "new.md"))

# 输出标准协议
print(json.dumps({
    "execution_status": "succeeded",
    "message": {"content": "文件操作完成。", "attachments": [], "artifacts": []},
    "next_action": {"agent_turn": "respond", "skill_session": "release"}
}))
```

### Python 示例：manifest 参数映射

```python
#!/usr/bin/env python3
"""处理文件并生成结果。manifest 参数自动映射为 CLI 参数。"""
import argparse
import json
import os
import sys
from pathlib import Path

ws = Path(os.environ["SKILL_WORKSPACE_ROOT"])

parser = argparse.ArgumentParser()
parser.add_argument("--input-path", required=True)
parser.add_argument("--output-path", required=True)
parser.add_argument("--format", default="markdown")
args = parser.parse_args()

input_file = ws / args.input_path
if not input_file.exists():
    print(json.dumps({
        "execution_status": "failed",
        "message": {"content": f"输入文件不存在: {args.input_path}", "attachments": [], "artifacts": []},
        "next_action": {"agent_turn": "respond", "skill_session": "release"}
    }))
    sys.exit(0)

content = input_file.read_text(encoding="utf-8")
result = f"输入: {args.input_path}\n大小: {len(content)} 字符\n格式: {args.format}"

output_file = ws / args.output_path
output_file.parent.mkdir(parents=True, exist_ok=True)
output_file.write_text(result, encoding="utf-8")

print(json.dumps({
    "execution_status": "succeeded",
    "message": {"content": f"处理完成，结果已保存到 {args.output_path}。", "attachments": [], "artifacts": [
        {"type": "markdown", "name": "处理结果", "path": args.output_path}
    ]},
    "next_action": {"agent_turn": "respond", "skill_session": "release"}
}))
```

### Bash 示例

```bash
#!/usr/bin/env bash
set -euo pipefail

INPUT_PATH="${1:?missing input_path}"
OUTPUT_PATH="${2:?missing output_path}"

if [ ! -f "$INPUT_PATH" ]; then
  echo '{"execution_status":"failed","message":{"content":"输入文件不存在。","attachments":[],"artifacts":[]},"next_action":{"agent_turn":"respond","skill_session":"release"}}'
  exit 0
fi

LINE_COUNT=$(wc -l < "$INPUT_PATH")
mkdir -p "$(dirname "$OUTPUT_PATH")"
echo -e "统计结果\n\n行数: $LINE_COUNT" > "$OUTPUT_PATH"

echo '{"execution_status":"succeeded","message":{"content":"统计完成。","attachments":[],"artifacts":[{"type":"markdown","name":"统计结果","path":"'"$OUTPUT_PATH"'"}]},"next_action":{"agent_turn":"respond","skill_session":"release"}}'
```


---

## 调试方式

1. **本地运行**：确认文件操作和 stdout JSON 符合预期后再提交。
   ```bash
   python3 scripts/process.py --input-path test.txt --output-path out.md
   ```
2. **检查 stdout**：脚本输出必须是合法 JSON。管道验证：
   ```bash
   python3 scripts/process.py --input-path test.txt --output-path out.md | python3 -m json.tool
   ```
3. **查看沙箱日志**：stderr 中的 `skill_python_*` 前缀日志用于诊断依赖安装状态。
4. **确认 manifest**：`manifest.json` 的 `args` 定义与脚本 `argparse` 参数名一致（snake_case → `--kebab-case`）。

---

## 参考

- 工作区工具接口规范：`docs/skills/sandbox-tool-interface.md`
- 会话流程控制协议：`docs/skills/skill-session-flow.md`
- Skill 项目规范：`docs/skills/skill-standard.md`
