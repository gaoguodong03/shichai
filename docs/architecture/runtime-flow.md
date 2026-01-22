# 运行流程文档

本文档详细描述了 DHA (Digital Human Agent) 系统的完整运行流程，包括系统启动、请求处理、ReAct Agent 工作流、工具调用和流式输出等各个环节。

## 目录

- [系统启动流程](#系统启动流程)
- [用户请求处理流程](#用户请求处理流程)
- [ReAct Agent 工作流程](#react-agent-工作流程)
- [MCP 工具调用流程](#mcp-工具调用流程)
- [Skills 加载和使用流程](#skills-加载和使用流程)
- [流式输出流程](#流式输出流程)
- [错误处理流程](#错误处理流程)

## 系统启动流程

### 1. 后端服务启动

```
启动命令: python -m app.main 或 uvicorn app.main:app --reload
```

**步骤详解：**

1. **加载环境变量**
   - 从 `.env` 文件加载配置
   - 包括 Qwen API Key、CORS 设置、MCP 配置路径等

2. **初始化 FastAPI 应用**
   - 创建 FastAPI 实例
   - 配置 CORS 中间件
   - 注册路由（`/api/chat`, `/api/settings`）

3. **启动 HTTP 服务器**
   - 监听 `0.0.0.0:8000`
   - 等待客户端连接

### 2. 延迟初始化（Lazy Initialization）

系统采用延迟初始化策略，在第一次请求时才初始化 MCP 和 Skills：

```python
# 全局管理器实例
mcp_manager = MCPToolManager()
skills_loader = SkillsLoader()
initialized = False

async def ensure_initialized():
    if not initialized:
        # 初始化 MCP Servers
        await mcp_manager.initialize_all()
        # 加载 Skills
        skills_loader.load_all_skills()
        initialized = True
```

**初始化步骤：**

1. **MCP Manager 初始化**
   - 加载 `config/mcp_servers.json` 配置文件
   - 遍历所有启用的 MCP Server
   - 建立 stdio 连接
   - 调用 `list_tools()` 获取工具列表
   - 将 MCP 工具转换为 LangChain Tool

2. **Skills Loader 初始化**
   - 扫描 `skills/` 目录
   - 读取每个 Skill 的 `SKILL.md` 文件
   - 解析 YAML frontmatter
   - 提取技能名称、描述和指令内容

## 用户请求处理流程

### 请求入口

```
POST /api/chat/stream
Content-Type: application/json

{
    "message": "现在几点了？",
    "session_id": "default"
}
```

### 处理步骤

1. **接收请求**
   - FastAPI 路由接收 POST 请求
   - 验证请求体（Pydantic 模型）
   - 解析 `message` 和 `session_id`

2. **确保初始化**
   - 调用 `ensure_initialized()`
   - 如果未初始化，执行初始化流程

3. **获取工具和技能**
   ```python
   tools = mcp_manager.get_tools()  # 获取所有 MCP 工具
   skills_instruction = skills_loader.get_active_skills_instructions()  # 获取技能指令
   ```

4. **创建 Agent**
   ```python
   llm = QwenLLM()  # 创建 LLM 客户端
   agent = create_react_agent(llm, tools, skills_instruction)  # 创建 ReAct Agent
   ```

5. **准备初始状态**
   ```python
   initial_state = {
       "messages": [HumanMessage(content=request.message)],
       "tools": tools
   }
   ```

6. **启动流式响应**
   - 创建 `StreamingResponse`
   - 使用 Server-Sent Events (SSE) 格式
   - 开始流式执行 Agent 工作流

## ReAct Agent 工作流程

### 工作流图

```
┌─────────────┐
│   Entry     │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Agent     │  ← LLM 思考和决策
│   Node      │
└──────┬──────┘
       │
       ├─── should_continue() ───┐
       │                          │
       │                          ▼
       │                    ┌─────────────┐
       │                    │  call_tool  │  ← 需要工具？
       │                    │     end     │
       │                    └─────────────┘
       │                          │
       │                          ▼
       │                    ┌─────────────┐
       │                    │    Tool     │  ← 执行工具
       │                    │    Node     │
       │                    └──────┬──────┘
       │                           │
       │                           │ (工具结果)
       │                           │
       └───────────────────────────┘
                    │
                    ▼
              ┌─────────────┐
              │     END     │
              └─────────────┘
```

### 详细流程

#### 1. Agent 节点（call_model）

**功能：** LLM 思考和决策

**执行步骤：**

1. 获取当前消息列表
2. 添加系统提示词（包含工具列表和技能指令）
3. 调用 LLM（`llm.get_client().ainvoke(messages)`）
4. 获取 LLM 响应（AIMessage）
5. 更新状态：`{"messages": messages + [response]}`
 
**系统提示词结构：**

```
你是一个有用的 AI 助手，可以使用工具来帮助用户。

你可以使用以下工具：
- time_get_time: 获取当前时间
- calculator_calculate: 执行数学计算
...

当你需要使用工具时，请按照以下格式回复：
```json
{
    "action": "tool_call",
    "tool": "tool_name",
    "arguments": {...}
}
```

## 可用技能
[Skills 指令内容]
```

#### 2. 条件判断（should_continue）

**功能：** 判断是否需要调用工具

**判断逻辑：**

1. 检查最后一条消息是否为 AIMessage
2. 检查消息内容是否包含 "tool_call"
3. 尝试解析 JSON 格式的工具调用
4. 如果解析成功且 `action == "tool_call"`，返回 `"call_tool"`
5. 否则返回 `"end"`

**代码示例：**

```python
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    
    if isinstance(last_message, AIMessage):
        content = last_message.content
        if isinstance(content, str) and "tool_call" in content.lower():
            # 解析 JSON
            tool_call = json.loads(json_str)
            if tool_call.get("action") == "tool_call":
                return "call_tool"
    
    return "end"
```

#### 3. Tool 节点（call_tool）

**功能：** 执行工具调用

**执行步骤：**

1. 从 Agent 节点的响应中提取工具调用信息
2. 解析 JSON：`{"action": "tool_call", "tool": "time_get_time", "arguments": {}}`
3. 根据工具名称查找对应的 LangChain Tool
4. 执行工具：
   - 异步工具：`await tool.arun(**arguments)`
   - 同步工具：`await asyncio.to_thread(tool.run, **arguments)`
5. 将工具结果封装为 HumanMessage
6. 更新状态：`{"messages": [HumanMessage(content=f"工具执行结果: {result}")]}`

**工具执行示例：**

```python
# 工具调用
tool_name = "time_get_time"
arguments = {}

# 查找工具
tool = find_tool_by_name(tool_name)

# 执行工具
if hasattr(tool, 'arun'):
    result = await tool.arun(**arguments)
else:
    result = await asyncio.to_thread(tool.run, **arguments)

# 返回结果
return {
    "messages": [
        HumanMessage(content=f"工具 {tool_name} 的执行结果: {result}")
    ]
}
```

#### 4. 循环执行

**流程：**

1. Tool 节点执行完成后，自动返回到 Agent 节点
2. Agent 节点接收工具结果，再次调用 LLM
3. LLM 基于工具结果生成最终回复
4. 如果不再需要工具，流程结束

**示例循环：**

```
用户: "现在几点了？"
  ↓
Agent: 思考 → 决定调用 time_get_time 工具
  ↓
Tool: 执行工具 → 返回 "当前时间: 2024-01-01 12:00:00"
  ↓
Agent: 基于工具结果 → 生成回复 "现在是 2024年1月1日 12点整"
  ↓
END: 返回最终回复
```

## MCP 工具调用流程

### MCP Server 连接流程

```
1. 读取配置
   └─> config/mcp_servers.json
   
2. 遍历启用的 Server
   └─> enabled: true
   
3. 建立连接
   └─> stdio_client(StdioServerParameters)
   
4. 初始化 Session
   └─> await session.initialize()
   
5. 获取工具列表
   └─> await session.list_tools()
   
6. 转换工具
   └─> MCP Tool → LangChain Tool
```

### 工具调用流程

```
Agent 决定调用工具
  ↓
解析工具名称: "time_get_time"
  ↓
查找 LangChain Tool
  ↓
调用 tool.arun() 或 tool.run()
  ↓
内部调用 MCP Session
  └─> await session.call_tool("get_time", {})
  ↓
MCP Server 执行
  └─> Python 函数执行
  └─> 返回结果
  ↓
结果转换
  └─> MCP Result → LangChain Result
  ↓
返回给 Agent
```

### 工具名称映射

**MCP Server 配置：**

```json
{
  "id": "time",
  "name": "时间 Server",
  "transport": {
    "type": "stdio",
    "command": "python",
    "args": ["example_time.py"]
  }
}
```

**工具注册：**

- MCP Server 中的工具名：`get_time`
- 注册到 LangChain 的工具名：`time_get_time`（添加 server_id 前缀避免冲突）

**调用过程：**

```python
# Agent 调用
tool_name = "time_get_time"

# 查找工具
tool = find_tool(tool_name)  # 找到 LangChain Tool

# 执行工具
result = await tool.arun()

# 内部执行
# 1. 提取原始工具名: "get_time"
# 2. 调用 MCP Session: await session.call_tool("get_time", {})
# 3. MCP Server 执行 Python 函数
# 4. 返回结果
```

## Skills 加载和使用流程

### Skills 加载流程

```
1. 扫描目录
   └─> skills/
   
2. 遍历子目录
   └─> example-skill/
   
3. 读取 SKILL.md
   └─> 解析 YAML frontmatter
   └─> 提取 body 内容
   
4. 创建 Skill 对象
   └─> name, description, content, metadata
   
5. 存储到字典
   └─> skills[name] = Skill(...)
```

### Skills 使用流程

```
1. 获取所有激活的 Skills
   └─> skills_loader.get_active_skills_instructions()
   
2. 合并技能指令
   └─> 格式: "## skill_name\n{description}\n\n{content}"
   
3. 添加到系统提示词
   └─> system_prompt += "\n## 可用技能\n{skills_instruction}\n"
   
4. LLM 接收技能指令
   └─> 在决策时参考技能指导
   
5. 根据技能执行任务
   └─> 可能调用相关工具
```

### Skills 示例

**SKILL.md 文件：**

```markdown
---
name: data-analysis
description: 数据分析技能
---

## 数据分析流程

1. 收集数据
2. 清理数据
3. 分析数据
4. 生成报告
```

**系统提示词中的体现：**

```
## 可用技能

## data-analysis
数据分析技能

## 数据分析流程

1. 收集数据
2. 清理数据
3. 分析数据
4. 生成报告
```

## 流式输出流程

### SSE 事件格式

系统使用 Server-Sent Events (SSE) 进行流式输出：

```
event: start
data: {"type": "start"}

event: react_step
data: {"type": "thought", "content": "用户询问时间，我需要调用工具..."}

event: react_step
data: {"type": "tool_result", "content": "工具 time_get_time 的执行结果: 当前时间: 2024-01-01 12:00:00"}

event: content
data: {"text": "现在是"}

event: content
data: {"text": "2024年1月1日"}

event: content
data: {"text": "12点整"}

event: end
data: {"type": "end"}
```

### 事件类型

1. **start** - 开始事件
   - 工作流开始执行时发送

2. **react_step** - ReAct 步骤事件
   - `type: "thought"` - LLM 思考过程（包含工具调用 JSON）
   - `type: "tool_result"` - 工具执行结果

3. **content** - 内容事件
   - LLM 生成的文本内容（流式输出）

4. **end** - 结束事件
   - 工作流执行完成

5. **error** - 错误事件
   - 执行过程中发生错误

### 流式执行流程

```python
async def event_generator():
    # 1. 发送开始事件
    yield f"event: start\ndata: {json.dumps({'type': 'start'})}\n\n"
    
    # 2. 流式执行 Agent 工作流
    async for event in agent.astream(initial_state):
        for node_name, messages in event.items():
            if node_name == "agent":
                # Agent 节点：LLM 响应
                for message in messages:
                    if isinstance(message, AIMessage):
                        content = message.content
                        if "tool_call" in content:
                            # 发送思考步骤
                            yield f"event: react_step\ndata: ...\n\n"
                        else:
                            # 发送内容
                            yield f"event: content\ndata: ...\n\n"
            
            elif node_name == "tool":
                # Tool 节点：工具结果
                for message in messages:
                    yield f"event: react_step\ndata: ...\n\n"
    
    # 3. 发送结束事件
    yield f"event: end\ndata: {json.dumps({'type': 'end'})}\n\n"
```

### 前端接收流程

```javascript
const eventSource = new EventSource('/api/chat/stream');

eventSource.addEventListener('start', (e) => {
    // 开始处理
});

eventSource.addEventListener('react_step', (e) => {
    const data = JSON.parse(e.data);
    if (data.type === 'thought') {
        // 显示思考过程
    } else if (data.type === 'tool_result') {
        // 显示工具结果
    }
});

eventSource.addEventListener('content', (e) => {
    const data = JSON.parse(e.data);
    // 流式显示文本内容
    appendText(data.text);
});

eventSource.addEventListener('end', (e) => {
    // 结束处理
    eventSource.close();
});
```

## 错误处理流程

### 错误类型

1. **初始化错误**
   - MCP Server 连接失败
   - Skills 加载失败
   - 处理：记录警告，继续运行（部分功能可能不可用）

2. **工具调用错误**
   - 工具不存在
   - 工具执行失败
   - 处理：返回错误消息给 Agent，Agent 可以重试或报告错误

3. **LLM 调用错误**
   - API 调用失败
   - 超时
   - 处理：返回错误事件给前端

4. **JSON 解析错误**
   - 工具调用 JSON 格式错误
   - 处理：返回解析错误消息

### 错误处理示例

```python
try:
    # 执行工具
    result = await tool.arun(**arguments)
except Exception as e:
    # 返回错误消息
    return {
        "messages": [
            HumanMessage(content=f"工具调用错误: {str(e)}")
        ]
    }
```

```python
try:
    async for event in agent.astream(initial_state):
        # 处理事件
        ...
except Exception as e:
    # 发送错误事件
    yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
```

## 完整流程示例

### 示例：用户询问时间

```
1. 用户发送请求
   POST /api/chat/stream
   {"message": "现在几点了？"}

2. 系统初始化（如果未初始化）
   - 加载 MCP Servers
   - 连接 time Server
   - 加载工具: time_get_time
   - 加载 Skills

3. 创建 Agent
   - 构建系统提示词（包含工具和技能）
   - 创建 LangGraph 工作流

4. 启动工作流
   └─> Agent 节点
       └─> LLM 思考
       └─> 决定调用 time_get_time
       └─> 生成工具调用 JSON

5. 条件判断
   └─> 检测到工具调用
   └─> 路由到 Tool 节点

6. Tool 节点
   └─> 解析工具调用
   └─> 查找工具: time_get_time
   └─> 调用 MCP Session
   └─> MCP Server 执行 get_time()
   └─> 返回: "当前时间: 2024-01-01 12:00:00"

7. 返回 Agent 节点
   └─> 接收工具结果
   └─> LLM 生成最终回复
   └─> "现在是 2024年1月1日 12点整"

8. 条件判断
   └─> 无工具调用
   └─> 结束工作流

9. 流式输出
   - event: start
   - event: react_step (思考)
   - event: react_step (工具结果)
   - event: content ("现在是")
   - event: content ("2024年1月1日")
   - event: content ("12点整")
   - event: end
```

## 性能优化

### 1. 延迟初始化
- 只在第一次请求时初始化
- 避免启动时的长时间等待

### 2. 连接复用
- MCP Server 连接保持打开
- 工具调用复用同一连接

### 3. 异步执行
- 所有 I/O 操作使用异步
- 支持并发请求处理

### 4. 流式输出
- 实时返回结果
- 减少用户等待时间

## 总结

DHA 系统采用 ReAct Agent 模式，通过 LangGraph 实现完整的工作流：

1. **系统启动**：延迟初始化，按需加载资源
2. **请求处理**：接收请求 → 初始化 → 创建 Agent → 执行工作流
3. **ReAct 循环**：Agent 思考 → 工具调用 → 结果处理 → 生成回复
4. **工具集成**：MCP Server → LangChain Tool → Agent 调用
5. **技能指导**：Skills 指令注入系统提示词
6. **流式输出**：SSE 实时推送执行过程和结果

整个系统设计注重可扩展性、可维护性和用户体验。
