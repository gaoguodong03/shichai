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
现在更改产品逻辑，以前打开对话是单独和 chat 聊天，现在更改为和主持人聊天，用户提出需求之后，由主持人推荐某位 DHA 加入对话中，加入对话后就是群聊了，现在主持人也可以在群聊的对话中了（以前的逻辑是删除 chat），这样就可完全删除 chat 了。
优化输入框部分：
- 默认只有一个输入框
- 默认为自动发送
- 将“选择成员 skill”“给下一个DHA的提示词输入框”“自动发送”“增删成员”（在左侧指定下一个发言人时的增加/删除成员）等开关隐藏在“更多”中
- 优化插入文件功能，新增插入本地文件，逻辑是：会先加入到工作区，再从工作区插入到输入框
优化工作区的显示：
- 点击文件会在右侧打开展示栏显示该文件的预览，并支持对 md 文件的在线编辑
梳理程序逻辑：
- 每个DHA 在回复的时候，将“工具调用”的内容单独存储到某个字段中，前后端约定都从这里读取
- 规范所有的消息，统一为一个变量，有固定的格式，如确定消息变量中有一种是发给某个 DHA 的提示词组成，并分为字段。

---

## 四、本次修改说明与结果（输入框 / 工作区 / 插入本地文件 / 增删成员）

**修改时间**：按计划执行，优先级为：输入框优化 → 工作区展示 → 插入本地文件 → 后端增删成员 → 文档记录。

### 1. 输入框优化（默认单输入框 + “更多”收纳）

- **WorkspaceContent.vue（工作台群聊）**
  - 默认仅保留一个合并输入框（讨论目标 + 可选「下一 DHA 提示词」）；「下一 DHA 提示词」输入框默认隐藏，通过「更多」→「显示下一 DHA 提示词输入框」打开。
  - 工具栏：左侧为「下一发言人」选择器 +「插入文件」；「更多」按钮下拉包含：**显示下一 DHA 提示词输入框**（勾选）、**自动确认**（勾选，默认开启）、**成员 Skill**（打开各成员 Skill 选择）、**增删成员**（打开当前成员/可邀请 DHA 面板）。
  - 默认「自动确认」为开启（`groupAutoConfirm` 默认 `true`）。
- **GroupChatView.vue**
  - 默认仅一个输入框（`showExtendedInputs = false`），绑定 `singleInputValue`；无用户消息时作为讨论目标发送，有用户消息时作为下一 DHA 提示词。
  - 「更多」下拉：**显示讨论目标 / 最近讨论 / 下一 DHA 提示词**（勾选后展示三列输入）、**自动确认**、**增删成员**（打开成员与邀请弹窗）。

### 2. 增删成员（收进“更多”+ 后端支持移除）

- **后端** `backend/app/api/group_chat.py`
  - `GroupSessionUpdate` 增加字段：`remove_dha_ids: Optional[List[str]]`。
  - `update_group_session` 中处理 `remove_dha_ids`：从当前 `dha_ids` 中剔除指定 id，并写回 meta。
- **前端 WorkspaceContent.vue**
  - 「更多」→「增删成员」打开面板：**当前成员**列表每人有「移出」按钮（调用 `removeMember(dhaId)`）；**可邀请的 DHA** 多选 +「邀请选中」与原有逻辑一致。
  - 文案由「新增成员」改为「增删成员」，入口仅在「更多」内。

### 3. 工作区展示（点击文件右侧预览 + md 在线编辑）

- **WorkspaceContent.vue** 群聊右侧工作区：
  - 点击文件已在右侧展示栏预览内容（原有逻辑保留）。
  - **md 在线编辑**：当预览文件为 `.md` 时，展示栏头部增加「编辑」按钮；点击后切换为 `textarea`，可修改内容，支持「保存」「取消」；保存调用 `PUT /api/workspaces/{id}/files/content?path=...`，写入后更新本地预览内容并退出编辑状态。

### 4. 插入文件（新增“插入本地文件”）

- **WorkspaceContent.vue** 群聊输入区「插入文件」下拉内：
  - 增加「从本地上传并插入」按钮，触发本地文件选择；选择后调用 `POST /api/workspaces/{id}/files/upload` 上传到当前工作区（当前目录或根目录），上传成功后把该文件的引用块（`【文件引用：workspaces/{id}/{path}】`）追加到「给下一 DHA 的提示词」输入内容（`groupNextPrompt`）中，并关闭下拉。
  - 逻辑满足：先加入工作区，再以引用形式插入到输入框。

### 5. 产品逻辑调整（主持人为先、移除 chat）— 已实现

- **后端** `backend/app/api/group_chat.py`
  - 新建会话时不再默认加入 `dha-chat`：`dha_ids` 为空则保持为空，表示「主持人为先」模式。
  - 当 `dha_ids` 为空时，流式/非流式请求均走主持人逻辑：调用 `_host_only_respond_and_recommend`，由主持人（group-host 技能）回复用户并推荐一位 DHA 加入；返回的 host 消息及 `event: end` 中携带 `suggested_add_dha_id`（可选）。
  - 推荐 DHA 时从全部实例中排除 `CHAT_DHA_ID`，不再使用 Chat。`update_group_session` 中保留对既有会话的 `current.discard(CHAT_DHA_ID)`，兼容历史数据。
- **前端** `frontend/src/views/WorkspaceContent.vue`
  - 收到 `event: end` 或 host 消息中的 `suggested_add_dha_id` 时，在输入区上方展示「主持人建议邀请 [name] 加入讨论」，提供「邀请加入」「忽略」按钮；点击「邀请加入」调用 `PUT add_dha_ids` 邀请该 DHA，刷新会话后进入群聊（主持人仍在流程中，无 chat）。

### 6. 未在本轮实现的内容（留待后续）

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

