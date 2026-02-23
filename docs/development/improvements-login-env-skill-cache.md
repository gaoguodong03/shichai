# 改进项开发文档：登录页、移除环境变量展示、回答级 Skill 缓存

本文档描述三项改进的开发思路与实现要点，供评审后实施。

---

## 一、加入登录页面

### 1.1 目标

- 在进入主应用前增加登录页，未登录用户只能看到登录界面。
- 登录成功后进入现有主界面（MainView）。

### 1.2 方案概述

采用**前端路由守卫 + 简单登录态**的轻量方案（不涉及后端真实认证与用户库）：

- **登录页**：独立路由 `/login`，提供用户名/密码表单（或仅用户名 + 确认按钮）。提交后在前端将「已登录」状态写入 `localStorage`（或 sessionStorage），并跳转到 `/`。
- **路由**：根路径 `/` 渲染主应用（MainView）；`/login` 渲染登录页。通过 Vue Router 的 `beforeEach` 守卫：若未登录且目标不是 `/login`，则重定向到 `/login`；若已登录且访问 `/login`，可重定向到 `/`。
- **登出**：在主界面提供登出入口（如侧栏或头部），清除本地登录态并跳转到 `/login`。

后续若接入真实后端认证，可在此基础上增加：调用后端登录 API、写入 token、请求头携带 token、后端校验等，本次仅做前端占位与路由控制。

### 1.3 涉及文件与改动

| 位置 | 改动 |
|------|------|
| `frontend/src/views/LoginView.vue` | 新建：登录页组件（表单、提交、错误提示）。 |
| `frontend/src/router/index.ts` | 新增 `/login` 路由；`beforeEach` 中根据本地登录态做重定向。 |
| `frontend/src/App.vue` 或布局 | 可选：在 MainView 内增加「登出」按钮，清除登录态并 `router.push('/login')`。 |

### 1.4 登录态约定

- **存储**：`localStorage` 键名如 `dha_logged_in`，值为 `"true"` 或简单 token 占位；或存 `dha_user` 为用户名（便于在界面展示）。
- **校验**：仅前端读取该键，无后端校验；便于后续替换为真实 token 与后端校验。

---

## 二、删去环境变量的前端显示

### 2.1 目标

- 不再在设置中展示「环境变量 (.env)」入口与页面，避免在前端暴露 .env 内容。

### 2.2 方案概述

- **前端**：移除「环境变量」入口与对应视图的引用；不再请求 `/api/settings/env`。
- **后端**：可选保留或删除 `GET /api/settings/env`。若仅前端不再使用，可保留接口以备调试；若希望彻底不暴露，可删除该接口。

建议：**前端彻底移除入口与页面**；**后端接口可保留但不在文档/UI 中暴露**，便于运维调试；若你方要求完全不提供该能力，则同时删除后端接口。

### 2.3 涉及文件与改动

| 位置 | 改动 |
|------|------|
| `frontend/src/views/MainView.vue` | 删除设置分类中的 `{ id: 'env', label: '环境变量 (.env)' }`；删除 `currentModule === 'settings' && selectedId === 'env'` 的 template 分支；删除对 `EnvSettingsView` 的 import 与使用。 |
| `frontend/src/views/EnvSettingsView.vue` | 可保留文件不引用，或直接删除（推荐删除以避免遗留）。 |
| `backend/app/api/settings.py` | 可选：删除 `get_env_content` 及 `@router.get("/settings/env")`；若不删，则仅前端不再调用。 |

---

## 三、Chat 每条回答的 skill 写进固定缓存（占一个字段）

### 3.1 目标

- 每条助手回复（即每个 Turn 的 AIMessage）对应的「本回答使用的 skill」持久化到固定缓存中，占用一个明确字段，便于历史展示、摘要与后续扩展。

### 3.2 现状简述

- **流式输出**：后端在 SSE 的 `content` 事件中已携带 `meta: { skills: [selected_skill_id] }`，前端 ChatView 用 `msg.meta?.skills` 显示。
- **持久化**：当前 `history.json` 中每条消息的格式为 `{ "role": "user"|"assistant", "content": "..." }`，assistant 消息另有 `tool_raw_results`；**没有**保存本条回复使用的 `skill_id`。因此刷新或重新加载会话后，历史消息的「技能」信息丢失，只能显示「无」。

### 3.3 方案概述

