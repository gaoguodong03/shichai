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


删除用户的发言
调节发言框
能不能做一个评估和测试系统，评估代码。确定哪些代码是合理的，这样就不用修改。把程序变为一个一个模块黑盒而不是一整个黑盒。
llm 回答的短暂游戏和动画

## 二、其他待开发项

- 主持人可以推荐多个人（不设限）加入进来
- 主持人不必再根据当前有多少成员分形态，也就是主持人应该常驻“邀请成员”的功能，只要感觉解决不了，就要请成员，因此我认为两个形态可以合并
- 主持人决定下一个发言人时，应该结合对话的内容，总结出给下一发言人的提示词（这个步骤是调用 LLM 执行的，所以只用在提示词中写就好了），写入“给下一个dha 的提示词”中
- 主持人在最后做 json 推荐后，这个 json 应该与主持人说话分为两个字段存储，专项专用。

- **程序逻辑梳理（工具调用单独字段、消息格式统一）**：后端群聊 assistant 消息已含 `tool_raw_results` 字段，前端已从此读取并展示；如需进一步把「工具调用」从 content 中彻底剥离、并统一所有消息为单一变量与固定格式（含发给某 DHA 的提示词字段），建议后续单独梳理接口与存储格式后再改。

---

## 三、完成项目

### Chat 上下文记忆说明（核查结果）

- **存储**：`_CHAT_HISTORY[session_id]` 存该会话的完整消息列表（HumanMessage / AIMessage）；`_TURN_SUMMARIES[session_id]` 存每轮结束后的 LLM 摘要（仅保留最近 10 轮，`_HISTORY_WINDOW_TURNS = 10`）。
- **每轮传给模型的内容**：`_build_history_summary(session_id, history)` 生成「历史摘要」字符串：
  - **优先**：若存在 `_TURN_SUMMARIES`，取最近 10 轮摘要，格式为「第 N 轮：摘要文本」；总长超过 `_HISTORY_SUMMARY_MAX_TOTAL_CHARS`（3200）时从最早轮开始丢弃。
  - **回退**：无 Turn 摘要时，按原始 history 的 Human+AI 对，取最近 10 轮，每轮截断为「用户：前 200 字」「助手：前 200 字」的预览。
- **请求时**：`user_content = "历史对话摘要：\n" + history_summary + "\n\n当前用户输入：\n" + request.message`，整段作为**一条** HumanMessage 传给 Agent；即模型每轮只收到「历史摘要 + 当前输入」，不直接收到完整消息列表。
- **轮次摘要写入**：流式/非流式回复结束后，调用 `_append_turn_summary(session_id, summary)`；summary 由 LLM 对「本轮用户+助手内容」做摘要生成，单条摘要超长会截断到 `_TURN_SUMMARY_MAX_CHARS`。摘要与 history 会持久化到 `data/sessions/`（history.json、turn_summaries.json、meta.json）。

捏一些人
做一个组会的讨论