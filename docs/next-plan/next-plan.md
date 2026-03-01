# 下一步开发计划

本文档记录待开发项与后续规划。

---

## 一、登录与认证（后续）

当前登录为**文本文件账密校验**（`config/auth_users.txt`），以下为后续可做项：

- **接入数据库**：将用户与密码存储迁入数据库（如 SQLite/PostgreSQL），支持注册信息、密码加密存储与找回等。
- **管理员与用户权限区分**：区分管理员与普通用户，不同权限可做不同能力（例如：仅管理员可配置 MCP/Skills、应用设置、用户管理；普通用户仅使用 Chat、个人会话与导出等）。
- Skill creator 以及群聊中的 skillcreator
- 领域报告 Skill + MCP
- MCP 沙箱方向
---

## 二、其他待开发项

### 已完成（本次开发）

- **多模型支持**：在应用设置与 LLM 客户端中增加 Gemini、Claude、GLM、Qwen、DeepSeek、Kimi 的默认配置（沿用 jeniya 基址与 API Key，模型名参考 https://jeniya.top/pricing）。设置加载时会合并默认 provider，保证新模型可用。
- **设置部分**：前端「应用设置」已分为「模型选择」「系统提示词」两个区块展示。
- **DHA 可选大模型**：DHA 实例增加 `llm_provider_id` 字段；编辑 DHA 时可选择该 DHA 使用的大模型，空则使用应用默认。群聊中每个 DHA 发言时按各自配置的 LLM 调用。
- **群聊 DHA 头像**：群聊消息中每个 DHA 使用名称首字作为圆形头像，并按 dha_id 哈希配色。
- **两种 Group 发言模式**：
  - **auto**：由主持人/调度决定下一发言人，逻辑不变。
  - **manual**：创建 Group 时可选「手动」；每次用户发言前必须选择「下一发言人」，仅该 DHA 回答一次后结束，等待用户再次提问；已修复「该 DHA 回答后控制权回到主持人」的 bug（manual 下不再调用主持人，直接结束本轮）。
- **Group 用户发言选择文件插入**：群聊输入区增加「插入文件」按钮，点击后列出 `/api/files` 下的文件，选择后向输入框插入 `【文件引用：path】`。
- **Group 重命名**：后端 `PUT /api/group-sessions/{id}` 支持 `title`、`speak_mode` 更新；前端 Group 列表项增加重命名按钮，弹窗输入新标题后调用接口并刷新。
- **Group 输入区与交互**：文件插入改为与 Chat 同款弹窗（目录浏览、上一级、刷新）；发言人选择与「自动」开关移至输入框下方；自动开启时下一发言人下拉禁用（变灰）；Group 无 Skill 选择。
- **Group 列表 bug 与默认**：修复「点击新建后再点已有 Group 无法跳转」——点击列表项时同时关闭新建表单；进入 Group 且列表有数据时，默认选中并打开第一个 Group。
- **Chat 每轮对话的上下文记忆（核查）**：见下方「Chat 上下文记忆说明」。

### Chat 上下文记忆说明（核查结果）

- **存储**：`_CHAT_HISTORY[session_id]` 存该会话的完整消息列表（HumanMessage / AIMessage）；`_TURN_SUMMARIES[session_id]` 存每轮结束后的 LLM 摘要（仅保留最近 10 轮，`_HISTORY_WINDOW_TURNS = 10`）。
- **每轮传给模型的内容**：`_build_history_summary(session_id, history)` 生成「历史摘要」字符串：
  - **优先**：若存在 `_TURN_SUMMARIES`，取最近 10 轮摘要，格式为「第 N 轮：摘要文本」；总长超过 `_HISTORY_SUMMARY_MAX_TOTAL_CHARS`（3200）时从最早轮开始丢弃。
  - **回退**：无 Turn 摘要时，按原始 history 的 Human+AI 对，取最近 10 轮，每轮截断为「用户：前 200 字」「助手：前 200 字」的预览。
- **请求时**：`user_content = "历史对话摘要：\n" + history_summary + "\n\n当前用户输入：\n" + request.message`，整段作为**一条** HumanMessage 传给 Agent；即模型每轮只收到「历史摘要 + 当前输入」，不直接收到完整消息列表。
- **轮次摘要写入**：流式/非流式回复结束后，调用 `_append_turn_summary(session_id, summary)`；summary 由 LLM 对「本轮用户+助手内容」做摘要生成，单条摘要超长会截断到 `_TURN_SUMMARY_MAX_CHARS`。摘要与 history 会持久化到 `data/sessions/`（history.json、turn_summaries.json、meta.json）。

