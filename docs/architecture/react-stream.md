# ReAct Stream 架构文档

## 概述

ReAct workflow 的流式处理是本项目的核心功能。本文档描述了基于 Python 后端的流式处理架构设计，使用 FastAPI 和 LangGraph 实现，通过 Server-Sent Events (SSE) 向前端推送实时数据。

## 架构层次

### 1. 类型定义层 (`app/agent/types.py`)

定义所有 ReAct 工作流相关的类型：

- `ReActStepType`: 步骤类型枚举（thought, tool_call, observation, final_answer）
- `ToolCallInfo`: 工具调用信息（工具名、参数、结果）
- `ReActStep`: ReAct 工作流步骤（类型、内容、时间戳）
- `StreamEvent`: 流式事件（react_step 或 content）

```python
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime

class ReActStepType(str, Enum):
    THOUGHT = "thought"
    TOOL_CALL = "tool_call"
    OBSERVATION = "observation"
    FINAL_ANSWER = "final_answer"

class ToolCallInfo(BaseModel):
    tool_name: str
    arguments: Dict[str, Any]
    result: Optional[Any] = None
    error: Optional[str] = None

class ReActStep(BaseModel):
    type: ReActStepType
    content: str
    tool_call: Optional[ToolCallInfo] = None
    timestamp: datetime

class StreamEvent(BaseModel):
    event_type: str  # "react_step" 或 "content"
    data: ReActStep | Dict[str, Any]
```

### 2. 事件处理层 (`app/agent/event_processor.py`)

负责将 LangGraph 的原始事件转换为 ReAct 步骤：

- `ToolArgsParser`: 工具参数解析器（处理嵌套 JSON 字符串）
- `MessageContentExtractor`: 消息内容提取器
- `LangGraphEventProcessor`: LangGraph 事件处理器
  - `process_chain_start()`: 处理节点开始事件
  - `process_chain_end()`: 处理节点结束事件
  - `process_llm_stream()`: 处理 LLM 流式内容
  - `process_tool_call()`: 处理工具调用事件

```python
from langgraph.graph import Graph
from typing import AsyncIterator, Dict, Any
from app.agent.types import ReActStep, StreamEvent

class LangGraphEventProcessor:
    def __init__(self):
        self.tool_args_parser = ToolArgsParser()
        self.content_extractor = MessageContentExtractor()
    
    async def process_stream_events(
        self, 
        graph: Graph, 
        initial_state: Dict[str, Any]
    ) -> AsyncIterator[StreamEvent]:
        """处理 LangGraph 流式事件并转换为 StreamEvent"""
        async for event in graph.astream_events(initial_state, version="v2"):
            # 处理不同类型的事件
            if event["event"] == "on_chain_start":
                yield await self.process_chain_start(event)
            elif event["event"] == "on_chain_end":
                yield await self.process_chain_end(event)
            elif event["event"] == "on_llm_stream":
                yield await self.process_llm_stream(event)
            # ... 其他事件类型
```

### 3. 流式处理层 (`app/agent/stream_handler.py`)

负责将事件处理器的输出转换为 SSE 流式响应：

- `ReActStreamHandler`: 流式处理器
  - `process_stream()`: 处理 LangGraph 流式事件
  - `format_sse()`: 格式化 SSE 事件
  - `create_sse_stream()`: 创建 SSE 响应流

```python
from fastapi.responses import StreamingResponse
from app.agent.event_processor import LangGraphEventProcessor
from app.agent.types import StreamEvent
import json

class ReActStreamHandler:
    def __init__(self, enable_debug_logs: bool = False):
        self.processor = LangGraphEventProcessor()
        self.enable_debug_logs = enable_debug_logs
    
    async def create_sse_stream(
        self, 
        graph: Graph, 
        initial_state: Dict[str, Any]
    ) -> StreamingResponse:
        """创建 SSE 流式响应"""
        async def event_generator():
            async for event in self.processor.process_stream_events(graph, initial_state):
                yield self.format_sse(event)
        
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )
    
    def format_sse(self, event: StreamEvent) -> str:
        """格式化 SSE 事件"""
        event_type = event.event_type
        data = json.dumps(event.data.dict(), ensure_ascii=False)
        return f"event: {event_type}\ndata: {data}\n\n"
```

