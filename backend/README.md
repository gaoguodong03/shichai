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
# 可选：复制并编辑 .env
python -m app.main
```

API 文档：`http://localhost:8000/docs`

## 项目结构（节选）

```
backend/
├── app/
│   ├── main.py
│   ├── api/             # 路由（sessions、group_chat、settings、files、auth…）
│   ├── agent/           # Agent / 工具组装
│   ├── mcp/             # 每用户 MCP 运行时
│   └── skills/          # SkillsLoader（按用户目录缓存）
├── config/              # 仓库内默认配置示例
└── requirements.txt
```

## 功能概览

- 多用户隔离（磁盘路径 + `Authorization: Bearer`）
- MCP 与 Skills 按用户目录加载；技能脚本在用户工作区内执行
- ReAct / Agent 流式输出（SSE）

## 多 Skill 本地路由

- 适用场景：一个专家绑定多个 `skill_ids` 时，后端按讨论目标与最近用户消息，用 `SkillsLoader` 基于名称/描述关键词等相关度选出 skill；多 skill 且未锁定时也可由专家模型择一，失败则回退上述逻辑。
- 路由入口：`app/skills/loader.py` 的 `pick_best_skill_id_for_message` / `pick_best_skill_with_debug`。

## Skill 脚本执行（run_skill_script）

- 脚本目录：`data/users/{username}/skills/{skill_id}/scripts/`
- 支持后缀：`.py`、`.sh`、`.bash`、`.ps1`、`.cmd`、`.bat`
- Python 脚本使用当前解释器（如 `conda activate sc` 后的 `python`）执行
- 调用协议：CLI-only（仅 `cli_args_json`），不再支持 `input_json`/stdin JSON
- 工具返回统一 JSON 字符串：`ok/code/message/stdout/stderr/...`
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
- 技能目录为每用户 `data/users/{username}/skills/{skill_id}/`（资源中心创建或 ZIP 导入）。
- 全局兼容补丁：在工具组装层维护历史 MCP id 别名映射（如 `fetch -> linkup`），防止旧 skill 配置导致运行失败。
- 补丁边界：这类补丁属于默认体验增强，不改变“单执行器 + 多用户隔离”的架构方向。

## 接口与命名迁移（2026-03）

- 会话主入口：`/api/sessions/*`（已不再提供 `/api/group-sessions/*` 别名）
- Agent 主入口：`/api/agents/*`
- 兼容别名：`/api/dha/instances/*`、`/api/experts/*`
- 字段主命名：`agent_ids`、`leader_agent_id`
- 兼容字段：`dha_ids`、`expert_ids`、`leader_dha_id`
