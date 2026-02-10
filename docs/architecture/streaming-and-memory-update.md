# 流式输出与记忆窗口优化设计

本文档作为「变化设计说明」，在正式改代码前先确定目标行为与改动点。对应你提到的第 3 条（流式）、第 5 条（保留最近 10 轮）。

---

## 一、目标概述

- **流式输出（LLM 级别）**  
  - 现在：ReAct Agent 内部对 LLM 使用 `ainvoke`，一次性拿完整回复，再通过 SSE 推送；虽然外层 `agent.astream` 已支持 token 流，但底层 `call_model` 仍是整段式。  
  - 目标：在 Agent 的每一轮调用中，尽可能使用 **token 级流式**，让前端更早看到首字。

- **记忆窗口（最近 10 轮）**  
  - 现在：`_build_history_summary` 会把所有 Turn 的摘要拼进去，总长度无硬上限。  
  - 目标：无论是 `_TURN_SUMMARIES` 还是回退的原始消息预览，**只向 LLM 提供最近 10 轮对话的摘要**。

---

## 二、当前实现小结

### 2.1 流式相关

- 入口：`/api/chat/stream` → `chat_stream`（`backend/app/api/chat.py`）
- ReAct 图：`create_skill_execution_agent`（`backend/app/agent/graph.py`）  
  - 节点：`agent`（call_model）、`should_continue`、`call_tool`。  
  - 当前 `call_model` 使用：
    - `client = llm.get_client()`
    - `resp = await client.ainvoke(messages)`（一次性整段返回）
- 外层：`agent.astream(initial_state, stream_mode=["updates", "messages", "values"])`  
  - `stream_mode="messages"` 已尝试基于 `langgraph` 的 token 流进行 SSE 推送。

**问题**：如果底层 LLM 客户端在 `bind_tools()` 后不支持真正的 streaming，或者 `call_model` 里只调用 `ainvoke`，用户仍然要等一整段回复。

### 2.2 记忆相关

- 历史结构：`_CHAT_HISTORY[session_id] = [HumanMessage, AIMessage, ...]`
- Turn 摘要：`_TURN_SUMMARIES[session_id] = [str, str, ...]`
- 摘要构建：`_build_history_summary(session_id, history)`（`chat.py`）
  - 若 `_TURN_SUMMARIES` 存在：直接把全部轮次摘要拼起来。
  - 否则：遍历全部历史消息，对每一对 Human+AI 生成预览。

**问题**：长对话时摘要可能无限增长，影响 token 开销与模型稳定性。

---

## 三、流式输出改进设计（第 3 条）

### 3.1 设计原则

1. **不改变对外 API 形状**：仍然是 SSE `content` 事件；前端无需改动协议。
2. **优先利用 LangGraph 的 `stream_mode="messages"`**：让 Agent 层先流式，再补救底层不支持的情况。
3. **兼容回退**：若底层 LLM 不支持 streaming 或出错，仍可回落到 `ainvoke` 整段式。

### 3.2 具体改动点

1. **`create_react_agent` 中的 `call_model`（`graph.py`）**
   - 当前：`resp = await client.ainvoke(messages)`，一次拿整段。
   - 目标方案：
     - 优先尝试 `client.astream(messages)`（或 QwenLLM 暴露的流式接口）：
       - 在 `call_model` 内部累积 token，构造最终 `AIMessage` 放入状态。
       - 同时将 token 通过 LangGraph 的 `yield` 机制向外传递（已由 `agent.astream(..., stream_mode=['messages'])` 负责）。
     - 若 `astream` 不可用或抛异常，则回退到 `ainvoke`。

2. **QwenLLM 客户端封装（`llm_client.py`）**
   - 检查现有实现是否提供流式接口（如 `client.astream` 或 `client.stream`）。  
   - 如无，则在 Qwen SDK 封装一层 `astream(messages)`，用于上面的 `call_model`。

3. **保持 SSE 事件逻辑不变**
   - `chat.py` 中 `event_generator` 已对 `stream_mode="messages"` 做处理：  
     - 仅当 `meta.langgraph_node == "agent"` 时，将 `msg_chunk.content` 推成 `content` 事件。  
   - 修改只在 Agent 内部，SSE 层无需变更。

### 3.3 验收标准

- 对同一问题：
  - **改动前**：前端在一段时间后一次性收到整段文本。
  - **改动后**：前端能看到内容逐字（或逐句）出现；长回答中途可以提前看到首屏。

---

## 四、记忆窗口优化设计（最近 10 轮，第 5 条）

### 4.1 设计原则

1. 「轮」以 Turn 为单位：**一条用户消息 + 一条助手回复**。  
2. 对于同一 `session_id`：
   - 内存结构 `_TURN_SUMMARIES[session_id]` 只保留 **最近 10 条**；旧的在追加新摘要时丢弃。
   - 若走「无摘要回退」路径，则从 `_CHAT_HISTORY[session_id]` 中只取最近 10 轮构造预览。

### 4.2 具体改动点

1. **`_append_turn_summary`（`chat.py`）**
   - 当前：简单 `turns.append(summary)`。
   - 改为：
     - 追加后若 `len(turns) > 10`，`pop(0)` 或切片 `turns[-10:]` 保留最近 10 条。

2. **`_build_history_summary`（`chat.py`）**
   - 摘要路径：
     - `turn_summaries = _TURN_SUMMARIES.get(session_id) or []`  
     - **只取最后 10 条**：`turn_summaries[-10:]`。
   - 回退路径（直接看 `_CHAT_HISTORY`）：
     - 先从末尾反向扫描出最近 10 个 Turn（Human+AI），再生成预览，而不是从头到尾全量遍历。

3. **文档更新**
   - 在 `session-round-memory.md` 与 `runtime-flow.md` 中补充：  
     - 传给 LLM 的历史上下文为「最近 10 轮的摘要」，而不是整个会话。

### 4.3 验收标准

- 长会话（> 20 轮）下，`history_summary` 长度稳定在一个可控范围内（粗略检查字符数或 token 数）。  
- 行为上仍能正确记住最近对话的关键信息，对很久之前的内容可适当遗忘。

---

## 五、后续实施顺序建议

1. **第一步：记忆窗口（10 轮）**
   - 改动集中在 `chat.py`，风险小，容易回滚。
2. **第二步：流式输出**
   - 先在 QwenLLM 层确认/封装 `astream` 能力，再调整 `call_model`。  
   - 开启详细日志，对比流式前后响应时间与事件数量。

---

## 六、实现状态

| 项目 | 状态 | 说明 |
|------|------|------|
| 记忆窗口（10 轮） | ✅ 已实现 | `_append_turn_summary` 截断；`_build_history_summary` 只取最近 10 轮；加载时截断 |
| 流式输出 | ✅ 已实现 | `call_model` 改用 `client.astream`，失败回退 `ainvoke`；传入 config 支持 tracer |

