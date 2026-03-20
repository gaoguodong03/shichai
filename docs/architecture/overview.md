# 架构概述

## 项目定位

拾柴·GatherFlame 是一个类似 **Gemini Chat / ChatGPT** 的 AI 聊天工具，对于每一个聊天工具都可以将其视为一个数字人智能体（Digital Human Agent，DHA），有自己的 skill 和 mcp，核心特点是**所有对话都支持 ReAct Agent 模式**，可以自动调用 MCP 工具和自定义 Skills。参考了 Manus 的设计思路。对于 MCP 的设计部分应该参考官方的 MCP 设计理念（[MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)）。

提供对话、Session 管理、MCP/Skills/模型配置等功能。

## 核心架构

### 前端层

**技术栈：Vue 3 + Vite**

采用前后端分离架构，前端作为独立应用通过 RESTful API 和 Server-Sent Events (SSE) 与 Python 后端通信。

#### 核心技术

- **框架**：Vue 3 (Composition API)
  - 使用 `<script setup>` 语法
  - Composition API 提供更好的逻辑复用和类型推导
- **构建工具**：Vite
  - 快速的开发服务器和热更新
  - 优化的生产构建
- **UI 组件库**：DaisyUI（Vue 版本）或 Element Plus
  - DaisyUI：基于 Tailwind CSS，轻量级
  - Element Plus：功能完整的企业级组件库
- **状态管理**：Pinia
  - Vue 官方推荐的状态管理库
  - 类型安全，支持 TypeScript
- **路由**：Vue Router
  - 单页应用路由管理
- **HTTP 客户端**：Axios 或 Fetch API
  - 用于 REST API 调用
- **SSE 流式处理**：EventSource API
  - 接收 Agent 的实时流式输出
- **图标库**：Iconify / Vue Icons
  - 丰富的图标选择

#### 前端架构特点

- **独立部署**：前端和后端可以独立部署，通过 CORS 配置跨域
- **API 通信**：通过 HTTP REST API 进行数据交互
- **流式响应**：使用 SSE (Server-Sent Events) 接收 Agent 的流式输出
- **实时更新**：SSE 用于实时状态更新和流式内容推送
- **类型安全**：使用 TypeScript 提供完整的类型检查

### 后端层（Python）

**技术栈：FastAPI**

#### Web 框架

- **FastAPI**
  - 原生支持异步，适合流式响应
  - 自动生成 API 文档（OpenAPI/Swagger）
  - 类型提示和验证（Pydantic）
  - 性能优秀，支持 SSE 和 WebSocket
  - 基于 Starlette 和 Pydantic，现代化设计

#### 核心优势

- **高性能**：基于 ASGI，支持异步处理
- **类型安全**：完整的 Python 类型提示支持
- **自动文档**：自动生成交互式 API 文档
- **流式支持**：原生支持 SSE 和 WebSocket
- **易于测试**：基于标准 Python 类型，易于编写测试

#### Agent 层（Python）

- **LangGraph**：Python 版本的 `langgraph` 实现 ReAct 循环
  - 使用 `langgraph` 构建 Agent 工作流
  - 支持状态管理和节点编排
- **LangChain**：Python 版本的 `langchain` 核心库
  - 提供 LLM 抽象接口
  - 工具调用和链式处理
- **MCP Python SDK**：使用官方 MCP Python SDK
  - 从 PyPI 安装：`pip install mcp`
  - 或从 GitHub 安装：`pip install git+https://github.com/modelcontextprotocol/python-sdk.git`
  - 直接使用 Python MCP SDK 连接 MCP Server
  - 支持 stdio、SSE、HTTP 等多种传输方式
  - 无需 JavaScript 适配器，原生 Python 集成
- **多模型支持**：通过 LangChain 的 LLM 接口支持多种模型
  - OpenAI（GPT-4, GPT-3.5 等）
  - Anthropic（Claude 系列）
  - 本地模型（通过 Ollama、vLLM 等）
  - 其他兼容 OpenAI API 的模型服务

#### API 设计

**RESTful API 端点**：
- `POST /api/chat`：发送消息，返回 SSE 流式响应
- `GET /api/sessions`：获取会话列表
- `POST /api/sessions`：创建新会话
- `DELETE /api/sessions/{id}`：删除会话
- `GET /api/settings/models`：获取模型配置
- `POST /api/settings/models`：更新模型配置
- `GET /api/settings/mcp`：获取 MCP Server 配置
- `POST /api/settings/mcp`：更新 MCP Server 配置
- `GET /api/settings/skills`：获取 Skills 配置
- `POST /api/settings/skills`：更新 Skills 配置

**流式响应格式（SSE）**：
```
event: react_step
data: {"type": "thought", "content": "..."}

event: react_step
data: {"type": "tool_call", "tool": "...", "args": {...}}

event: content
data: {"text": "..."}
```

### 数据层

- **Session 数据管理**：SQLite / PostgreSQL（根据规模选择）
- **记忆管理（Session 级别）**：内存缓存 + 持久化存储
- **配置管理**：JSON 文件或数据库存储（MCP/Skills/模型配置）

