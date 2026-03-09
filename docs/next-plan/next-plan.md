# 下一步开发计划

本文档记录待开发项与后续规划。

---

## 一、暂缓内容

- 登录与认证（后续）：当前登录为**文本文件账密校验**（`config/auth_users.txt`），以下为后续可做项：
  - **接入数据库**：将用户与密码存储迁入数据库（如 SQLite/PostgreSQL），支持注册信息、密码加密存储与找回等。
  - **管理员与用户权限区分**：区分管理员与普通用户，不同权限可做不同能力（例如：仅管理员可配置 MCP/Skills、应用设置、用户管理；普通用户仅使用 Chat、个人会话与导出等）。

- Skill creator 以及群聊中的 skillcreator
- 领域报告 Skill + MCP
- MCP 沙箱方向

-（3）是否考虑引入接入外部事件的功能（？）
-（4）是否考虑引入接入外部消息应用的功能（真的不急）
- mcp Playwright 控制浏览器
加载 skill，能不能从 github 上加载
- **两种 Group 发言模式**：
  - **auto**：由主持人/调度决定下一发言人，逻辑不变。
  - **manual**：创建 Group 时可选「手动」；每次用户发言前必须选择「下一发言人」，仅该 DHA 回答一次后结束，等待用户再次提问；已修复「该 DHA 回答后控制权回到主持人」的 bug（manual 下不再调用主持人，直接结束本轮）。

删除用户的发言
调节发言框
能不能做一个评估和测试系统，评估代码。确定哪些代码是合理的，这样就不用修改。把程序变为一个一个模块黑盒而不是一整个黑盒。
llm 回答的短暂游戏和动画

## 二、其他待开发项


## 三、完成项目

### Chat 上下文记忆说明（核查结果）

- **存储**：`_CHAT_HISTORY[session_id]` 存该会话的完整消息列表（HumanMessage / AIMessage）；`_TURN_SUMMARIES[session_id]` 存每轮结束后的 LLM 摘要（仅保留最近 10 轮，`_HISTORY_WINDOW_TURNS = 10`）。
- **每轮传给模型的内容**：`_build_history_summary(session_id, history)` 生成「历史摘要」字符串：
  - **优先**：若存在 `_TURN_SUMMARIES`，取最近 10 轮摘要，格式为「第 N 轮：摘要文本」；总长超过 `_HISTORY_SUMMARY_MAX_TOTAL_CHARS`（3200）时从最早轮开始丢弃。
  - **回退**：无 Turn 摘要时，按原始 history 的 Human+AI 对，取最近 10 轮，每轮截断为「用户：前 200 字」「助手：前 200 字」的预览。
- **请求时**：`user_content = "历史对话摘要：\n" + history_summary + "\n\n当前用户输入：\n" + request.message`，整段作为**一条** HumanMessage 传给 Agent；即模型每轮只收到「历史摘要 + 当前输入」，不直接收到完整消息列表。
- **轮次摘要写入**：流式/非流式回复结束后，调用 `_append_turn_summary(session_id, summary)`；summary 由 LLM 对「本轮用户+助手内容」做摘要生成，单条摘要超长会截断到 `_TURN_SUMMARY_MAX_CHARS`。摘要与 history 会持久化到 `data/sessions/`（history.json、turn_summaries.json、meta.json）。

