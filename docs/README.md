# 心像 EchoTwin 项目文档

心像 EchoTwin（原 DHA，Digital Human Agent）项目文档中心，**面向文档开发**：以文档为单一信息源，开发时优先查阅与更新文档。

---

## 文档导航

### 一、架构文档（理解系统）

| 文档 | 说明 |
|------|------|
| [架构概述](./architecture/overview.md) | 项目定位、前后端架构、Skill 与 MCP 设计 |
| [运行流程](./architecture/runtime-flow.md) | 请求完整流程（技能选择 → 执行 → 工具调用） |
| [步骤类型与工具](./architecture/step-types-and-tools.md) | MCP / script / service / export / 只读文件等执行路径（单聊已合并为统一会话） |
| [统一对话模型](./architecture/unified-conversation-model.md) | 单聊与群聊合并：带主持人的唯一会话类型、数据格式与 API |
| [Skill + MCP 设计](./architecture/skill-mcp-design-draft.md) | 两阶段技能选择与执行（已实现） |
| [LLM 提示词结构](./architecture/llm-prompt-structure.md) | 每次请求发给大模型的内容 |
| [会话与记忆设计](./architecture/session-round-memory.md) | 轮对话、Turn、摘要与记忆 |
| [流式处理](./architecture/streaming-and-memory-update.md) | ReAct 流式处理与记忆更新 |
| [API 设计](./architecture/api-design.md) | RESTful API 规范 |
| [项目结构](./architecture/project-structure.md) | 目录与代码组织 |
| [LLM 提供者切换](./architecture/llm-provider-switch.md) | 更换大模型（jeniya、OpenAI 兼容 API） |

### 二、功能文档（功能说明）

| 文档 | 说明 |
|------|------|
| [对话功能](./features/chat.md) | 对话交互、SSE 流式输出 |
| [Session 管理](./features/session-management.md) | 会话新建、列表、切换 |
| [记忆功能](./features/memory.md) | Agent 记忆管理 |
| [MCP 配置](./features/mcp-config.md) | MCP Server 配置与管理 |
| [Skills 配置](./features/skills-config.md) | Skills 配置与管理 |
| [多模型配置](./features/multi-model-config.md) | 多 LLM 模型配置 |
| [文件预览方案](./features/file-preview-research.md) | PDF/DOC/Excel 预览方案调研 |

### 三、开发文档（上手与配置）

| 文档 | 说明 |
|------|------|
| [项目依赖](./requirements.md) | 前后端依赖清单 |
| [开发设置](./development/setup.md) | 环境配置、安装、启动 |
| [MCP 操作指南](./development/mcp-operation-guide.md) | 从 MCP.so 搜选、远程接入、本地编写 |
| [部署](./development/deployment.md) | 生产环境部署 |
| [多 DHA 群聊方案](./development/multi-dha-group-chat-plan.md) | 群聊多 DHA 架构与规划 |

### 四、规划与历史

| 文档 | 说明 |
|------|------|
| [下一步计划](./next-plan/next-plan.md) | 待开发项与暂缓内容 |
| [群聊逻辑](./next-plan/group-chat-logic.md) | 群聊逻辑规划 |
| [前端 UI 改造](./next-plan/frontend-ui-reform.md) | 前端 UI 改造规划 |
| [演示场景](./demo/demo-scenarios.md) | 演示场景说明 |

---

## 面向文档开发

1. **开发前**：先查对应架构/功能文档，确认设计再动手
2. **开发中**：实现与文档不符时，以文档为准并更新代码，或发现文档过期时更新文档
3. **新增能力**：先写或更新文档，再实现

---

## 快速开始

1. [开发设置](./development/setup.md) 完成环境与启动
2. [架构概述](./architecture/overview.md) 理解整体设计
3. [运行流程](./architecture/runtime-flow.md) 理解请求链路

---

## 外部资源

- [MCP 官方文档](https://modelcontextprotocol.io)
- [Anthropic Agent Skills](https://agentskills.io)
- [LangChain 文档](https://python.langchain.com)
- [FastAPI 文档](https://fastapi.tiangolo.com)
- [Vue 3 文档](https://vuejs.org)
