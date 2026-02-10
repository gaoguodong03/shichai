# 下一步开发计划

本文档列出待开发项，先写文档再按文档实现。开发时优先查阅本文档与相关架构/功能文档。

---

## 1. 左侧栏宽度改为三分之一（已完成）

- **目标**：最左侧导航列宽度由固定 `w-52` 改为占视口宽度的 1/3。
- **涉及**：`frontend/src/views/MainView.vue` 中 `<nav>` 的宽度类；若需响应式，考虑 `w-1/3` 或 CSS 变量。
- **参考**：[UI/UX 设计](../design/ui-ux.md) 中的布局规则，更新文档中的「最左侧列」宽度说明。

---

## 2. Skill 详情页展示「其他部分」：assets、references、scripts（已完成，方案 A）

- **目标**：在 Skills 模块的「技能详情」页面中，除 SKILL.md 主内容外，展示该 skill 目录下的 **references**、**assets**、**scripts** 等辅助内容，便于查阅与调试。
- **参考结构**：以 `backend/skills/prompt-engineering-patterns` 为例：
  - `SKILL.md`：主说明（已有）
  - `references/`：如 chain-of-thought.md、few-shot-learning.md、prompt-optimization.md 等
  - `assets/`：如 few-shot-examples.json、prompt-template-library.md
  - `scripts/`：如 optimize-prompt.py
- **展示方式**：已采用方案 A（详情页内多 Tab：主说明 | References | Assets | Scripts，每 Tab 下列出文件列表，点击可预览文本/代码）。
- **后端**：已实现 `GET /api/settings/skills/{skill_id}/parts`（文件列表）、`GET .../parts/{references|assets|scripts}/{path}`（文件内容）。
- **文档**：已更新 [Skills 配置](../features/skills-config.md)。

---

## 3. 特定领域数据收集与报告生成 Skill + MCP（已完成）

- **目标**：做一个「特定领域数据收集 + 报告生成」的 Skill，并配套 MCP 提供数据获取与结构化能力。
- **实现**：
  - **设计文档**：[领域数据与报告 Skill+MCP](../features/domain-data-report-skill-mcp.md)，写明数据源（现有 linkup/exa/fetch + call_api）、工具列表、报告格式与示例流程。
  - **技能**：`backend/skills/data-report/`，含 SKILL.md（步骤、工具对应、报告格式约定）与 `assets/report-template.md`（可选模板）。
  - **MCP 映射**：chat 中改为按 `_SKILL_MCP_SERVERS` 配置，`data-report` 关联 linkup、exa、fetch（与 wechat-article-writer 共用）。
- **结论**：未新增 MCP，现有 MCP + call_api 已覆盖「搜索 / 抓取 / API / 文件」流水线；后续可针对具体领域在 SKILL 或 scripts 中细化。

---

## 4. Skill 步骤执行流程确认（当前 vs 目标模型）

- **目标模型（从流程上讲）**：Skill 的每一步（step）的执行体可能是：
  - **MCP**：调用某个 MCP 工具；
  - **script**：执行 skill 目录下的脚本（如 `scripts/optimize-prompt.py`）；
  - **service**：调用某个 API / 外部服务；
  - **直接问大模型**：本步仅由 LLM 推理或生成，不调工具。
- **流程形态**：可能是**多步重复**（多个 step 循环执行），也可能**跳过**某些 step（条件分支或可选步骤）。
- **待确认**：当前实现是否与上述模型一致；若不一致，需在文档中写明「当前流程」并决定是否演进。

### 当前流程（需对照代码确认）

- **现有设计**（见 [运行流程](../architecture/runtime-flow.md)、[Skill + MCP 设计](../architecture/skill-mcp-design-draft.md)）：
  - 两阶段：① 技能选择（name+description）→ ② 技能执行（选中 skill 全文 + 工具列表）。
  - 技能执行阶段：**单一 ReAct Agent**，系统提示词中包含选中 skill 的**完整正文**（SKILL.md）；Agent 根据自然语言描述的「步骤」自由决定下一步是回复文本还是发起 **tool_call**。
  - **显式可执行体**：目前仅有 **MCP 工具**（及内置工具如 read_file、export_session）；**没有**将 skill 下的 script、或通用「调用 API」作为一等步骤类型。
  - **多步/跳过**：由 ReAct 循环实现多轮 tool_call + LLM；是否执行某步、是否重复或跳过，完全由 LLM 根据 skill 正文理解后决定，**没有**显式的步骤编排器（orchestrator）按 step 类型分发到 MCP/script/service/LLM。
- **结论**：当前为「LLM 解释型」执行；script、service 已作为**工具**实现，LLM 按技能说明选择调用。
- **实现**：新增工具 `run_skill_script`（执行当前技能 scripts/ 下 .py/.sh）、`call_api`（HTTP 请求）；技能可在 SKILL.md 或 scripts 中描述何时使用。详见 [步骤类型与 Script/Service 工具](../architecture/step-types-and-tools.md) 与 [运行流程 - 1.3](../architecture/runtime-flow.md)。

---

## 5. 单步多次 MCP/工具调用展示（待实现）

- **现象**：某一步（一轮 Agent 决策）可能会调用同一或不同 MCP 工具**多次**，当前前端只展示**一次**工具调用参数（例如只显示一条 `exa_web_search_exa { "action": "tool_call", ... }`）。
- **目标**：支持在同一轮/同一条消息中展示**多次**工具调用（每次调用的工具名 + 参数 + 可选结果摘要）。
- **可能改动**：前后端接口与消息结构需扩展，例如：流式或最终消息中携带 `tool_calls[]` 数组而非单条；前端按数组逐条渲染。具体方案待设计时再定。
- **状态**：记录需求，后续更改前后端接口架构时实现。

---

## 6. MCP 本计划趋势：基于浏览器的 MCP 沙箱

- **目标**：将「基于浏览器的 MCP 沙箱」作为后续演进方向记录下来，便于后续调研与排期。
- **含义**：在浏览器环境中安全、隔离地运行或调试 MCP 相关逻辑（例如工具调用、参数校验、简单脚本），不依赖本地 Node/Python 环境即可体验或演示 MCP。

### MCP 演进与规划（记录）

- **当前**：本地/远程 MCP Server（stdio、HTTP），通过后端连接，前端仅展示工具名与调用结果。
- **规划方向**：浏览器内 MCP 沙箱。
  - **设想**：在浏览器侧提供隔离环境，可加载并执行部分 MCP 工具或适配器，用于演示、轻量调试或「无后端」体验。
  - **适用场景**：产品演示、前端自测工具调用、教学与体验；不替代现有后端 MCP 架构。
  - **与现有 MCP 的衔接**：可与现有 Server 并存，例如沙箱内工具仅在前端演示时可用，正式环境仍走后端 MCP。
- **状态**：文档记录，优先级低，作为路线图与可选方案参考。

---

## 开发顺序建议

1. **1**：改左侧栏宽度，改动小、可快速验收。
2. **4**：先确认并更新「Skill 步骤执行流程」文档（对照代码确认当前行为，写明与目标模型的差异；若需支持 script/service 为步骤类型，再拆子项）。
3. **2**：Skill 详情页扩展，需前后端配合（API + 展示方式确定后再实现）。
4. **3**：领域数据与报告 Skill + MCP，依赖 2 的 skill 结构理解与 MCP 设计习惯。
5. **5**：单步多次工具调用展示（待设计接口与实现）。
6. **6**：先写了文档。

完成每项后更新本文档状态（如「已完成」）及对应功能/架构文档。
