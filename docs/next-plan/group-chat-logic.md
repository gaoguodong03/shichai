# Group 群聊前后端逻辑说明

## 〇、群聊执行顺序（从用户输入到最终输出）

本节按**时间顺序**梳理：用户一次请求进来后，后端依次做了什么、**给谁发了什么**，不涉及字段细节。

### 顺序总览

1. **请求入口**  
   前端 POST `.../chat/stream`，body 里可有：`message`（用户输入）、`override_next_speaker`（指定下一发言人）、`custom_prompt`（给下一 DHA 的提示词）。

2. **写入用户消息**  
   若有 `message`，则追加一条 `role=user` 的消息到历史并落盘。  
   **讨论目标**：从历史中取**首条用户消息**的前 200 字作为本场 `discussion_goal`，后续主持人和 DHA 都会用到。

3. **确定上一发言人**  
   从历史中倒序找最近一条「参与讨论的 DHA」发言（`role=assistant` 且 `dha_id` 不是主持人），得到 `last_speaker_dha_id`，供主持人判断「谁刚说完、是否 task_done」。

4. **决定下一发言人**（三种情况）  
   - **前端指定了 override_next_speaker**：直接用该值（可为某 dha_id、user、end），不再调用主持人。  
   - **仅 1 个 DHA**：也经主持人点名后，再让该 DHA 发言。  
   - **多 DHA 且未指定**：  
     - **手动模式**：只调用主持人，得到「建议的下一发言人 + 主持词 + next_prompt + suggested_order」，写一条主持人消息，然后 **end + waiting_for_user**，等用户下次请求再带 override 或新 message。  
     - **自动模式**：调用主持人得到 decision，若有「下一发言人是某 DHA」则先写一条主持人消息，再进入下面的 DHA 执行循环。

5. **主持人被调用时，发给主持人的内容**  
   - 参与者列表（各 DHA 的 name / dha_id / role）  
   - 讨论目标（首条用户消息）  
   - 最近讨论内容（历史消息转成的【用户】/【主持人】/【DHA名】文本）  
   - 若已有上一发言人：刚发言的 DHA 的 dha_id；否则：说明「请指定第一个发言人」  
   主持人（或默认 leader_decide）返回：`task_done`、`next_speaker`、`reason`、`announcement`（主持词）、可选 `next_prompt`（给下一 DHA 的提示词）、可选 `suggested_order`（首轮任务规划顺序）。

6. **写主持人消息**  
   把主持词写入一条消息（role=host 或 assistant+dha_id=主持人），并带上 `next_dha_name`、`next_prompt`、`suggested_order`（若有），落盘并推给前端。

7. **DHA 执行循环**（当 next_speaker 是某 dha_id 时）  
   - **发给该 DHA 的「用户侧」输入**：  
     - 若本次请求带了 `custom_prompt` 且尚未用过，则用 `custom_prompt`；  
     - 否则用**上一条主持人消息里的 next_prompt**（主持人生成的或后端默认模板：讨论目标 + 最近讨论 + 「请紧扣讨论目标发言」）。  
   - **发给该 DHA 的「系统侧」**：该 DHA 的 skill 内容 + 角色说明 + 应用级 system_prompt。  
   - 该 DHA 的 agent 流式输出 → 前端逐 token 展示；整段回复结束后写一条 `role=assistant`、`dha_id=该 DHA` 的消息并落盘。

8. **该 DHA 说完之后（多 DHA + 自动模式）**  
   再次调用主持人（输入：更新后的最近讨论 + 刚发言的 DHA 的 dha_id）→ 得到新的 next_speaker、主持词、next_prompt。  
   - 若 next_speaker 仍是某 dha_id：写主持人消息，然后回到步骤 7，让该 DHA 发言。  
   - 若 next_speaker 为 user 或 end：写主持人消息（若有），然后结束循环。

9. **结束**  
   - 发 `event: end`，并带上是否 `waiting_for_user`、`suggested_next_speaker`（建议的下一发言人，供前端自动确认用）、或 `discussion_ended`。  
   - 若是等待用户，则本轮不再继续调用 DHA，等用户下次请求（可带 message 或 override_next_speaker + custom_prompt）。

