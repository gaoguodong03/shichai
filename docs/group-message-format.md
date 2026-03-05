# 群聊消息格式约定（前后端）

本文档规定群聊消息的字段格式，供前端展示与后端持久化使用。

## 消息类型

### 1. 用户消息 (role=user)

```json
{
  "message_id": "msg-xxx",
  "role": "user",
  "content": "用户输入内容",
  "timestamp": "ISO8601"
}
```

### 2. 主持人消息 (role=host)

```json
{
  "message_id": "msg-xxx",
  "role": "host",
  "content": "下面由 某某 发言。",
  "timestamp": "ISO8601",
  "next_prompt": "给下一 DHA 的完整提示词（可选，有则展示）"
}
```

- `next_prompt`：即将发送给下一发言人的完整提示词，前端可折叠展示「给下一 DHA 的提示词」。

### 3. DHA 发言消息 (role=assistant)

```json
{
  "message_id": "msg-xxx",
  "role": "assistant",
  "dha_id": "dha-xxx",
  "content": "完整回复内容（含 tool_call JSON 块）",
  "timestamp": "ISO8601",
  "skill_id": "skill-id 或 default",
  "tool_raw_results": ["工具1原始返回", "工具2原始返回"]
}
```

**字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `skill_id` | string | 本 DHA 使用的技能 ID，来自 DHA 配置的 skill_ids 首项，无则 "default" |
| `content` | string | 完整回复。若调用了工具，需包含 `\`\`\`json\n{"action":"tool_call","tool":"xxx","arguments":{...}}\n\`\`\`` 块，供前端解析小蓝框 |
| `tool_raw_results` | string[] | 每条工具调用的原始返回，与 content 中 tool_call 块顺序一一对应，供「原始输出」按钮 |

**前端解析：**

- `extractToolCalls(content)` 从 content 中提取 `action: "tool_call"` 的 JSON 块
- `tool_raw_results[i]` 对应第 i 个 tool_call 的原始返回
- `skill_id` 用于展示 skill 标签，无则显示「无」
