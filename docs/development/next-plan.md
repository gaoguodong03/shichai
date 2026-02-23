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
- **待确认**：当前实现是否与上述模型一致；若不一致，需在文档中写明「当前流程」并决定是否演进。（已对照代码确认，见下文）

### 当前流程（已对照代码确认，与实现一致）

- **现有设计**（见 [运行流程](../architecture/runtime-flow.md)、[Skill + MCP 设计](../architecture/skill-mcp-design-draft.md)）：
  - 两阶段：① 技能选择（name+description）→ ② 技能执行（选中 skill 全文 + 工具列表）。
  - 技能执行阶段：**单一 ReAct Agent**，系统提示词中包含选中 skill 的**完整正文**（SKILL.md）；Agent 根据自然语言描述的「步骤」自由决定下一步是回复文本还是发起 **tool_call**。
  - **显式可执行体**：目前仅有 **MCP 工具**（及内置工具如 read_file、export_session）；**没有**将 skill 下的 script、或通用「调用 API」作为一等步骤类型。
  - **多步/跳过**：由 ReAct 循环实现多轮 tool_call + LLM；是否执行某步、是否重复或跳过，完全由 LLM 根据 skill 正文理解后决定，**没有**显式的步骤编排器（orchestrator）按 step 类型分发到 MCP/script/service/LLM。
- **结论**：当前为「LLM 解释型」执行；script、service 已作为**工具**实现，LLM 按技能说明选择调用。
- **实现**：新增工具 `run_skill_script`（执行当前技能 scripts/ 下 .py/.sh）、`call_api`（HTTP 请求）；技能可在 SKILL.md 或 scripts 中描述何时使用。详见 [步骤类型与 Script/Service 工具](../architecture/step-types-and-tools.md) 与 [运行流程 - 1.3](../architecture/runtime-flow.md)。

---

## 5. 单步多次 MCP/工具调用展示（已完成，方案 A）

- **现象**：某一步（一轮 Agent 决策）可能会调用同一或不同 MCP 工具**多次**，当前前端只展示**一次**工具调用参数（例如只显示一条 `exa_web_search_exa { "action": "tool_call", ... }`）。
- **目标**：支持在同一轮/同一条消息中展示**多次**工具调用（每次调用的工具名 + 参数 + 可选结果摘要）。
- **可能改动**：前后端接口与消息结构需扩展，例如：流式或最终消息中携带 `tool_calls[]` 数组而非单条；前端按数组逐条渲染。
- **实现方案 A**：后端在 `react_step` 事件中增加 `tool_calls[]` 数组（同时保留单条 `tool_call` 字段），并将每次调用以 ```json 代码块``` 形式写入消息内容；前端 `ChatView` 解析消息中的所有 `tool_call` JSON 代码块，逐条渲染为独立的工具调用卡片，从而在同一轮中展示多次 MCP/工具调用。
- **状态**：已实现方案 A；若未来统一消息结构（例如完全依赖结构化字段而非代码块），再更新本节说明。

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

## 7. MCP 工具接入与参数整改（已完成）

- **目标**：统一 MCP 工具的接入方式与参数命名，减少 `__arg1` 这类中间产物对使用体验的影响，并修复部分 MCP「未连接 / 参数不正确」的问题。
- **环境变量与连接整改**：
  - 为 `volces-icon`、`amap-maps`、`zhipu-web-search` 显式配置 `transport.env`，统一从 `.env` 注入 API Key：
    - `volces-icon`：`VOLCES_IMAGE_API_KEY`。
    - `amap-maps`：`AMAP_MAPS_API_KEY`。
    - `zhipu-web-search`：MCP 要求 `BIGMODEL_API_KEY`，通过 `${ZHIPU_WEB_SEARCH_API_KEY}` 映射。
  - 效果：三者在 MCP 管理器启动时都能正常完成初始化，前端不再显示「未连接」（高德、智谱），错误由「连接失败」转为显式的业务/参数错误（若有）。
