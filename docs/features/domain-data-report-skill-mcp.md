# 领域数据收集与报告生成 Skill + MCP 设计

## 目标

做一个「特定领域数据收集 + 报告生成」的 Skill，并配套使用现有 MCP 与内置工具，实现：从用户指定来源（网页搜索、URL 抓取、外部 API）收集数据 → 结构化整理 → 输出 Markdown/表格报告。

## 领域与数据源（当前方案）

- **领域**：先做**通用型**数据收集与报告，不绑定单一业务（如运营指标、实验数据、问卷统计可后续在 SKILL 中细化）。
- **数据源**（由现有能力覆盖）：
  - **网页搜索**：Exa、Linkup（MCP）
  - **URL 抓取**：Fetch MCP、Linkup fetch
  - **外部 API**：`call_api` 工具（GET/POST 等）
  - **本地/结构化数据**：`read_file`、file-reader MCP（PDF/Excel 等）
- **结论**：不新增 MCP，用现有 linkup、exa、fetch + 内置 call_api、read_file 即可覆盖「搜索 → 抓取 → 调用 API → 读文件」的流水线。

## 技能职责

- 定义数据收集的**步骤**：确认用户需求（主题、时间范围、指标/字段）→ 选择数据源（搜索/URL/API/文件）→ 调用相应工具 → 整理成结构化数据。
- 定义**报告结构**：Markdown 标题、表格、列表；可选模板放在 `assets/`。
- 在 SKILL.md 中说明：何时用 linkup/exa 搜索、何时用 fetch 抓取、何时用 call_api 调接口、如何汇总成报告。

## 工具列表（本技能可用）

| 类型 | 工具 | 用途 |
|------|------|------|
| MCP | linkup（linkup-search, linkup-fetch） | 搜索、抓取网页 |
| MCP | exa（exa_web_search_exa） | 网络搜索 |
| MCP | fetch（fetch_fetch） | 按 URL 抓取为 Markdown |
| 内置 | call_api | 调用用户指定的 HTTP API |
| 内置 | read_file / file-reader_* | 读取用户引用或产出文件 |
| 内置 | run_skill_script | 可选：执行 scripts/ 下聚合脚本 |

## 报告格式与示例流程

- **输出**：Markdown 文档，包含标题、可选摘要、表格或列表形式的数据汇总。
- **存放**：可建议用户「导出为 .md」或写入 `data/agent-outputs/` 下某文件（通过现有机制）。
- **示例流程**：
  1. 用户：「帮我收集最近一周关于 XX 的报道并生成一份汇总报告」
  2. Agent 确认主题与时间范围，用 exa/linkup 搜索 → 用 fetch 抓取部分 URL → 提取标题、来源、时间、摘要 → 整理成 Markdown 表格 → 输出报告摘要并提示可导出。

## 技能 ID 与 MCP 映射

- **skill_id**：`data-report`
- **关联 MCP**：`linkup`、`exa`、`fetch`（与 wechat-article-writer 共用，通过 `_SKILL_MCP_SERVERS` 配置）。

## 后续可选

- 在 SKILL 的 `assets/` 中放报告模板（如 `report-template.md`）。
- 在 `scripts/` 中放简单聚合脚本（如从多个 JSON 合并为一张表），由 Agent 在需要时调用 `run_skill_script`。
