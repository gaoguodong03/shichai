# 书童四九 · 后端

FastAPI 服务：统一会话流、Agent 配置、每用户 MCP / Skills、工作区文件 API。

## 环境变量（节选）

| 变量 | 说明 |
|------|------|
| `SHUTONG_USER_DATA_ROOT` | 用户数据根目录，默认 `backend/data/users`；每个用户独占 `data/users/{username}/`（会话、工作区、配置、技能副本）。旧名 `SHICHAI_USER_DATA_ROOT` 已废弃。 |
| `AUTH_SECRET` | JWT 签名密钥，生产环境务必修改。 |
| `ALLOW_ANONYMOUS_API` | 设为 `1` 时允许无 Bearer 访问（仅本地调试，**禁止**用于生产）。 |
| `QWEN_API_KEY` 等 | 各 LLM 提供商的 API Key，见应用内「设置」。 |
| `CALL_API_TIMEOUT` | `call_api` 请求超时秒数，默认 `30`。 |
| `CALL_API_DISABLE_SSRF_GUARD` | 设为 `1` 时跳过 call_api 的主机 SSRF 检查（仅本地调试，**禁止**生产）。 |
| `CALL_API_HTML_EXTRACT` | 设为 `0` 时不对 HTML 响应做 trafilatura 正文提取（仅用去标签纯文本/短片段）。默认开启。 |
| `CALL_API_MAX_RESULT_CHARS` | 返回给模型的正文最大字符数，默认 `50000`。 |
| `CALL_API_HTML_PLAINTEXT_MAX_CHARS` | trafilatura 未命中时，去标签纯文本回退的最大长度，默认 `6000`。 |
| `CALL_API_MIN_PLAINTEXT_CHARS` | 纯文本回退至少多长才采用（避免壳页面无文案仍占篇幅），默认 `80`。 |
| `CALL_API_MAX_HTML_RAW_SNIPPET_CHARS` | 连纯文本都过短时，附带的原始 HTML 调试片段上限（避免 UI 气泡撑满屏），默认 `900`。 |

## 快速开始

```bash
python -m venv venv
# Windows: venv\Scripts\activate
pip install -r requirements.txt
# 复制并编辑 .env，至少设置模型 Key 与 AUTH_SECRET
cp .env.example .env
# 新建本地账号；密码会写入 SQLite hash，不要提交运行时配置文件
python manage_accounts.py add --username demo@example.com --password 'change-me'
python -m app.main
```

API 文档：`http://localhost:8000/docs`

本地运行时文件不进入 Git：`backend/.env`、`backend/config/auth_users.txt`、`backend/config/users.json`、`backend/config/auth_users.sqlite`、`backend/data/users/`。模板文件保留为 `.example`。

## 项目结构（节选）

```
backend/
├── app/
│   ├── main.py
│   ├── api/             # 路由（sessions、group_chat、settings、files、auth…）
│   ├── agent/           # Agent / 工具组装
│   ├── mcp/             # 每用户 MCP 运行时
│   └── skills/          # SkillsLoader（按用户目录缓存）
├── config/              # 仓库内默认配置与本地运行时模板
└── requirements.txt
```

## 功能概览

- 多用户隔离（磁盘路径 + `Authorization: Bearer`）
- MCP 与 Skills 按用户目录加载；技能脚本在用户工作区内执行
- ReAct / Agent 流式输出（SSE）

## 多 Skill 本地路由

- 适用场景：一个专家绑定多个 `skill_ids` 时，后端按讨论目标与最近用户消息，用 `SkillsLoader` 基于名称/描述关键词等相关度选出 skill；多 skill 且未锁定时也可由专家模型择一，失败则回退上述逻辑。
- 路由入口：`app/skills/loader.py` 的 `pick_best_skill_id_for_message` / `pick_best_skill_with_debug`。
- Skill 会话锁：群聊中专家执行 skill 后，后端会把 `skill_session_owner_id` 与 `skill_session_skill_id` 写入会话 meta；后续用户继续回复时，若未点名、未要求主持人接管、未覆盖 `next_speaker`，会跳过主持人并继续交给同一专家/skill。

### Skill 会话退出协议

