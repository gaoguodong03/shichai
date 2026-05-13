# DHA 输入大模型的提示词结构

本文档说明 DHA 每次请求大模型时，实际发送的**完整提示词内容**及其组成结构。

---

## 一、两阶段流程概览

DHA 采用**两阶段**设计（见 [skill-mcp-design-draft.md](./skill-mcp-design-draft.md)）：

1. **第一次调用**：技能选择，仅输入用户消息 + 各 skill 的 name（+ description，若有）
2. **第二次调用**：技能执行，输入选中 skill 的完整内容 + 用户问题 + 历史摘要（若有）

---

## 二、消息格式概览

DHA 使用 LangChain 的 `messages` 格式调用 LLM。每次调用时，`messages` 是一个有序列表，可能包含：

| 序号 | 角色 | 说明 |
|-----|------|------|
| 1 | system | 系统提示词（固定模板 + 工具 + 技能），每次请求首条 |
| 2..N | human / ai | 对话历史 + 工具执行结果，交替出现 |

**关键逻辑**：在 `call_model` 中，若首条不是 `SystemMessage`，则自动在队列最前插入系统提示词。

---

## 三、系统提示词（System Prompt）结构

以下为**技能执行阶段**（第二次调用）的系统提示词结构，对应 `create_skill_execution_agent`。技能选择阶段（第一次调用）见 `skill_selector.py`。

### 3.1 用户自定义系统提示词（可选）

- **来源**：应用设置中的「系统提示词」（`app_settings.system_prompt`）
- **注入时机**：每次 chat 前
- **格式**：用户输入的纯文本，不做额外处理
- **位置**：系统提示词的最开头

```
{用户设置的系统提示词}

```

### 3.2 角色与工具列表

固定模板：

```
你是一个有用的 AI 助手，可以使用工具来帮助用户。

你可以使用以下工具：
- {tool_name}: {tool_description}
- {tool_name}: {tool_description}
...
```

- **工具来源**：
  - MCP 工具：`mcp_manager.get_tools()`，按技能或请求过滤；读文件为 file-reader/filesystem 的 MCP 工具（如 `filesystem_read_text_file`、`file-reader_read_pdf`）
  - 内置工具：`export_session_to_md`、`call_api`、`run_skill_script`（已选技能时）
- **工具名格式**：MCP 工具为 `{server_id}_{tool_name}`（如 `exa_web_search_exa`、`filesystem_read_text_file`）

### 3.3 工具调用格式说明

```
当你需要使用工具时，请按照以下格式回复：
```json
{
    "action": "tool_call",
    "tool": "tool_name",
    "arguments": {...}
}
```

当你不需要使用工具时，直接回复用户的问题。

## 文件引用
当用户消息中出现【文件引用：path】时，**必须先调用 file-reader 或 filesystem 的读文件工具**（如 `filesystem_read_text_file`、`file-reader_read_pdf` 等，path 为相对工作区路径）读取内容，再根据文件内容回答。不要猜测文件内容。
```

> 说明：实际调用时，LLM 使用 LangChain 的 `bind_tools` 返回结构化 `tool_calls`，上述 JSON 格式为兼容旧解析逻辑保留。

**技能执行阶段**的系统提示词中**不再包含**技能选择规则或可用技能索引：技能已在第一次调用中选定，此处仅注入**选中 skill 的完整内容**。

---

## 四、对话消息（Human / AI）

### 4.1 层级概念

- **轮对话（Session）**：新建对话、历史会话的粒度，对应 `session_id`
- **轮内对话（Turn）**：每轮中的一次「用户消息 + 助手回复」
- **记忆**：传给 LLM 的应是本轮各 Turn 的**摘要或关键内容**，而非原始全文。详见 [会话、轮对话与记忆设计](./session-round-memory.md)。

### 4.2 消息来源

- **历史消息**：`_CHAT_HISTORY[session_id]`，每对 (HumanMessage, AIMessage) 即一次 Turn，最多保留最近 **5 条**（`_CHAT_HISTORY_MAX_MESSAGES`）
- **历史摘要**：`_build_history_summary(history)` 构建 `history_summary`，作为「本轮记忆」注入当前用户消息前
- **本条用户消息**：`HumanMessage(content=request.message)`（含 history_summary 时合并为单条）
- **工具执行结果**：格式为 `HumanMessage(content="工具 {tool_name} 的执行结果: {result}")`

### 4.3 单次请求的初始 messages

```
[
  HumanMessage(历史消息1),   // 或 AIMessage
  AIMessage(历史回复1),
  ...
  HumanMessage(本条用户消息)
]
```

系统提示词在 `call_model` 中作为 `SystemMessage` 插入到最前面，因此实际发给 LLM 的为：

```
[
  SystemMessage(系统提示词),
  HumanMessage(历史消息1),
  AIMessage(历史回复1),
  ...
  HumanMessage(本条用户消息)
]
```

### 4.4 ReAct 循环中的追加

当 LLM 返回 `tool_calls` 时：

1. **call_tool** 执行工具
2. 将结果封装为 `HumanMessage(content="工具 xxx 的执行结果: ...")`
3. 该消息追加到 `messages`
4. 再次进入 **agent** 节点，LLM 收到的是：原有 messages + 工具结果

因此，多轮工具调用时，messages 中会交替出现 `AIMessage`（含 tool_calls）和 `HumanMessage`（工具结果）。

---

## 五、完整数据流示意

```
用户输入: "生成北邮校庆文案"
session_id: "default"

↓ Chat API 准备（工具、skills_for_selection、历史摘要）

↓ 第一次调用：select_skill
  输入：用户消息 + 各 skill 的 name+description
  输出：skill_id = "wechat-article-writer"

↓ 获取 skill_full_content，create_skill_execution_agent

skill_execution 的 system_prompt = 
  用户设置(可选) +
  选中 skill 的完整内容 +
  角色与工具列表 +
  工具调用格式

↓ 第二次调用：技能执行 Agent（ReAct 循环）

初始 messages: [HumanMessage("生成北邮校庆文案")]  // 若有历史则含摘要

↓ call_model 插入 SystemMessage，发给 LLM

↓ LLM 返回 AIMessage（含 tool_calls: exa_web_search_exa）

↓ call_tool 执行，结果追加

下一轮 messages:
  [SystemMessage(system_prompt),
   HumanMessage("生成北邮校庆文案"),
   AIMessage(tool_calls...),
   HumanMessage("工具 exa_web_search_exa 的执行结果: ...")]

↓ LLM 继续推理，可能再调工具或直接回复
```

---

## 六、日志查看

在 `backend/app/agent/skill_agent_runtime.py` 的 `call_model` 中，每次调用 LLM 前会输出：

```
输入大模型的提示词:
  [1] system: 共 N 字符，前150字: ...
  [2] human: ...
  [3] ai: ...
```

运行后端时，可在终端看到本次请求的 messages 概览，便于调试和确认实际发送内容。

---

## 七、相关文档

- [会话、轮对话与记忆设计](./session-round-memory.md)：轮 vs Turn、记忆设计
- [运行流程](./runtime-flow.md)：两阶段流程与 ReAct 循环
- [API 设计](./api-design.md)：chat 接口与请求参数
- [Skill + MCP 设计](./skill-mcp-design-draft.md)：两阶段设计说明
- [Skills 配置](../features/skills-config.md)：技能加载与筛选
