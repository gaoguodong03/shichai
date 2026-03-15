# 统一对话模型（单聊与群聊合并）

本文档定义「合并单聊与群聊」后的产品形态、会话模型与数据格式，作为后端与前端改动的依据。

---

## 一、产品形态

### 1.1 唯一对话类型：带主持人的会话

- **新对话 = 主持人对话**：用户点击「新对话」后，进入一个**始终有主持人**的会话；主持人不可删除、不可退出。
- **主持人职责**：欢迎用户、理解需求、推荐专家（DHA）或技能、引导讨论；当会话中只有主持人时，由主持人直接回复（使用 `group-host` 技能或 default）。
- **专家 / 技能**：用户可在对话中「选择某位专家的某技能」与专家对话，或由主持人推荐后加入某 DHA；多 DHA 时由主持人或调度逻辑决定下一发言人。**不再保留**「无主持人的纯单聊」入口。

### 1.2 用户可见能力（合并后）

| 能力 | 说明 |
|------|------|
| 新对话 | 创建一条新会话，默认仅主持人；首条消息即与主持人交流。 |
| 选专家/技能 | 在会话内选择「与某 DHA 的某技能对话」或由主持人推荐 DHA 加入；仍为同一会话内的交互。 |
| 导出 | 将当前会话导出为 Markdown（保留，会话级）。 |
| 工作区文件 | 按会话隔离的工作区（上传/下载/列表），会话 id 即 workspace_id。 |

### 1.3 不再保留

- 单独的「单聊」入口、单聊专用会话列表、单聊专用 API（`/api/chat/stream`、`/api/sessions` 等）在合并后下线，由统一会话 API 替代。

---

## 二、统一会话模型

### 2.1 会话唯一标识与存储

- **会话 id**：与当前群聊一致，使用 `group-{uuid}` 或统一改为 `session-{uuid}`（二选一，实现时定）。下文暂用 `session_id` 表示。
- **一份会话列表**：不再区分「单聊列表」与「群聊列表」；所有会话均为「带主持人的会话」，列表字段见下。
- **存储位置**：统一使用当前群聊的存储方式（或在其上扩展），单聊的 `history.json` / `meta.json` / `turn_summaries.json` 不再使用（可做一次性迁移或只读兼容）。

### 2.2 会话元数据（meta）

每条会话一条 meta，建议字段（与现有 group_sessions_meta 对齐并略作统一）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 会话 id |
| title | string | 标题（可自动生成或用户编辑） |
| dha_ids | string[] | 当前加入的 DHA 列表；**空数组 = 仅主持人** |
| speak_mode | string | 发言模式：auto | manual（与现群聊一致） |
| created_at | string | ISO8601 |
| updated_at | string | ISO8601 |

- **主持人**：不占 `dha_ids`，主持人始终存在；`dha_ids` 为空即「仅主持人在场」。
- 不再使用 `leader_dha_id` 表示主持人（主持人由逻辑固定）。

### 2.3 消息历史格式

一条消息（与现群聊历史格式一致）：

| 字段 | 类型 | 说明 |
|------|------|------|
| role | string | `user` \| `host` \| `assistant` |
| content | string | 正文 |
| dha_id | string | 可选；当 role=assistant 时表示该条回复来自哪个 DHA；role=host 时可省略或固定标识 |
| meta | object | 可选；skill_id、tool_raw_results 等（与现实现兼容） |

- **主持人消息**：role=host 或 role=assistant 且 dha_id 为空/固定 host 标识，由实现约定。
- 历史按时间顺序追加；前端按 session_id 拉取完整列表或分页。

### 2.4 工作区

- 每个会话对应一个工作区：`workspace_id = session_id`。
- 文件 API：`/api/workspaces/{session_id}/files`（与现有一致），导出、run_skill_script 等写文件均落在该工作区。

---

## 三、API 与流程（合并后）

### 3.1 会话 CRUD（统一）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/sessions | 会话列表（原单聊列表 + 群聊列表合并为一份） |
| POST | /api/sessions | 创建会话（默认 dha_ids=[]，即仅主持人） |
| GET | /api/sessions/{id} | 会话详情 + 消息历史 |
| PATCH | /api/sessions/{id} | 更新标题、dha_ids、speak_mode 等 |
| DELETE | /api/sessions/{id} | 删除会话 |

### 3.2 对话流式

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/sessions/{id}/chat/stream | 在指定会话中发送一条用户消息，流式返回回复 |

- **请求体**：与现群聊一致（如 message、可选 selected_dha_id / skill_ids 等，由实现定）。
- **行为**：若当前会话 dha_ids 为空，则由主持人回复（技能用 group-host 或 default）；若 dha_ids 非空，由现有主持人调度/选人逻辑决定下一发言人；若请求中指定了「某 DHA 的某技能」，可在该轮强制该 DHA 用该技能回复（与现「选专家/技能」合并）。

### 3.3 导出与文件

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/sessions/{id}/export | 导出会话为 Markdown（写入该会话工作区并返回下载信息） |
| GET/POST 等 | /api/workspaces/{id}/files | 与现有一致，id 即 session_id |

### 3.4 下线

- 单聊专用：`POST /api/chat/stream`、`GET/POST /api/sessions`（旧单聊 sessions）、`POST /api/sessions/{id}/export`（若与上面统一则保留一条）。
- 群聊专用命名：`/api/group-sessions` 改为 `/api/sessions`（或保留 group-sessions 作为别名并重定向，由实现定）。

---

## 四、后端实现要点（顺序）

1. **统一会话存储**：以现有 group_sessions_meta + group_history_* 为基础，扩展或重命名为统一 sessions 的 meta 与 history；单聊历史若需保留可做一次性迁移脚本或只读兼容。
2. **统一 stream 入口**：仅保留一个流式接口（如 `POST /api/sessions/{id}/chat/stream`），内部根据 session 的 dha_ids 与请求参数决定「主持人回复」或「调度 DHA」；单聊的 `chat_stream` 逻辑合并进来（技能选择、build_tools、export 等能力复用）。
3. **工具组装**：以 `build_tools_for_group_chat` 为主，主持人会话（dha_ids 为空）时传入「主持人 DHA」或等价配置（skill_ids=[group-host]、mcp 等）；需要 export/run_skill_script 时在该路径下扩展，保证统一会话也支持导出与脚本。
4. **路由与兼容**：新 API 使用 `/api/sessions`；旧 `/api/group-sessions` 可 302 或保留一段时间后下线；旧 `/api/chat/stream` 下线。

---

## 五、前端实现要点（顺序）

1. **单一对话入口**：仅保留一个「对话」或「会话」入口；新对话 = 创建带主持人的会话并打开。
2. **主持人不可删**：会话设置/参与者中主持人为固定项，仅可添加/移除 DHA。
3. **选专家/技能**：在会话内通过现有或略改的「选 DHA / 选技能」控件完成，不再有「单聊 vs 群聊」选择。

---

## 六、文档与步骤类型

- [运行流程](runtime-flow.md) 与 [步骤类型与工具](step-types-and-tools.md) 在合并后仅描述「一种会话」下的流程与工具；单聊/群聊差异表述改为「仅主持人」vs「主持人 + 若干 DHA」。
- 本设计文档作为合并的权威说明，实现完成后可把「单聊/群聊」历史表述从其它文档中移除或改为「统一会话（主持人 + 可选 DHA）」。