- 固定字段：专家回复末尾可输出状态块 `[[SKILL_SESSION_STATE]]`，块内 JSON 使用布尔字段 `over` 表示本段 skill 会话是否结束。
- 推荐格式：在完整回复正文之后另起一段输出 `[[SKILL_SESSION_STATE]]`、`{"over": true}` 或 `{"over": false}`、`[[/SKILL_SESSION_STATE]]`；状态块会被后端解析并从展示正文中移除。
- 字段含义：`over: true` 表示当前 skill 流程已完成，应清除会话锁并交回主持人（四九）重新调度；`over: false` 表示继续保持当前专家/skill 锁，下一轮用户消息仍优先进入同一 skill 会话。
- 兼容字段：解析器也接受 `skill_session_over` 作为 `over` 的别名，且接受 `true/false` 字符串或 `0/1` 数值。
- 脚本辅助字段：脚本型 Skill 可在 stdout JSON 中输出 `skill_session_over: true|false`（兼容 `over`）让后端确定性处理会话锁。
- 冲突规则：平台按“继续优先”决策；专家状态块或脚本 stdout 任一明确为 `false` 时保留锁，没有明确 `false` 时再按专家状态块 `true`、脚本 `true`、旧标记的顺序释放锁。
- 旧版标记：正文中的 `[[SKILL_SESSION_END]]` 或 `【技能会话结束】` 仅作为兼容释放 skill 会话锁；这些标记也会从展示正文中移除。
- 注意：脚本 stdout 中的 `done` / `final` 只表示“本轮工具循环可以收束并生成最终答复”，不会直接释放群聊 Skill 会话锁。
- 用户侧退出：用户消息命中「你的任务完成了」「任务结束」「不用继续了」「到此为止」「交/还给主持人」「请主持人」「换/叫/请其他专家」「下一个专家」「退出/结束 skill/技能」等表达时，会清除当前 skill 会话锁，本轮重新进入主持人调度。

## Skill 脚本执行（run_skill_script）

- 脚本目录：`data/users/{user_id}/resources/skills/{skill_id}/scripts/`
- 支持后缀：`.py`、`.sh`、`.bash`、`.ps1`、`.cmd`、`.bat`
- 线上路径走 OpenSandbox：脚本在 `/workspace/<session_id>` 下执行，Skill 资源通过 `/skills/<skill_id>` 只读挂载。
- 调用协议：CLI-only（仅 `cli_args_json`），不再支持 `input_json`/stdin JSON
- 相对路径手册：`docs/skills/skill-script-paths.md`
- 工具返回统一 JSON 字符串：`ok/code/message/stdout/stderr/...`
- 推荐 stdout JSON 字段：`ok`、`code`、`message`、`result/text/output`，以及可选 `skill_session_over`。成功完成且不需要同一 Skill 继续处理时设 `skill_session_over: true`；仍需用户补充或确认时设 `false`。
- 内置调试命令：
  - `script_path="__list__"`：列出可执行脚本
  - `script_path="__manifest__"`：查看 `scripts/manifest.json`
  - `script_path="__describe__:<script>"`：查看单脚本元信息

### Skill 协议校验

```bash
python backend/scripts/validate_skill_cli_contract.py
```

## 多用户上线建议（默认体验补丁）

- 架构原则：所有用户共用一套 `run_skill_script` 执行器，按用户上下文访问各自 `skills/` 与 `workspace/`。
- 技能目录为每用户 `data/users/{user_id}/resources/skills/{skill_id}/`（资源中心新建或 ZIP 导入）。
- 全局兼容补丁：在工具组装层维护历史 MCP id 别名映射（如 `fetch -> linkup`），防止旧 skill 配置导致运行失败。
- 补丁边界：这类补丁属于默认体验增强，不改变“单执行器 + 多用户隔离”的架构方向。

## 接口与命名迁移（2026-03）

- 会话主入口：`/api/sessions/*`（已不再提供 `/api/group-sessions/*` 别名）
- Agent 主入口：`/api/agents/*`
- 专家资源包导入导出：`/api/dha/instances/*`
- 字段主命名：`agent_ids`、`leader_agent_id`
- 新接口不再写出 `expert_ids` 等旧别名；历史场景包和旧磁盘配置只在导入/读取边界做兼容转换。