### 4. API 路由层 (`app/api/chat.py`)

FastAPI 路由，使用流式处理器：

```python
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.agent.stream_handler import ReActStreamHandler
from app.agent.graph import create_react_graph

router = APIRouter(prefix="/api/chat", tags=["chat"])
stream_handler = ReActStreamHandler(
    enable_debug_logs=os.getenv("DEBUG", "false") == "true"
)

class ChatRequest(BaseModel):
    message: str
    session_id: str
    model: Optional[str] = None

@router.post("/stream")
async def chat_stream(request: ChatRequest):
    """发送消息，返回 SSE 流式响应"""
    try:
        # 创建 Agent Graph
        graph = create_react_graph(
            session_id=request.session_id,
            model=request.model
        )
        
        # 构建初始状态
        initial_state = {
            "messages": [{"role": "user", "content": request.message}],
            "session_id": request.session_id
        }
        
        # 创建并返回 SSE 流
        return await stream_handler.create_sse_stream(graph, initial_state)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

## 数据流

```
用户请求
    ↓
FastAPI Router (/api/chat/stream)
    ↓
ReActStreamHandler.create_sse_stream()
    ↓
LangGraphEventProcessor.process_stream_events()
    ↓
LangGraph Agent (astream_events)
    ↓
事件转换 (ReActStep)
    ↓
SSE 格式化
    ↓
StreamingResponse
    ↓
前端 (EventSource API)
```

## 前端集成

### Vue 3 组件示例

```vue
<template>
  <div class="chat-container">
    <div v-for="step in reactSteps" :key="step.id">
      <ReActStepDisplay :step="step" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useEventSource } from '@/composables/useEventSource'

const reactSteps = ref<ReActStep[]>([])

const { eventSource, close } = useEventSource('/api/chat/stream', {
  message: 'Hello, how can you help me?',
  session_id: 'session-123'
})

eventSource.addEventListener('react_step', (event) => {
  const step = JSON.parse(event.data)
  reactSteps.value.push(step)
})

eventSource.addEventListener('content', (event) => {
  const content = JSON.parse(event.data)
  // 更新内容显示
})

onUnmounted(() => {
  close()
})
</script>
```

## 设计原则

1. **单一职责**: 每个类/函数只负责一个功能
2. **易于测试**: 每个组件都可以独立测试
3. **易于扩展**: 新增事件类型只需扩展 `EventProcessor`
4. **类型安全**: 使用 Python 类型提示和 Pydantic 验证
5. **错误处理**: 统一的错误处理机制，通过 SSE 发送错误事件

## 扩展指南

### 添加新的事件类型

1. 在 `types.py` 中添加新的 `ReActStepType`
2. 在 `event_processor.py` 中添加处理逻辑
3. 在 `stream_handler.py` 中确保新事件被正确处理

### 修改事件处理逻辑

只需修改 `LangGraphEventProcessor` 中的相应方法，不影响其他层。

### 添加新的流式格式

扩展 `StreamEvent` 类型，并在 `stream_handler.py` 中添加格式化逻辑。

## 最佳实践

1. **参数解析**: 使用 `ToolArgsParser` 统一处理工具参数
2. **内容提取**: 使用 `MessageContentExtractor` 统一提取消息内容
3. **错误处理**: 在流式处理中通过 SSE 发送错误事件
4. **调试日志**: 使用 `enable_debug_logs` 配置控制日志输出
5. **连接管理**: 正确处理客户端断开连接，清理资源
6. **性能优化**: 使用异步生成器，避免阻塞主线程

## 测试建议

1. **单元测试**: 测试 `EventProcessor` 的各个方法
2. **集成测试**: 测试完整的流式处理流程
3. **端到端测试**: 测试前端接收和显示流式数据
4. **压力测试**: 测试并发 SSE 连接的性能

## 注意事项

- **SSE 超时**: 配置适当的超时时间，避免长时间连接
- **错误恢复**: 实现客户端自动重连机制
- **资源清理**: 确保在连接断开时正确清理 LangGraph 状态
- **CORS 配置**: 确保前端可以访问 SSE 端点