## Skills 与 MCP 的设计关系

### 核心定位

**Skills（技能）** 和 **MCP（Model Context Protocol）** 在架构中扮演不同但互补的角色：

#### Skills：策略层（"做什么"和"怎么做"）

- **定义**：基于 [Anthropic Agent Skills 标准](https://agentskills.io) 的文档化指令包
- **作用**：提供任务执行的策略指导，告诉 Agent 如何完成特定任务
- **形式**：Markdown 文档（SKILL.md），包含：
  - 分步指令
  - 输入输出示例
  - 常见边界情况处理
  - 可选的脚本、参考文档和资源
- **特点**：
  - 渐进式披露加载（元数据 → 指令 → 资源）
  - 可组合使用多个技能
  - 支持本地目录和远程 URL

#### MCP：执行层（"执行能力"）

- **定义**：Model Context Protocol 标准协议，提供标准化的工具接口
- **作用**：提供可执行的工具函数，Agent 可以直接调用执行具体操作
- **形式**：MCP Server 暴露的工具（Tools）、资源（Resources）、提示（Prompts）
- **特点**：
  - 标准化的工具接口
  - 支持多个 MCP Server 同时运行
  - 通过 Python MCP SDK 直接集成到 LangChain 工具系统

### 协作关系

**只有一个 Agent（ReAct 循环）**，不存在 Agent 调用 Agent。Skill 的每一步由 Agent 解释执行，**步骤中如需要再调用 MCP**。

```
                    ┌─────────────────────────────────────┐
                    │    技能执行 Agent (ReAct 循环)        │
                    │  • 系统提示词中注入选中 Skill 的完整指令 │
                    │  • 按当前 Skill 的「步骤」逐步执行      │
                    └─────────────────┬───────────────────┘
                                      │
         ┌────────────────────────────┼────────────────────────────┐
         │                            │                            │
         ▼                            ▼                            ▼
   ┌───────────┐               ┌───────────────┐               ┌───────────┐
   │ Step 1    │               │ Step 2        │               │ Step N    │
   │ 理解需求   │  ── 下一步 ──▶ │ 搜索/抓取     │  ── 下一步 ──▶ │ 交付结果   │
   │ (纯推理)   │               │ 若需要则调用  │               │ (纯推理)   │
   └───────────┘               │ MCP Tool      │               └───────────┘
                               └───────┬───────┘
                                       │
                                       ▼
                               ┌───────────────┐
                               │   MCP Tools   │
                               │ (执行能力)     │
                               │ • 搜索/抓取等  │
                               └───────────────┘
```

**工作流程**（两阶段设计）：

1. **第一次调用：技能选择**：根据用户意图，LLM 仅依据各 Skill 的 name+description 选定一个 Skill；**不注入完整 skill 内容**，避免 token 过多。
2. **第二次调用：技能执行**：将选中 Skill 的完整指令（SKILL.md）注入到技能执行 Agent 的系统提示词；Agent 按该 Skill 描述的步骤顺序执行；每一步可以是纯推理，也可以**在这一步里决定调用 MCP 工具**。
3. **步骤内调用 MCP**：当某一步需要「执行能力」时（例如「使用 web_fetch 抓取」「使用 exa 搜索」），Agent 输出 tool_call，ReAct 的 Tool 节点执行对应 MCP 工具，结果返回给**同一个** Agent，再继续下一步。
4. **无 Agent 调 Agent**：技能选择与技能执行都是直接调用 LLM；技能执行阶段只有一个 ReAct 循环。

**示例场景**：

- **Skill**：wechat-article-writer 规定步骤为「理解需求 → 搜索补充 → 规划结构 → 撰写正文 → …」。
- **执行**：Agent 执行「搜索补充」这一步时，根据需要调用 MCP 的 `exa_web_search_exa` 或 `fetch_fetch`；执行「撰写正文」时通常不再调工具，直接生成文本。
- **协作**：Skill 规定「做什么、按什么顺序做」；MCP 在**某一步需要时**提供「怎么做」的执行能力。

### 设计原则

1. **职责分离**：
   - Skills 专注于"知识"和"策略"
   - MCP 专注于"能力"和"执行"

2. **松耦合**：
   - Skills 不直接依赖特定的 MCP Server
   - 通过工具名称或 `allowed-tools` 字段声明可用的工具

3. **可组合性**：
   - 多个 Skills 可以组合使用
   - 多个 MCP Server 的工具可以同时可用
   - Agent 根据上下文智能选择技能和工具

4. **渐进式增强**：
   - 基础能力由 MCP 工具提供
   - 高级策略由 Skills 提供
   - 两者结合实现复杂任务

## 相关文档

- [运行流程](./runtime-flow.md) - 两阶段流程详解
- [Skill + MCP 设计](./skill-mcp-design-draft.md) - 两阶段设计说明
- [流式处理架构](./streaming-and-memory-update.md) - ReAct 流式处理与记忆更新
- [API 设计文档](./api-design.md) - RESTful API 设计规范
- [项目结构文档](./project-structure.md) - 项目目录结构说明
