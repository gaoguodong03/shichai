# 步骤类型与 Script/Service 工具

本文档说明 Skill 步骤的执行体类型及当前实现方式（script、service 作为工具注入技能执行 Agent）。

## 步骤类型（目标模型）

每一步（step）的执行体可以是：

| 类型 | 含义 | 当前实现 |
|------|------|----------|
| **MCP** | 调用某个 MCP 工具 | 已有：按技能过滤 MCP 工具列表，LLM 选择调用 |
| **script** | 执行 skill 目录下的脚本 | 工具 `run_skill_script`：执行当前技能 `scripts/` 下 .py/.sh |
| **service** | 调用某个 API / 外部服务 | 工具 `call_api`：HTTP 请求（url、method、headers、body） |
| **直接问大模型** | 本步仅 LLM 推理或生成 | 不发起 tool_call，直接文本回复 |

流程上可**多步重复**或**跳过**某步，由 LLM 在 ReAct 循环中根据技能说明决定。

## 声明方式：SKILL.md 与 scripts

- **SKILL.md**：在正文中自然语言描述「何时运行某脚本」「何时调用某 API」，例如：
  - 「若需优化提示词，可调用 scripts 下的 `optimize-prompt.py`，传入 JSON …」
  - 「获取天气请调用 API：GET https://...」
- **scripts 目录**：脚本本身可读写、或通过注释/文档说明自己的用法与参数，供 LLM 与用户参考；执行仍由 Agent 在需要时调用 `run_skill_script` 完成。

不需要在 frontmatter 里声明步骤类型；当前为「LLM 解释型」：工具列表 + 技能全文注入，由 LLM 决定调用 MCP / run_skill_script / call_api 或直接回复。

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
