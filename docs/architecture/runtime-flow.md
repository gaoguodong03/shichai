# 运行流程文档（程序逻辑与运行结果）

本文档描述 DHA 系统的**整体程序逻辑**和**实际运行流程**，重点说明：**两阶段设计**（先选技能、再执行技能）；**Skill 的每一步由技能执行 Agent 执行，步骤中如需要才调用 MCP**；**不存在 Agent 调用 Agent**。

---

## 一、整体程序逻辑

### 1.1 核心结论

- **两阶段设计**：每轮 chat 固定两次 LLM 调用：① 技能选择（仅 name+description）→ ② 技能执行（选中 skill 的完整内容 + 工具）。
- **Skill 是「步骤说明书」**：选中的 Skill 完整指令（SKILL.md）注入到技能执行 Agent 的系统提示词，Agent **按 Skill 描述的步骤顺序**执行；每一步可以是纯推理，也可以**在这一步里**决定调用 MCP 工具。
- **MCP 是「步骤内能力」**：当某一步需要搜索、抓取、计算等**执行能力**时，Agent 输出 tool_call，由 ReAct 的 Tool 节点执行对应 MCP 工具，结果回到**同一个** Agent，再继续下一步。
- **无 Agent 调 Agent**：技能选择与技能执行都是直接调用 LLM，不存在 Agent 调用 Agent。

### 1.2 数据流概览

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Chat API：组装历史摘要、获取 tools、skills_for_selection     │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  第一次调用：select_skill(llm, user_msg, name+description)    │
│  • 输入：用户消息 + 各 skill 的 name（+ description，若有）   │
│  • 输出：选中的 skill_id                                     │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  create_skill_execution_agent(llm, tools, 选中skill完整内容)   │
│  • 系统提示词 = 用户设置 + 选中 skill 全文 + 工具列表          │
│  • 图：agent 节点 ↔ should_continue ↔ call_tool / end       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  技能执行 Agent (ReAct) 运行                                 │
│  • 每次迭代：LLM 根据「当前消息 + Skill 步骤」决定：          │
│    - 只回复文本（本步不调工具）→ 结束或继续                   │
│    - 调用工具（本步需要 MCP）→ call_tool 节点执行 MCP         │
│  • 工具结果作为新消息回到同一 Agent，继续下一步               │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
  最终回复（文本 + 可选 meta：skill / mcp_servers / tools）