- **MCPToolManager 参数处理与日志**（`backend/app/mcp/manager.py`）：
  - 新增统一的参数归一化函数 `normalize_mcp_kwargs_for_call(server_id, original_tool_name, kwargs)`：
    - 作为**纯函数**集中管理 MCP 参数兼容/容错逻辑，内部用于真正调用 MCP 前的归一化，`chat.py` 也复用它来生成前端展示参数，保证「展示 == 实际调用」。
    - 在归一化前，若检测到 `__arg1` 等占位参数，会写调试日志（`log_mcp_arg1_*`）提醒还有 Skill/提示词在用旧样例。
  - 兼容逻辑（过渡期，尽量窄范围）：
    - `volces-icon_generate_app_icon`：
      - 若有 `__arg1` 且无 `description`，兼容纯字符串 / JSON 字符串，统一归一化为 `{"description": "...", "pic_size": "..."}`。
      - 在工具调用前后写入调试日志（raw kwargs、mapped kwargs），方便排查参数错误。
    - `amap-maps_maps_geo`：
      - 若仍然收到 `{"__arg1": "天安门,北京"}` 等形式，则在 manager 层将其拆分为 `{"address": "天安门", "city": "北京"}`，并兼容 JSON/dict 写法。
      - 在不破坏 Skill 语义的前提下，对北京场景增加精细容错：当 `address` 中包含「北邮 / 天安门 / 故宫 / 北京 / 西单 / 中关村」等关键词且 `city` 缺失或为区名（海淀、朝阳等）时，自动补 `city="北京"`，减少全国检索误匹配。
      - 调用前后写入调试日志：记录归一化后的参数与返回结果前 300 字，便于分析「参数不对 / 地方错判」问题。
    - `amap-maps` 路线/距离工具（如 `maps_direction_driving`、`maps_direction_walking`、`maps_bicycling`、`maps_direction_transit[_integrated]`、`maps_distance`）：
      - 若仍收到 `__arg1` 且其中是 JSON（如 `{"origin": "...", "destination": "...", "city": "...", "cityd": "..."}`），则在 manager 层解析出 `origin` / `destination` / `city` / `cityd` / `type` 等字段并补齐，避免旧模板导致 `INVALID_PARAMS`。
    - `file-reader` 系列 MCP（`file-reader_read_file` / `read_pdf` / `read_docx` / `read_xlsx`）：
      - 若仍收到 `__arg1`，统一视为 `path` 参数的别名：将 `__arg1` 写入 `path`，保证旧调用能正常读取文件。
  - 安全收尾：在所有归一化步骤之后，会统一删除残留的 `__arg*` 字段，只向 MCP 传递 schema 中定义的字段名，日志与前端展示都只暴露最终字段（如 `description`、`address`、`city`、`origin`、`destination`、`path`）。
- **Skill 与路由层整改**：
  - `backend/skills/data-report/SKILL.md`：
    - 明确 `exa_web_search_exa`、`linkup_linkup-search` 都必须使用 `query` 参数传入关键词，禁止再用 `__arg1`。
  - `backend/skills/amap-maps/SKILL.md`：
    - 强调地图相关任务（位置、路线、天气、周边搜索）**只使用 `amap-maps` MCP**，不要为这些任务调用 `linkup`、`exa` 等通用搜索 MCP。
    - 重申 `maps_geo`、`maps_direction_*` 等工具的参数规范（`address` / `city` / `origin` / `destination`）。
  - `backend/app/agent/skill_selector.py`：
    - 在 LLM 路由前增加简易规则：若用户输入/历史摘要中明显包含「怎么走 / 路线 / 导航 / 公交 / 地铁 / 经纬度 / 坐标 / 多远」等关键词，且存在 `amap-maps` 技能，则**直接选择 `amap-maps`**，避免地图问题被 `data-report` 等技能抢走并误用 linkup。
- **前端展示层参数归一化**（`backend/app/api/chat.py`）：
  - 在构造 `react_step` 事件和插入 ```json 工具调用代码块``` 时，对**展示用参数**做与 manager 一致的轻量归一化，不影响实际 MCP 调用，但保证两者一致：
    - 对 MCP 工具 `volces-icon_*`、`amap-maps_*`、`file-reader_*`，直接调用 `normalize_mcp_kwargs_for_call(server_id, original_tool_name, args)`，使展示参数与 manager 最终发给 MCP 的参数完全一致（包括自动补 `city="北京"`、解析 `__arg1` 为 `origin`/`destination`、`path` 等）。
    - 对内置工具 `read_file`，若仍收到 `{"__arg1": "xxx.md"}` 形式，则在展示层将 `__arg1` 重命名为 `path`，与工具说明保持一致。
  - 效果：前端与文档看到的工具调用参数名与 MCP schema / Skill 说明保持一致（`description`、`address`、`city`、`origin`、`destination`、`path` 等），而不是中间层占位名 `__arg1` / `__arg2`；同时前端展示的 JSON 即为「manager 实际发起调用时的参数快照」。

> 后续迭代建议：随着 Skill 与提示词清理完成，可进一步下掉 manager 中对 `__arg1` 及相关兼容逻辑，仅保留日志，用完全 schema 驱动的参数命名；本文档保持记录当前过渡期方案与兼容策略。

---

## 开发顺序建议

1. **1**：改左侧栏宽度，改动小、可快速验收。
2. **4**：先确认并更新「Skill 步骤执行流程」文档（对照代码确认当前行为，写明与目标模型的差异；若需支持 script/service 为步骤类型，再拆子项）。
3. **2**：Skill 详情页扩展，需前后端配合（API + 展示方式确定后再实现）。
4. **3**：领域数据与报告 Skill + MCP，依赖 2 的 skill 结构理解与 MCP 设计习惯。
5. **5**：单步多次工具调用展示（已完成，方案 A）。
6. **6**：先写了文档。

完成每项后更新本文档状态（如「已完成」）及对应功能/架构文档。