### 给谁发了什么（汇总）

| 对象 | 收到的主要内容 |
|------|----------------|
| **主持人**（或默认调度 LLM） | 参与者列表、讨论目标、最近讨论全文、上一发言人 dha_id（或「指定首发言人」）；输出 next_speaker、主持词、next_prompt、suggested_order 等。 |
| **参与讨论的 DHA** | 一条「用户消息」= next_prompt（讨论目标 + 最近讨论 + 主持人的具体指引，或默认模板）；系统消息 = 该 DHA 的 skill + role。 |
| **前端** | 流式：start → 若干 message（主持人/assistant）→ content（DHA 流式片段）→ end（含 waiting_for_user、suggested_next_speaker 等）。 |

### 举例说明

- **场景**：群聊里有 2 个 DHA：「需求分析」「写作助手」，并设了主持人 DHA。用户输入：「帮我写一份本周工作周报」。  
- **执行顺序**：  
  1. 用户消息「帮我写一份本周工作周报」写入历史；讨论目标 = 该句。  
  2. 无上一发言人，自动模式下调用主持人，输入：参与者列表、讨论目标、最近讨论（此时只有【用户】这条）。  
  3. 主持人返回：next_speaker=需求分析、主持词「下面由 需求分析 发言」、next_prompt=「讨论目标：… 请先梳理用户本周做了哪些事、需要突出哪些成果」。  
  4. 写一条主持人消息（含 next_prompt、suggested_order 若有）→ 前端展示。  
  5. **需求分析 DHA** 收到 next_prompt 作为「用户消息」→ 流式输出（例如先问用户要更多信息或直接列要点）→ 写一条 assistant(需求分析) 消息。  
  6. 再次调用主持人，输入：最近讨论（已含用户 + 主持人 + 需求分析）。主持人返回：task_done=true、next_speaker=写作助手、next_prompt=「根据需求分析的要点，写一份周报正文」。  
  7. 写主持人消息 → **写作助手 DHA** 收到上述 next_prompt → 流式输出周报 → 写 assistant(写作助手) 消息。  
  8. 再调主持人，返回 next_speaker=user、主持词「请用户查看或补充」→ 写主持人消息 → end（waiting_for_user, suggested_next_speaker=user）。  
  9. 前端展示完整对话；用户可继续输入或选下一发言人再点确认。

---

## 一、整体流程概览

```
用户在前端 Group 会话中发送消息
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 前端 POST /api/sessions/{id}/chat/stream（或 .../group-sessions/..）│
│ body: { message?, override_next_speaker?, custom_prompt? }        │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 后端 group_chat_stream（仅流式）                                  │
│ 1. 若有 message：追加 user 消息并落盘                             │
│ 2. 从历史中取 last_speaker_dha_id（最近一条非主持人的 assistant）│
│ 3. 若未指定 override_next_speaker → 由主持人 DHA 或默认调度决策   │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 主持人决策（二选一）                                              │
│ • 主持人 DHA：_host_decide_by_dha(leader_dha_id) 执行 group-host  │
│   skill，解析回复得到 task_done/next_speaker/announcement         │
│ • 默认调度：leader_decide(llm, ...) 仅输出 JSON                   │
│ 输出：task_done, next_speaker, reason, announcement（主持词）     │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ 写入主持人发言：assistant(leader_dha_id, announcement) 并落盘    │
└─────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────┐
│ while next_speaker in dha_ids：                                  │
│   1. 用该 DHA 的 skill + tools 构造 agent，传入群聊上下文          │
│   2. agent 流式/非流式输出 → 前端展示 + 落盘一条 assistant 消息   │
│   3. last_speaker_dha_id = 当前 DHA（参与讨论者）                 │
│   4. 再次由主持人 DHA / leader_decide 决策 → 主持词 + next_speaker │
│   5. 写入主持人发言 assistant(leader_dha_id)，再轮转或结束        │
│   6. 若 next_speaker 为 user/end → 退出循环，结束本轮             │
└─────────────────────────────────────────────────────────────────┘
```

## 二、后端关键逻辑

### 2.1 入口与数据

