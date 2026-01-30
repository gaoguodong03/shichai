# 运行流程文档（程序逻辑与运行结果）

本文档描述 DHA 系统的**整体程序逻辑**和**实际运行流程**，重点说明：**只有一个 ReAct Agent**；**Skill 的每一步由该 Agent 执行，步骤中如需要才调用 MCP**；**不存在 Agent 调用 Agent**。

---

## 一、整体程序逻辑

### 1.1 核心结论

- **单一 Agent**：全系统只有一个 ReAct 循环（一个 LLM + 一个「思考 → 可选工具调用 → 再思考」的循环）。没有「主 Agent 调子 Agent」。
- **Skill 是「步骤说明书」**：Skill 的完整指令（SKILL.md）被注入到该 Agent 的系统提示词里，Agent **按 Skill 描述的步骤顺序**执行；每一步可以是纯推理，也可以**在这一步里**决定调用 MCP 工具。
- **MCP 是「步骤内能力」**：当某一步需要搜索、抓取、计算等**执行能力**时，Agent 输出 tool_call，由 ReAct 的 Tool 节点执行对应 MCP 工具，结果回到**同一个** Agent，再继续下一步。
- **无 Agent 调 Agent**：所有「按 Skill 步骤执行」和「调用 MCP」都发生在同一个 ReAct 循环内，不存在 Agent 调用 Agent。

### 1.2 数据流概览

```
用户消息
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Chat API：组装「历史 + 用户消息」、拿到 tools + skills_instruction │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  create_react_agent(llm, tools, skills_instruction)         │
│  • 系统提示词 = 工具列表 + 技能选择规则 + 可用技能(SKILL.md)    │
│  • 图：agent 节点 ↔ should_continue ↔ call_tool / end       │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│  Agent (ReAct) 运行                                          │
│  • 每次迭代：LLM 根据「当前消息 + Skill 步骤」决定：           │
│    - 只回复文本（本步不调工具）→ 结束或继续                   │
│    - 调用工具（本步需要 MCP）→ call_tool 节点执行 MCP         │
│  • 工具结果作为新消息回到同一 Agent，继续下一步               │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
  最终回复（文本 + 可选 meta：skill / mcp_servers / tools）
```

---

## 二、启动与初始化

### 2.1 后端启动

- 启动命令：`uvicorn app.main:app` 或 `python -m app.main`。
- 加载 `.env`、挂载路由（如 `/api/chat/stream`、`/api/settings/*`）。
- **不在此阶段**连接 MCP 或加载 Skill 正文；仅准备好 API。

### 2.2 延迟初始化（第一次聊天请求时）

在**第一次**收到聊天请求时执行一次：

1. **MCP Manager**
   - 读取 `config/mcp_servers.json`，对每个 `enabled: true` 的 Server 建立连接（stdio 或 HTTP）。
   - 对每个 Server 调用 `list_tools()`，得到工具列表；工具在系统内命名为 `{server_id}_{tool_name}`（如 `time_get_time`、`exa_web_search_exa`）。
   - 将 MCP 工具封装为 LangChain Tool，供 ReAct 使用。

2. **Skills Loader**
   - 扫描 `skills/` 下各子目录，读取每个目录下的 `SKILL.md`。
   - 解析 YAML frontmatter（name、description）和正文，组成「可用技能」的完整指令文本。
   - `get_active_skills_instructions()` 返回所有已加载 Skill 的合并文本（用于注入系统提示词）。

3. **标记已初始化**
   - 之后同一进程内不再重复做上述 MCP 连接和 Skill 扫描。

**要点**：只有**一个** MCP Manager 和一个 Skills Loader；它们为**那一个** ReAct Agent 提供「工具列表」和「Skill 步骤说明」。

---

## 三、单次请求的完整流程

### 3.1 请求入口

- 前端：`POST /api/chat/stream`，body：`{ "message": "…", "session_id": "…" }`。
- 后端：`chat_stream(request)`。

### 3.2 准备 Agent 输入

1. **ensure_initialized()**  
   若未初始化，则执行上节的 MCP 连接与 Skills 加载。

2. **获取工具与技能文本**
   - `tools = mcp_manager.get_tools()`：当前所有 MCP 工具（LangChain Tool 列表）。
   - `skills_instruction = skills_loader.get_active_skills_instructions()`：所有 Skill 的合并指令（含「技能选择」规则和每个 SKILL.md 的步骤说明）。

3. **创建 ReAct Agent**
   - `llm = QwenLLM()`（或配置的其它 LLM）。
   - `agent = create_react_agent(llm, tools, skills_instruction)`。
   - 系统提示词中包括：
     - 工具列表（名称 + 描述）；
     - 工具调用格式（JSON）；
     - **技能选择**：根据用户意图先选一个 Skill（如 wechat-article-writer / app-icon-generator）；
     - **可用技能**：`skills_instruction` 的完整内容（即「按该 Skill 的步骤执行」的说明书）。

4. **初始状态**
   - `messages` = 会话历史（截断到最近 N 条）+ 本条用户消息。
   - `tools` = 上面拿到的工具列表（同一份引用会一直在状态里）。

**要点**：全流程只有这里创建的一次 `agent`，没有在内部再创建「子 Agent」。