在**会话历史**中为每条 **assistant** 消息增加一个字段 `skill_id`（字符串，可选），表示该条回复使用的技能；写入与读取都基于该字段，形成「固定缓存」中的一条明确字段。

- **写入**：在 `chat.py` 中，当一轮对话结束、将本轮 AIMessage 追加到 `_CHAT_HISTORY` 时，把本轮的 `selected_skill_id` 写入该 AIMessage 的 `additional_kwargs["skill_id"]`（或单独字段）；`_message_to_dict` 序列化 AIMessage 时，把 `skill_id` 写入 JSON（如 `out["skill_id"] = ...`）。
- **读取**：从磁盘加载 `history.json` 时，若某条消息 `role === "assistant"` 且带有 `skill_id`，则反序列化为 AIMessage 时把 `skill_id` 放进 `additional_kwargs`（或前端/API 需要的结构）；这样 GET 会话消息时返回的每条 assistant 消息都带 `skill_id`。
- **前端**：ChatView 展示历史消息时，优先使用消息自带的 `skill_id`（或 `meta.skills[0]`）；若流式返回的 `content` 事件中带有 `meta.skills`，仍可覆盖当前正在生成的那条，逻辑不变。

这样「固定缓存」就是：**每条 assistant 消息在 history 中的 `skill_id` 字段**；不新增单独缓存表，不改变 session/turn 的层级概念。

### 3.4 涉及文件与改动

| 位置 | 改动 |
|------|------|
| `backend/app/api/chat.py` | ① 构造本轮 AIMessage 时：`aimessage_kwargs["additional_kwargs"] = { "tool_raw_results": ..., "skill_id": selected_skill_id }`（若已有 `additional_kwargs` 则合并 `skill_id`）。② `_message_to_dict`：对 AIMessage 若存在 `additional_kwargs.get("skill_id")`，则 `out["skill_id"] = ...`。③ `_load_sessions_from_disk`：恢复 AIMessage 时若 `m.get("skill_id")` 存在，则 `kwargs["additional_kwargs"]["skill_id"] = m["skill_id"]`（或通过 `additional_kwargs` 传入）。 |
| `backend/app/api/chat.py`（GET 会话消息） | 若当前 API 返回的消息格式已通过 `_message_to_dict` 生成，则无需改；返回的 assistant 消息会自然带 `skill_id`。若前端期望在 `meta.skills` 中展示，可在返回消息时把 `skill_id` 填入 `meta.skills`（或保持 `skill_id` 字段，前端用其一即可）。 |
| `frontend/src/views/ChatView.vue` | 历史消息的展示：若接口返回的 assistant 消息带 `skill_id`，则用其显示「本回答使用的 skill」；若带 `meta.skills` 则沿用现有逻辑；可统一为 `msg.skill_id ?? msg.meta?.skills?.[0] ?? '无'`。 |

### 3.5 数据格式约定

- **history.json 单条 assistant 消息**（新增字段）：  
  `{ "role": "assistant", "content": "...", "skill_id": "wechat-article-writer", "tool_raw_results": [] }`  
  `skill_id` 可选，无则省略或为空字符串。
- **向后兼容**：加载时若旧数据无 `skill_id`，则视为空，前端显示「无」；新数据写入时始终带 `skill_id`（可为空）。

---

## 四、实施顺序建议

1. **删除环境变量前端展示**（改动小、无依赖）  
   → 移除侧栏入口、Env 视图引用、可选删除 EnvSettingsView.vue 与后端 `/settings/env`。

2. **每条回答 skill 写进固定缓存**（纯后端 + 前端展示）  
   → 后端：AIMessage 写入/读取时带上 `skill_id`；前端：历史消息用 `skill_id`（或 meta.skills）展示。

3. **登录页面**（独立功能）  
   → 新增 LoginView、路由与守卫、本地登录态；主界面加登出。

---

## 五、简要小结

| 改进项 | 思路概要 |
|--------|----------|
| 登录页面 | 新增 `/login` 与 LoginView，路由守卫根据本地登录态重定向；登出清空本地并跳转登录。 |
| 删去环境变量前端显示 | 前端移除设置中的「环境变量」入口与 EnvSettingsView；后端 env 接口可选保留或删除。 |
| 回答级 skill 缓存 | 在 history 中每条 assistant 消息增加 `skill_id` 字段；写入时从 `selected_skill_id` 写入，读取时恢复；前端历史消息用该字段展示 skill。 |

以上为开发思路与要点；可根据你的反馈修改后再按此文档实施开发。