| 文件 | 说明 |
|------|------|
| `backend/app/api/group_chat.py` | 群聊 API：会话 CRUD、`/chat/stream`（仅流式） |
| `backend/app/agent/leader_scheduler.py` | 领导人调度：根据历史与上一发言人决定 task_done 与 next_speaker |

- **会话与历史**：`group_sessions_meta.json` 存会话元数据；`group_history_{id}.json` 存消息列表。
- **消息结构**：`role`（user | assistant）、`dha_id`（assistant 时必填）、`content`、`message_id`、`timestamp`。

### 2.2 主持人 DHA 与 group-host skill

- **主持人**：由会话的 `leader_dha_id` 指定，即某个具体 DHA 担任。
- **主持技能**：`skills/group-host/SKILL.md` 定义主持人行为：根据讨论目标与最近讨论、上一发言人，输出一句**主持词**（announcement）和 **JSON**（task_done, next_speaker, reason）。主持人 DHA 调用时仅使用该 skill，不绑定 MCP 工具。
- **决策流程**：若存在 `leader_dha_id` 且该 DHA 有效，则调用 `_host_decide_by_dha` 执行 group-host skill，解析回复；解析失败或未配置主持人时回退到 `leader_decide`（默认 LLM 调度）。
- **主持词展示**：每次决策后写入一条 `role=assistant`、`dha_id=leader_dha_id`、`content=announcement` 的消息，前端将该 DHA 展示为「主持人」并显示主持词。

### 2.3 首发言人与「等待用户」的修正

- 若**没有**上一发言人且领导人返回 `next_speaker="user"`：后端会强制 `next_speaker = dha_ids[0]`，保证至少有一个 DHA 先发言。
- 若**最后一条是用户消息**且领导人仍返回 `next_speaker="user"`：后端会按轮转取下一个 DHA（`dha_ids[(idx+1) % len(dha_ids)]`），避免用户刚说完就结束。

### 2.4 同一 DHA 连续发言

- 当领导人返回 **task_done=false** 时，后端会把 `next_speaker` 设为**当前发言人**，即同一 DHA 会再发一条。
- 若领导人多次返回 task_done=false（或 LLM 解析失败回退逻辑导致重复），就会出现**同一 DHA 连续多条**（例如三条）的情况。
- 主持人 DHA 的每次决策会写入一条 assistant(leader_dha_id) 消息，内容为主持词，前端以「主持人」标签展示。

## 三、前端关键逻辑

### 3.1 数据流

| 文件 | 说明 |
|------|------|
| `MainView.vue` | 左侧导航选 Group → 中间列会话列表 → 右侧 `GroupChatView`；`groupSessionDetail` 来自 `GET /api/group-sessions/{id}` |
| `GroupChatView.vue` | 展示 `messages`（props）、发送消息时 POST `/api/sessions/{id}/chat/stream`，通过 SSE 接收 message/content/end，父组件拉取详情刷新列表 |

- 会话聊天**仅使用流式**接口：`POST .../chat/stream`，前端通过 SSE 逐条接收 start → message → content → end。

### 3.2 展示规则

- **用户消息**：右对齐、蓝色气泡。
- **DHA 消息**：左对齐；展示 `dha_map[dha_id].name`、`dha_map[dha_id].role`（简介），并按 `dha_id` 哈希取不同边框/背景色。
- **主持人消息**：主持人由 `leader_dha_id` 对应的 DHA 担任，其发言为 `role=assistant`、`dha_id=leader_dha_id`；前端根据 `msg.dha_id === leaderDhaId` 显示「主持人」标签。旧版 `role=host` 仍兼容展示。

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
   - 流式接口已按上述逻辑实现。

2. **主持人提示消息**  
   - 在每次某 DHA 发言前，向 `messages` 追加一条 `role="host"` 的消息，`content` 为「主持人：接下来由 {name} 发言。」并落盘。  
   - 前端对 `role === 'host'` 做单独展示（居中、灰色小字、圆角标签样式）。  
   - `_messages_to_context` 中对 `role="host"` 按「【主持人】content」拼入上下文字符串。

---

文档版本：基于当前代码梳理，适用于 `group_chat.py` 与 `leader_scheduler.py` 的现有实现。