### 3.3 ReAct 循环（同一 Agent，Skill 步骤中可能调 MCP）

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
- 系统提示词已在建图时固定，包含：工具列表 + 技能选择 + 可用技能（Skill 步骤）。
- 调用 LLM：`llm.invoke(messages)`，得到一条 `AIMessage`。
- 该消息可能包含：
  - **仅文本**：表示本步只做推理（例如「先澄清需求」「规划结构」），不调工具。
  - **tool_calls**：表示本步需要执行能力，要调用 MCP；内容为 `(tool_name, arguments)`。

**should_continue**：

- 若上一条 AIMessage 含有 `tool_calls` → 走 **call_tool** 分支。
- 否则 → **end**，结束循环。

**call_tool 节点**：

- 从上一条 AIMessage 里取出每个 `tool_call` 的 `name` 和 `args`。
- 在 `state["tools"]` 中按 `name` 查找 LangChain Tool（即某个 MCP 工具的封装）。
- 执行：`tool.func(**args)` 或等价调用；内部会通过 MCP Session 调用真实 MCP Server。
- 将执行结果格式化为字符串，封装成 `HumanMessage(content="工具 xxx 的执行结果: …")`，**追加到 messages**。
- 下一轮迭代：**再次进入 agent 节点**，LLM 看到「工具结果」+ 继续按 Skill 步骤决定：要么再调工具，要么输出最终回复。

**要点**：

- 每一轮都是**同一个** Agent（同一个图、同一个 LLM、同一套 Skill 指令）。
- 「Skill 的某一步」对应的是 LLM 在某轮迭代中决定：这一步是只说话，还是调用 MCP；若调用 MCP，则在该轮走 call_tool，结果回到下一轮 agent，继续按 Skill 下一步执行。
- **不存在** Agent 调用 Agent；只存在「Agent 调用 MCP 工具」。

### 3.4 流式输出（SSE）

- 后端在 `agent.astream(initial_state)` 的迭代中，根据事件类型向前端推送：
  - `event: start`
  - `event: react_step`（思考或工具结果，带 meta：skills / mcp_servers / tools）
  - `event: content`（最终或中间文本，带 meta）
  - `event: end` / `event: error`
- meta 中的 `skills` 来源于：  
  - 先根据用户消息推断（如文案→wechat-article-writer）；  
  - 若本轮有 tool_calls，则按 `server_id` 从 `_MCP_SERVER_TO_SKILL` 覆盖（如调用了 exa → 显示 wechat-article-writer）。

### 3.5 会话历史

- 流式结束后，将本轮「用户消息 + 助手完整回复」追加到该 `session_id` 的对话历史中，并做长度截断。
- 下次同一 session 的请求会带上这段历史，仍是**同一个** Agent 逻辑，只是多了一些历史消息。

---

## 四、Skill 与 MCP 在运行中的角色（对照）

| 维度       | Skill                          | MCP                                    |
|------------|--------------------------------|----------------------------------------|
| 是什么     | 步骤说明书（SKILL.md 注入提示词） | 可执行工具集（通过 MCP Server 注册）     |
| 谁使用     | 同一个 ReAct Agent（LLM）      | 同一个 ReAct Agent（通过 call_tool）   |
| 何时起作用 | 每一步推理时（选技能、按步骤执行） | 某一步需要「执行能力」时（搜索、抓取等） |
| 调用关系   | 不「调用」MCP，只指导何时用哪些能力 | 被 Agent 在步骤中按需调用               |

- **Skill 的每一步可能会调用 MCP**：指的是「Agent 在执行 Skill 描述的某一步时，若该步需要搜索/抓取/计算等，就会在本轮或后续轮发出 tool_call，从而调用 MCP」。
- **不会有 Agent 直接调用 Agent**：整个系统只有一个 ReAct 循环，没有子 Agent 或嵌套 Agent。

---

## 五、运行结果示例（单轮简化）

以用户说「生成北邮校庆文案」为例（wechat-article-writer 被选中）：

1. **第一轮 agent**  
   - 输入：用户消息 + 系统提示（含 wechat-article-writer 的步骤）。  
   - 输出：AIMessage 仅文本，例如「按 wechat-article-writer，先澄清：校庆年份、受众、风格…」（**本步不调工具**）。  
   - should_continue → end，流式把这段文本推给前端。

2. 若用户补全信息后再说「可以写了」：
   - **第一轮 agent**  
     - 输出：AIMessage 带 tool_calls，例如 `exa_web_search_exa` 或 `fetch_fetch`（执行「搜索补充」这一步）。  
   - **call_tool**  
     - 执行对应 MCP，结果写入 HumanMessage。  
   - **第二轮 agent**  
     - 输入：历史 + 工具结果；仍按同一 Skill 步骤继续。  
     - 输出：可能再调工具，或直接输出正文（本步不调工具）→ end。

3. **结果**  
   - 前端收到：`content` 事件中的最终文案 + meta（如 `skills: ["wechat-article-writer"]`、`mcp_servers: ["exa"]` 等）。  
   - 全程**只有一个** ReAct Agent；Skill 指导「步骤」，MCP 在步骤需要时被调用。

---

## 六、相关文档

- [架构概述](./overview.md)：协作关系图与 Skill/MCP 定位  
- [流式处理](./react-stream.md)：ReAct 流式实现细节  
- [API 设计](./api-design.md)：接口与事件格式  
