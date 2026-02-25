# Group 群聊前后端逻辑说明

## 一、整体流程概览

```
用户在前端 Group 会话中发送消息
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 前端 POST /api/group-sessions/{id}/chat 或 .../chat/stream      │
│ body: { message?, override_next_speaker?, action? }              │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 后端 group_chat / group_chat_stream                              │
│ 1. 若有 message：追加 user 消息并落盘                             │
│ 2. 从历史中取 last_speaker_dha_id（最近一条 assistant 的 dha_id）│
│ 3. 若未指定 override_next_speaker → 调用领导人调度                │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 领导人调度 leader_decide(llm, dha_list, discussion_goal,         │
│            recent_messages, last_speaker_dha_id)                 │
│ 输入：群内 DHA 列表、讨论目标、最近讨论内容、上一发言人             │
│ 输出：{ task_done, next_speaker, reason }                        │
│   - task_done=false → 当前 DHA 继续发言（未完成任务）            │
│   - task_done=true  → next_speaker 为下一发言人                  │
│   - next_speaker：dha_id | "user" | "end"                        │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ while next_speaker in dha_ids：                                  │
│   1. 用该 DHA 的 skill + tools 构造 agent，传入群聊上下文          │
│   2. agent 流式/非流式输出 → 前端展示 + 落盘一条 assistant 消息   │
│   3. last_speaker_dha_id = 当前 DHA                              │
│   4. 再次调用 leader_decide → 得到新的 next_speaker              │
│   5. 若 task_done=false → next_speaker 保持为当前 DHA（同一人再发）│
│   6. 若 next_speaker 为 user/end → 退出循环，结束本轮             │
└─────────────────────────────────────────────────────────────────┘
```

## 二、后端关键逻辑

### 2.1 入口与数据

| 文件 | 说明 |
|------|------|
| `backend/app/api/group_chat.py` | 群聊 API：会话 CRUD、`/chat`（非流式）、`/chat/stream`（流式） |
| `backend/app/agent/leader_scheduler.py` | 领导人调度：根据历史与上一发言人决定 task_done 与 next_speaker |

- **会话与历史**：`group_sessions_meta.json` 存会话元数据；`group_history_{id}.json` 存消息列表。
- **消息结构**：`role`（user | assistant）、`dha_id`（assistant 时必填）、`content`、`message_id`、`timestamp`。

### 2.2 首发言人与「等待用户」的修正

- 若**没有**上一发言人且领导人返回 `next_speaker="user"`：后端会强制 `next_speaker = dha_ids[0]`，保证至少有一个 DHA 先发言。
- 若**最后一条是用户消息**且领导人仍返回 `next_speaker="user"`：后端会按轮转取下一个 DHA（`dha_ids[(idx+1) % len(dha_ids)]`），避免用户刚说完就结束。

### 2.3 同一 DHA 连续发言（当前问题来源）

- 当领导人返回 **task_done=false** 时，后端会把 `next_speaker` 设为**当前发言人**，即同一 DHA 会再发一条。
- 若领导人多次返回 task_done=false（或 LLM 解析失败回退逻辑导致重复），就会出现**同一 DHA 连续多条**（例如三条）的情况。
- 当前设计下，**主持人（领导人）本身不写入聊天记录**，只做调度；因此前端看不到「主持人说：接下来由 XX 发言」这类提示。

## 三、前端关键逻辑

### 3.1 数据流

| 文件 | 说明 |
|------|------|
| `MainView.vue` | 左侧导航选 Group → 中间列会话列表 → 右侧 `GroupChatView`；`groupSessionDetail` 来自 `GET /api/group-sessions/{id}` |
| `GroupChatView.vue` | 展示 `messages`（props）、发送消息时 POST `/api/group-sessions/{id}/chat`，成功后 `emit('message-sent')`，父组件拉取详情刷新列表 |

- 当前 Group 聊天使用的是**非流式**接口：`POST .../chat`，一次返回完整 `messages`，前端不处理 SSE。
- 流式接口 `.../chat/stream` 存在，但若前端未调用，则不会出现流式行为。

### 3.2 展示规则

- **用户消息**：右对齐、蓝色气泡。
- **DHA 消息**：左对齐；展示 `dha_map[dha_id].name`、`dha_map[dha_id].role`（简介），并按 `dha_id` 哈希取不同边框/背景色。
- **主持人消息**：当前数据模型中没有 `role=host` 或类似字段，因此前端不会、也无法显示「主持人」的单独一条消息。

## 四、问题与改进对应

| 现象 | 原因 | 改进方向 |
|------|------|----------|
| 三条都是同一个 DHA | 领导人多次返回 task_done=false，或 next_speaker 一直为同一 dha_id | 限制同一 DHA 在一轮中连续发言次数；或 task_done=true 时若 next_speaker 仍为上一发言人则改为轮转下一人 |
| 没有主持人消息 | 主持人仅做调度，不写入消息列表 | 可选：在每次 DHA 发言前插入一条「主持人：接下来由 {name} 发言」类系统/主持人消息，前端对 role 或 type 做展示 |

## 五、已实现的后端改动

1. **限制同一 DHA 连续发言**  
   - 使用变量 `consecutive_same_dha` 记录当前连续同一人发言次数。  
   - 若领导人返回的 `next_speaker` 等于 `last_speaker_dha_id`：  
     - 若 `task_done=true`，或已连续同一人发言过（`consecutive_same_dha >= 1`），则强制轮转到下一个 DHA（或结束到 user）。  
     - 若 `task_done=false` 且尚未连续同一人，则允许该 DHA 再发一次，并令 `consecutive_same_dha += 1`。  
   - 若 `next_speaker != last_speaker_dha_id`，则 `consecutive_same_dha = 0`。  
   - 流式与非流式接口均已按上述逻辑实现。

2. **主持人提示消息**  
   - 在每次某 DHA 发言前，向 `messages` 追加一条 `role="host"` 的消息，`content` 为「主持人：接下来由 {name} 发言。」并落盘。  
   - 前端对 `role === 'host'` 做单独展示（居中、灰色小字、圆角标签样式）。  
   - `_messages_to_context` 中对 `role="host"` 按「【主持人】content」拼入上下文字符串。

---

文档版本：基于当前代码梳理，适用于 `group_chat.py` 与 `leader_scheduler.py` 的现有实现。
