# 对话功能

## 概述

对话功能是应用的核心功能，提供类似 **Gemini Chat / ChatGPT** 的对话交互体验。与传统的 AI 聊天工具不同，**所有对话都基于 ReAct Agent 模式**，这意味着 AI 可以自动调用 MCP 工具和自定义 Skills 来完成复杂任务。

参考了 **Manus** 的设计思路，将 Agent 能力无缝集成到对话体验中。

## 核心特性

### 对话体验
- **类似 ChatGPT/Gemini 的界面**: 简洁的对话界面，消息气泡式布局
- **实时对话交互**: 支持多轮对话，保持上下文
- **流式响应**: 实时显示 AI 回复，提升用户体验
- **消息历史**: 完整的对话历史记录

### ReAct Agent 能力
- **自动工具调用**: AI 可以根据对话内容自动决定是否需要调用工具
- **MCP 工具集成**: 自动使用已配置的 MCP Server 工具
- **Skills 扩展**: 支持使用自定义 Skills 增强能力
- **透明化展示**: 显示 AI 的思考过程（Thought）和工具调用过程

## 实现要点

### 技术架构
- **LangGraph (Python)**: 使用 Python 版本的 LangGraph 实现 ReAct 循环
  - Thought -> Tool Call -> Observation -> Thought
- **MCP Python SDK**: 直接使用 Python MCP SDK 连接 MCP Server
- **FastAPI SSE**: 使用 FastAPI 的 Server-Sent Events 实现流式输出
- **流式输出**: 支持流式输出 Thought、Tool Call 和最终回复

### 工作流程（两阶段）

1. **第一次调用**：技能选择。AI 根据用户消息和各 Skill 的 name+description 选定一个 Skill。
2. **第二次调用**：技能执行。AI 按选中 Skill 的步骤进入 ReAct 循环：
   - **Thought**: AI 思考需要做什么
   - **Tool Call**: 如果需要，调用相关工具（MCP 工具或 Skills）
   - **Observation**: 获取工具执行结果
   - **Thought**: 基于结果继续思考
   - 重复直到得出最终答案
3. 流式输出最终回复给用户

详见 [运行流程](../architecture/runtime-flow.md) 和 [Skill + MCP 设计](../architecture/skill-mcp-design-draft.md)。

### 工具调用展示
- 在对话中显示工具调用过程（可选，可折叠）
- 显示工具名称、参数、执行结果
- 用户可以看到 AI 的推理过程

## 与 ChatGPT/Gemini 的区别

| 特性 | ChatGPT/Gemini | 本项目 |
|------|---------------|--------|
| 对话模式 | 纯文本对话 | ReAct Agent 模式 |
| 工具调用 | 需要手动触发或特定模式 | 自动智能调用 |
| 能力扩展 | 有限 | 通过 MCP 和 Skills 无限扩展 |
| 推理过程 | 不透明 | 可选的透明化展示 |
| 后端技术 | 专有服务 | Python + FastAPI，开源可定制 |

## 实现细节

### 前端实现

使用 Vue 3 + EventSource API 接收 SSE 流：

```vue
<script setup lang="ts">
import { useEventSource } from '@/composables/useEventSource'

const { eventSource } = useEventSource('/api/chat/stream', {
  message: 'Hello',
  session_id: 'session-123'
})

eventSource.addEventListener('react_step', (event) => {
  const step = JSON.parse(event.data)
  // 处理 ReAct 步骤
})
</script>
```

### 后端实现

使用 FastAPI 和 LangGraph 实现流式处理：

```python
@router.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    graph = create_react_graph(session_id=request.session_id)
    return await stream_handler.create_sse_stream(graph, initial_state)
```

## 参考资源

- [流式与记忆](../architecture/streaming-and-memory-update.md)
- [API 设计文档](../architecture/api-design.md)
