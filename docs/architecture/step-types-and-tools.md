# 步骤类型与 Script/Service 工具

本文档说明 Skill 步骤的**三种执行分支**及当前实现方式（MCP、script、service 均作为工具注入技能执行 Agent）。

## 步骤的三种执行分支

Skill 的每一步（step）可能走以下三种执行分支之一，**应在 SKILL.md 中明确写出本步走哪一分支**，避免模型误选工具：

| 分支 | 含义 | 工具 / 实现 | 在 SKILL 中如何写明 |
|------|------|-------------|----------------------|
| **MCP** | 调用某个 MCP 工具 | 按技能过滤的 MCP 工具列表，如 `volces-icon_generate_app_icon`、`linkup_linkup-fetch` | 写明「本步使用 MCP 工具 xxx」「调用 volces-icon_generate_app_icon」等 |
| **script** | 执行当前技能 `scripts/` 下脚本 | 工具 `run_skill_script`，参数 `script_path`、`input_json` | 写明「本步使用 run_skill_script」「script_path=generate_image.py」等，禁止本步使用 call_api |
| **service** | 调用外部 HTTP API | 工具 `call_api`，参数 `url`、`method`、`headers_json`、`body` | 写明「本步使用 call_api」「请求 GET/POST 某 URL」等 |

另有**直接问大模型**：本步仅 LLM 推理或生成，不发起 tool_call。

流程上可**多步重复**或**跳过**某步，由 LLM 在 ReAct 循环中根据技能说明决定；**每一步应明确对应一个分支**，避免「技能要求跑脚本却去调 call_api」或反之。

## 在 SKILL.md 中写明执行分支

- **SKILL.md**：在描述某一步时，**直接写出本步使用的分支与工具**，例如：
  - 「本步**使用 run_skill_script**，script_path=hello_dha.py，input_json 可为空。禁止使用 call_api。」
  - 「本步**使用 MCP**：调用 volces-icon_generate_app_icon，参数 description、pic_size。」
  - 「本步**使用 call_api**：GET https://api.xxx.com/weather?city=…」
- **scripts 目录**：脚本本身可注释用法与参数；执行仍由 Agent 在需要时调用 `run_skill_script` 完成。若某 skill 的某步只允许 script，则在该步说明中写「仅 run_skill_script，禁止 call_api」。

不在 frontmatter 里声明步骤类型；当前为「LLM 解释型」：工具列表 + 技能全文注入，**依赖 SKILL 正文中每步写明执行分支**，由 LLM 按说明调用 MCP / run_skill_script / call_api 或直接回复。

## 工具说明

### run_skill_script

- **创建**：`create_run_skill_script_tool(skill_id)`，仅在「已选中技能」时加入当轮工具列表。
- **参数**：`script_path`（相对 `scripts/` 的文件名，如 `optimize-prompt.py`）、`input_json`（可选，作为 stdin 传入脚本）。
- **约束**：仅允许运行该技能 `scripts/` 目录内、`.py` 或 `.sh` 文件；禁止 `..`；超时由环境变量 `SKILL_SCRIPT_TIMEOUT`（默认 60 秒）控制。

### call_api

- **创建**：全局单例工具，每轮都加入。
- **参数**：`url`（必填）、`method`（默认 GET）、`headers_json`（可选 JSON 字符串）、`body`（可选）。
- **约束**：请求超时由 `CALL_API_TIMEOUT`（默认 30 秒）控制；支持任意 HTTP(S) 地址，安全与合规由技能作者与部署方负责。

## 与运行流程的关系

见 [运行流程 - 1.3 Skill 步骤执行体](runtime-flow.md#13-skill-步骤执行体目标模型-vs-当前实现)。