```

### 1.3 Skill 步骤执行体（目标模型 vs 当前实现）

从流程上讲，Skill 的**每一步（step）**的执行体在目标模型中可以是：

- **MCP**：调用某个 MCP 工具
- **script**：执行 skill 目录下的脚本（如 `scripts/optimize-prompt.py`）
- **service**：调用某个 API / 外部服务
- **直接问大模型**：本步仅由 LLM 推理或生成，不调工具

流程形态上可以是**多步重复**或**跳过**某些 step。

**当前实现**：技能执行阶段由单一 ReAct Agent 根据 SKILL 正文理解步骤。每一步可走**多种执行路径**之一：MCP、script（run_skill_script）、service（call_api）、export（export_session_to_md，仅单聊）、只读文件（file-reader/filesystem）、或仅推理。完整清单与单聊/群聊差异见 [步骤类型与工具](step-types-and-tools.md)。

**约定**：SKILL.md 中**每步应写明本步走哪一路径**（见 [步骤类型与工具](step-types-and-tools.md)），避免模型误选工具。多步/跳过由 LLM 在 ReAct 循环中决定；所有路径均以工具形式提供（或仅回复文本），LLM 按技能说明选择调用。

---

## 二、启动与初始化

### 2.1 后端启动

- 启动命令：`uvicorn app.main:app` 或 `python -m app.main`。
- 加载 `.env`、挂载路由（如 `/api/chat/stream`、`/api/settings/*`）。
- **不在此阶段**连接 MCP 或加载 Skill 正文；仅准备好 API。

### 2.2 MCP 与 Skills 初始化（应用启动时）

在 FastAPI **lifespan 启动阶段**执行一次（与关闭时 cleanup 同任务，避免 MCP/anyio 跨任务错误）：

1. **MCP Manager**
   - 读取 `config/mcp_servers.json`，对每个 `enabled: true` 的 Server 建立连接（stdio 或 Streamable HTTP）。
   - 对每个 Server 调用 `list_tools()`，得到工具列表；工具在系统内命名为 `{server_id}_{tool_name}`（如 `time_get_time`、`exa_web_search_exa`）。
   - 将 MCP 工具封装为 LangChain Tool（**异步 func**，直接 `session.call_tool`），供技能执行 Agent 使用。

2. **Skills Loader**
   - 扫描 `skills/` 下各子目录，读取每个目录下的 `SKILL.md`。
   - 解析 YAML frontmatter（name、description）和正文。
   - `get_skills_for_selection()`：返回 name+description 精简列表（用于第一次调用技能选择）。
   - `get_skill_full_content(skill_id)`：返回指定技能的完整内容（用于第二次调用技能执行）。

3. **标记已初始化**
   - 之后同一进程内不再重复做上述 MCP 连接与 Skill 扫描。

**要点**：MCP Manager 和 Skills Loader 为**技能选择**和**技能执行**两阶段提供工具列表与技能内容。MCP 工具调用为**纯异步**（Agent 侧 `await tool.func(...)`），无同步包装，与主事件循环同任务。

---

## 三、单次请求的完整流程

### 3.1 请求入口

- 前端：`POST /api/chat/stream`，body：`{ "message": "…", "session_id": "…" }`。
- 后端：`chat_stream(request)`。

### 3.2 单聊主流程摘要（已下线）

单聊已合并为统一会话，现仅保留群聊路径。以下为历史说明：

1. **ensure_initialized()** — 若未初始化则执行 MCP 连接与 Skills 加载。
2. **导出意图分支** — 若识别为「导出会话」等意图，走导出逻辑后返回。
3. **工具组装** — 现由 `build_tools_for_group_chat(all_tools, dha, workspace_id)` 得到工具列表（见 [步骤类型与工具](step-types-and-tools.md)）；会话内由主持人或选 DHA/技能决定执行体。
4. **create_skill_execution_agent** — 用技能完整内容与 tools 构建 ReAct Agent。
5. **流式执行** — Agent 按 Skill 步骤运行，每步可走 MCP / run_skill_script / call_api 等，结果流式返回前端。

### 3.3 准备与第一次调用（技能选择）

1. **ensure_initialized()**  
   若未初始化，则执行上节的 MCP 连接与 Skills 加载。

2. **获取工具与技能列表**
   - `tools = mcp_manager.get_tools()` + 内置工具（`export_session_to_md`）；读文件由 MCP 的 file-reader/filesystem 工具提供（如 `filesystem_read_text_file`），无独立 `read_file` 工具。
   - `skills_for_selection = skills_loader.get_skills_for_selection()`：仅含 name、description（若有）。

3. **构建历史摘要**（多轮 chat）
   - `history_summary = _build_history_summary(history)`：从会话历史生成摘要文本。
   - **只保留最近 10 轮**：`_TURN_SUMMARIES` 与回退路径均只取最近 10 轮，控制 token 开销。

4. **第一次调用 LLM：技能选择**
   - `selected_skill_id = select_skill(llm, user_message, skills_for_selection, history_summary)`。
   - 输入：用户消息 + 各 skill 的 name+description（**不给完整 skill 内容**）。
   - 输出：选中的 `skill_id`（如 `wechat-article-writer`）。

### 3.4 第二次调用（技能执行）

1. **获取选中技能的完整内容**
   - `skill_full_content = skills_loader.get_skill_full_content(selected_skill_id)`。

2. **创建技能执行 Agent**
   - `agent = create_skill_execution_agent(llm, tools, skill_full_content, extra_system_prompt)`。
   - 系统提示词中包括：
     - 用户设置（可选）；
     - 选中 skill 的**完整内容**；
     - 工具列表（名称 + 描述）；
     - 工具调用格式（JSON）。

3. **初始状态**
   - `messages` = 用户问题（含历史摘要，若有）；
   - `tools` = 上面拿到的工具列表。

### 3.5 ReAct 循环（技能执行 Agent，步骤中可能调 MCP）

图结构（LangGraph）：

```
  Entry → agent 节点 → should_continue
                            │
              ┌─────────────┼─────────────┐
              │ call_tool   │     end     │
              ▼             │             ▼
         call_tool 节点     │            END
              │             │
              └─────────────┘
                (工具结果作为 HumanMessage 回到 agent 节点)
```

**agent 节点（call_model）**：

- 输入：当前 `state["messages"]`、`state["tools"]`。
- 系统提示词已在建图时固定，包含：选中 skill 的完整内容 + 工具列表。
- 调用 LLM：`llm.invoke(messages)`，得到一条 `AIMessage`。
- 该消息可能包含：
  - **仅文本**：表示本步只做推理，不调工具。
  - **tool_calls**：表示本步需要执行能力，要调用 MCP。

**should_continue**：

- 若上一条 AIMessage 含有 `tool_calls` → 走 **call_tool** 分支。
- 否则 → **end**，结束循环。

**call_tool 节点**：

- 从上一条 AIMessage 里取出每个 `tool_call` 的 `name` 和 `args`；对 MCP 工具做参数规范化（如 `__arg1` → schema 首参）。
- 在 `state["tools"]` 中按 `name` 查找 LangChain Tool；MCP 工具的 `func` 为异步，直接 `await tool.func(**args)` 执行，与主循环同任务。
- 将结果封装成 `HumanMessage(content="工具 xxx 的执行结果: …")`，**追加到 messages**。
- 下一轮迭代：**再次进入 agent 节点**，LLM 继续按 Skill 步骤决定：要么再调工具，要么输出最终回复。

### 3.6 流式输出（SSE）

- 后端在 `agent.astream(initial_state)` 的迭代中，根据事件类型向前端推送：
  - `event: start`
  - `event: react_step`（思考或工具结果，带 meta：skills / mcp_servers / tools）
  - `event: content`（最终或中间文本，带 meta）
  - `event: end` / `event: error`
- meta 中的 `skills` 为选中的 `skill_id`；若本轮有 tool_calls，则按工具所属 server 更新 `mcp_servers`。

### 3.7 会话历史

- 流式结束后，将本轮「用户消息 + 助手完整回复」追加到该 `session_id` 的对话历史中，并做长度截断。
- 下次同一 session 的请求会带上**历史摘要**，参与技能选择与技能执行的输入。

---

## 3.7 Chat 流程时序与等待点

用户从「发送消息」到「看到首字」的时序如下（`call_model` 使用 `astream` 做 token 级流式）：

```
T0  用户点击发送
│
├─ T1  ensure_initialized()      [首次约 1–3s：MCP 连接 + Skill 加载]
│
├─ T2  技能选择 select_skill     [LLM 调用 #1：ainvoke，等完整返回]
│      输入：用户消息 + 各 skill name+description
│      输出：skill_id
│
├─ T3  asyncio.sleep(1)          [固定延迟，避免 DashScope 限流；可设 QWEN_REQUEST_DELAY_SEC=0 关闭]
│
├─ T4  技能执行 Agent 第一次 call_model   [LLM 调用 #2：astream，token 逐字推给前端]
│      输入：system_prompt(含 skill 全文) + 用户消息
│      输出：AIMessage（文本或 tool_calls）
│
├─ T5  [若 tool_calls] call_tool 执行 MCP   [耗时取决于工具：搜索/抓取等]
│
├─ T6  技能执行 Agent 第二次 call_model   [LLM 调用 #3：astream，token 逐字推给前端]
│      ... 循环直到无 tool_calls ...
│
└─ T7  流式推送 content 事件 → 前端展示
```

**主要等待来源**：

| 阶段 | 说明 | 可调参数 |
|------|------|----------|
| 技能选择 | 第一次 LLM 调用，`ainvoke` 等完整响应 | 无，可考虑流式或跳过（单 skill 时已跳过） |
| 固定延迟 | 技能选择与 Agent 间 1 秒，防 429 | `QWEN_REQUEST_DELAY_SEC=0` 可关闭 |
| Agent call_model | 使用 `astream` token 级流式，首字更快 | 若 astream 失败则回退 ainvoke |
| 工具执行 | MCP 调用（搜索、抓取等） | 受外部 API 影响 |

**当前实现**：`call_model` 使用 `client.astream(messages)` token 级流式调用，配合 `stream_mode="messages"` 将 chunk 推给前端；若 astream 失败则回退到 `ainvoke`。

---

## 四、Skill 与 MCP 在运行中的角色（对照）

| 维度       | Skill                          | MCP                                    |
|------------|--------------------------------|----------------------------------------|
| 是什么     | 步骤说明书（SKILL.md 注入提示词） | 可执行工具集（通过 MCP Server 注册）     |
| 谁使用     | 技能执行 Agent（LLM）          | 技能执行 Agent（通过 call_tool）       |
| 何时起作用 | 第一次调用：选技能；第二次调用：按步骤执行 | 某一步需要「执行能力」时（搜索、抓取等） |
| 调用关系   | 不「调用」MCP，只指导何时用哪些能力 | 被 Agent 在步骤中按需调用               |

- **Skill 的每一步可能会调用 MCP**：指的是「Agent 在执行 Skill 描述的某一步时，若该步需要搜索/抓取/计算等，就会在本轮或后续轮发出 tool_call，从而调用 MCP」。
- **不会有 Agent 直接调用 Agent**：技能选择与技能执行都是直接调用 LLM；技能执行阶段只有一个 ReAct 循环。

---

## 五、运行结果示例（单轮简化）

以用户说「生成北邮校庆文案」为例：

1. **第一次调用（技能选择）**  
   - 输入：用户消息 + 各 skill 的 name+description。  
   - 输出：`{"skill_id": "wechat-article-writer"}`。

2. **第二次调用（技能执行）**  
   - 输入：wechat-article-writer 的完整 SKILL 内容 + 用户问题。  
   - **第一轮 agent**：可能输出 AIMessage 带 tool_calls，例如 `exa_web_search_exa` 或 `fetch_fetch`。  
   - **call_tool**：执行对应 MCP，结果写入 HumanMessage。  
   - **第二轮 agent**：输入历史 + 工具结果；继续按 Skill 步骤执行，可能再调工具或直接输出正文 → end。

3. **结果**  
   - 前端收到：`content` 事件中的最终文案 + meta（如 `skills: ["wechat-article-writer"]`、`mcp_servers: ["exa"]` 等）。

---

## 六、相关文档

- [架构概述](./overview.md)：协作关系图与 Skill/MCP 定位  
- [Skill + MCP 设计](./skill-mcp-design-draft.md)：两阶段设计说明  
- [流式与记忆](streaming-and-memory-update.md)：流式输出与记忆窗口  
- [API 设计](./api-design.md)：接口与事件格式  
- [LLM 提示词结构](./llm-prompt-structure.md)：每次请求发送给大模型的具体内容  
