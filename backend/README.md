# 书童四九 · 后端

FastAPI 服务：统一会话流、Agent 配置、每用户 MCP / Skills、工作区文件 API。

## 环境变量（节选）

| 变量 | 说明 |
|------|------|
| `SHUTONG_USER_DATA_ROOT` | 用户数据根目录，默认 `backend/data/users`；每个用户独占 `data/users/{username}/`（会话、工作区、配置、技能副本）。旧名 `SHICHAI_USER_DATA_ROOT` 已废弃。 |
| `AUTH_SECRET` | JWT 签名密钥，生产环境务必修改。 |
| `ALLOW_ANONYMOUS_API` | 设为 `1` 时允许无 Bearer 访问（仅本地调试，**禁止**用于生产）。 |
| `QWEN_API_KEY` 等 | 部署级默认环境变量；产品内主契约是应用内「设置 → 环境变量」。 |
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
# 复制并编辑 .env，至少设置部署级默认模型环境变量与 AUTH_SECRET
cp .env.example .env
# 新建本地账号；密码会写入 SQLite hash，不要提交运行时配置文件
python manage_accounts.py add --username demo@example.com --password 'change-me'
python -m app.main
```

API 文档：`http://localhost:8000/docs`

本地运行时文件不进入 Git：`backend/.env`、`backend/config/users.json`、`backend/config/auth_users.sqlite`、`backend/data/users/`。模板文件保留为 `.example`。

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

- 适用场景：一个专家绑定多个 Skill 目录时，后端使用专家 LLM 严格输出本轮唯一 `selected_skill`；单 Skill 直接使用该 Skill，选型失败则按协议阻塞本轮专家执行。
- 路由入口：`app/agent/expert_runtime.py` 的 `resolve_expert_skill()` / `expert_llm_pick_skill()`。
- Skill 接续：群聊中专家执行 Skill 后，后端从消息级 `skill_result.next_action.skill_session` 推导是否写入 `orchestration_state.json.continuation`；后续用户继续回复时，只在 `skill_session=keep` 且未被主持人调度覆盖时接回同一专家和 Skill。

### Skill 会话退出协议

- 固定字段：脚本型 Skill 的 stdout JSON 必须输出 `execution_status`、`content`、`artifacts`、`next_action`。
- 会话字段：`next_action.agent_turn` 只允许 `respond` 或 `continue`；`next_action.skill_session` 只允许 `keep` 或 `release`。
- 字段含义：`skill_session=release` 表示下一条用户消息不再锁定当前 Skill；`skill_session=keep` 表示下一条用户消息优先接回同一专家和 Skill。`agent_turn` 只控制当前专家本轮是否继续行动，两个维度互不替代。
- 专家正文状态块：非脚本 Skill、MCP / HTTP / workspace 工具后的流程判断来自专家最终回复末尾的 `[[SKILL_SESSION_STATE]] ... [[/SKILL_SESSION_STATE]]` 隐藏状态块，状态块会被后端解析并从展示正文中移除。
- 严格协议：旧字段和旧标记不再参与会话锁控制；正文中的 `[[SKILL_SESSION_END]]`、`【技能会话结束】` 只会被当作普通文本。
- 注意：脚本 stdout 中的 `done` / `final` 只表示“本轮工具循环可以收束并生成最终答复”，不会释放群聊 Skill 会话锁。
- 主持人接管：用户明确要求主持人接管时，运行时清理短期接续状态并重新进入主持人调度。

## Skill 脚本执行（run_skill_script）

- 脚本目录：`data/users/{user_id}/resources/skills/{directory_name}/scripts/`
- 支持后缀：`.py`、`.sh`、`.bash`、`.ps1`、`.cmd`、`.bat`
- 线上路径走 OpenSandbox：脚本在 `/workspace/<session_id>` 下执行，Skill 资源通过 `/skills/<directory_name>` 只读挂载。
- 调用协议：当前运行时工具使用结构化参数调用脚本；脚本 stdout 必须遵守当前 Skill 结果契约。
- 相对路径手册：`docs/skills/skill-script-paths.md`
- 工具返回统一 JSON 字符串：`ok/code/message/stdout/stderr/...`
- stdout JSON 字段：`execution_status`、`content`、`artifacts`、`next_action`。成功完成且不需要同一 Skill 继续处理时设 `next_action.skill_session: "release"`；仍需用户补充或确认时设 `"keep"`。

### Skill 协议校验

```bash
python backend/scripts/validate_skill_cli_contract.py
```

## 多用户上线建议（默认体验补丁）

- 架构原则：所有用户共用一套 `run_skill_script` 执行器，按用户上下文访问各自 `skills/` 与 `workspace/`。
- 技能目录为每用户 `data/users/{user_id}/resources/skills/{directory_name}/`（资源中心新建或 ZIP 导入）。
- 工具权限边界：当前 Skill 的 `allowed-tools.mcp` / `allowed-tools.http_api` 决定本轮外部工具集合；工作区工具是平台默认能力。
- 旧数据处理：历史数据兼容应通过单独迁移或清理处理，不写进运行时主路径。

## 接口与命名迁移（2026-03）

- 会话主入口：`/api/sessions/*`（已不再提供 `/api/group-sessions/*` 别名）
- Agent 主入口：`/api/agents/*`
- 专家资源包导入导出：`/api/dha/instances/*`
- 字段主命名：`agent_names`、`host.name`、`host.skill_directory`、`target_agent_name`
- 新接口只写出 name-based 字段；旧字段不进入运行时主路径。
