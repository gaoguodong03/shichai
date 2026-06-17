# 用户资源存储标准

## 1. 用户身份层

用户身份层继续使用 SQLite 也可以，但账号表必须以 `user_id` 为资源主键。

建议字段：

```text
users
  user_id TEXT PRIMARY KEY
  username TEXT UNIQUE
  email TEXT UNIQUE NULL
  password_hash TEXT
  created_at TEXT
  updated_at TEXT
  status TEXT
```

规则：

- `backend/data/users/<user_id>/` 是唯一资源目录。
- 登录名、邮箱、手机号都不能直接作为资源目录名。
- 旧邮箱目录不进入主路径兼容逻辑。
- 如需迁移旧数据，单独提供迁移脚本，并生成迁移报告。

## 2. 资源层

所有资源中心可见资源统一放在 `resources/`。

### 2.1 场景

路径：

```text
resources/scenarios/<scenario_id>/scenario.json
```

职责：

- 描述一次会话如何被组织。
- 引用专家、主持人 Skill、运行策略。
- 不复制专家、Skill、工具或模型完整内容。

示例：

```json
{
  "id": "scenario-ppt-writing-v1",
  "name": "编写PPT",
  "description": "把用户想法转成PPT大纲、配图并组装PPTX",
  "agent_ids": ["agent-ppt-guide", "agent-image"],
  "leader_agent_id": "agent-scene-host",
  "discussion_goal_example": "帮我做一个面向学生的AI工具介绍PPT",
  "host_config": {
    "skill_ids": ["group-host-ppt-writing"],
    "system_prompt": "",
    "llm_provider_id": "",
    "mcp_server_ids": [],
    "file_capabilities": {
      "read": true,
      "edit": true,
      "write": true,
      "rename": true,
      "mkdir": true,
      "list_dir": true
    },
    "url_capability": false
  },
  "runtime_policy": {
    "turn_order": "host_decides",
    "max_rounds": 8,
    "allow_user_takeover": true,
    "allowed_skill_scope": "scene_agents"
  },
  "refs": {
    "agents": [{"id": "agent-ppt-guide", "name_snapshot": "PPT引导专家"}],
    "skills": [{"id": "group-host-ppt-writing", "name_snapshot": "PPT主持技能"}],
    "tools": [],
    "models": []
  },
  "ui": {
    "avatar_url": "",
    "tags": ["PPT", "写作"],
    "sort_order": 10
  },
  "version": 1,
  "created_at": "2026-05-23T00:00:00+08:00",
  "updated_at": "2026-05-23T00:00:00+08:00"
}
```

### 2.2 专家

路径：

```text
resources/agents/<agent_id>/agent.json
```

职责：

- 描述专家角色、系统提示词、默认模型、可用 Skill 和工具。
- 专家可以引用 Skill、工具和模型，但不复制它们。

建议字段：

```json
{
  "id": "agent-ppt-guide",
  "name": "PPT引导专家",
  "role": "将用户想法收敛为PPT大纲与逐页文稿",
  "system_prompt": "你是PPT引导专家...",
  "skill_ids": ["ppt-outline-to-deck", "pptx-deck-assembler"],
  "tool_ids": [],
  "model_provider_id": "",
  "runtime_params": {
    "temperature": null,
    "max_tokens": null
  },
  "file_capabilities": {
    "read": true,
    "edit": true,
    "write": true,
    "rename": true,
    "mkdir": true,
    "list_dir": true
  },
  "url_capability": false,
  "avatar_url": "/expert-avatars/expert-05.png",
  "version": 1,
  "created_at": "2026-05-23T00:00:00+08:00",
  "updated_at": "2026-05-23T00:00:00+08:00"
}
```

`temperature` 等模型参数属于专家、场景或运行时策略，不作为 Skill 的强绑定字段。Skill 可以给建议值，但不能强制全局生效。

### 2.3 Skill

路径：

```text
resources/skills/<skill_id>/
  SKILL.md
  scripts/
  assets/
  templates/
  other/
```

规则：

- 只有包含 `SKILL.md` 的目录才是有效 Skill。
- `scripts/` 放可执行脚本和脚本依赖文件。
- `assets/` 放图片、音频、样例数据等静态资产。
- `templates/` 放模板文件。
- `other/` 放不属于前三类但需要随 Skill 保存的文件。
- 导出 Skill 时必须保留完整目录结构。

### 2.4 工具

路径：

```text
resources/tools/<tool_id>/tool.json
```

职责：

- 保存 MCP server 或其他外部工具配置。
- 可以引用密钥，但不能保存明文密钥。

示例：

```json
{
  "id": "amap-maps",
  "name": "高德地图",
  "type": "mcp",
  "enabled": true,
  "command": "python",
  "args": ["server.py"],
  "env": {
    "AMAP_API_KEY": {"secret_ref": "amap_api_key"}
  },
  "version": 1
}
```

### 2.5 模型

路径：

```text
resources/models/<model_provider_id>/model.json
```

职责：

- 保存模型提供商、base_url、模型名和可配置参数。
- API key 只保存 `secret_ref`。

示例：

```json
{
  "id": "qwen",
  "name": "Qwen",
  "provider": "openai-compatible",
  "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "models": [
    {
      "id": "qwen-plus",
      "display_name": "Qwen Plus",
      "supports_tools": true
    }
  ],
  "api_key_ref": "qwen_api_key",
  "version": 1
}
```

## 3. 索引文件

每类资源有自己的 `index.json`。

示例：

```json
{
  "version": 1,
  "items": [
    {
      "id": "scenario-ppt-writing-v1",
      "name": "编写PPT",
      "description": "把用户想法转成PPT大纲、配图并组装PPTX",
      "avatar_url": "",
      "tags": ["PPT", "写作"],
      "sort_order": 10,
      "updated_at": "2026-05-23T00:00:00+08:00"
    }
  ]
}
```

规则：

- 列表页优先读 index。
- 详情页读取资源主体文件。
- 如果 index 缺项但资源目录存在，可以后台修复 index。
- 如果 index 有项但资源目录缺失，前端应显示缺失或跳过，后端应记录健康检查问题。

## 4. 会话层

`sessions/` 存一次真实会话的历史，不存资源模板。

路径：

```text
sessions/
  index.json
  <session_id>/
    meta.json
    messages.jsonl
    events.jsonl
    runtime_state.json
    workspace/
```

文件职责：

- `index.json`：会话列表摘要。
- `meta.json`：标题、场景、参与专家、新建时间、归档状态。
- `messages.jsonl`：聊天消息，一行一条，适合追加写。
- `events.jsonl`：SSE 事件、工具调用、错误、沙箱记录。
- `runtime_state.json`：下一轮发言者、pending owner、host plan、运行时快照。
- `workspace/`：本次会话产生的文件。

会话必须保存资源快照引用：

```json
{
  "scenario_id": "scenario-ppt-writing-v1",
  "scenario_version": 1,
  "agent_refs": [
    {"id": "agent-ppt-guide", "name_snapshot": "PPT引导专家", "version": 1}
  ],
  "skill_refs": [
    {"id": "ppt-outline-to-deck", "name_snapshot": "PPT大纲生成", "version": 1}
  ]
}
```

这样旧会话不会被后续资源改名或删除破坏展示。

## 5. 密钥层

密钥文件：

```text
vault/secrets.enc.json
```

规则：

- 明文密钥不得出现在 `resources/`、`sessions/`、导出 bundle 或沙箱挂载目录。
- 资源文件只能保存 `secret_ref`。
- 导出工具或模型时，只导出缺失密钥提示，不导出真实值。
- 沙箱运行时由后端按本轮需要注入临时环境变量。

## 6. 沙箱投影

沙箱不是用户数据目录的副本，而是一次运行的执行视图。

推荐挂载：

```text
/workspace
/skills
/runtime/config.json
```

规则：

- `/skills` 可以物理挂载当前用户全部 Skill，减少切换专家/Skill 的沙箱重建成本。
- `/skills` 必须只读或 copy-on-write。
- 本轮工具注册器只注册场景和专家允许的 Skill。
- 模型上下文只暴露本轮允许的专家、Skill 和工具。
- `vault/`、账号密码、完整用户配置不得挂载进沙箱。
- 工具调用输出写入当前 session 的 `workspace/`。

## 7. 导入导出

资源 bundle 必须包含 manifest：

```text
bundle.json
resources/
```

导入流程：

1. 解包到临时目录。
2. 读取 manifest。
3. 计算依赖图。
4. dry-run 返回将导入、将覆盖、id 重映射、缺失引用和需要密钥的内容。
5. 用户确认后写入资源目录。
6. 原子更新 index。
7. 记录导入事件。

导出规则：

- 导出场景时递归带上引用的专家、专家引用的 Skill 和工具配置。
- 导出专家时带上引用的 Skill 和工具配置。
- 导出 Skill 时带完整目录。
- 不导出 vault 中的真实密钥。

导入冲突规则：

- 目标账号导入时不使用导出方 id 判断冲突。
- 资源名称相同表示版本一致，覆盖目标账号已有资源内容并保留本地 id，包内引用映射到这个本地 id。
- 资源名称不同表示新版本或新资源，即使导出方 id 与本地 id 相同，也生成新的本地 id 后导入。

## 8. 写入和备份

所有 JSON 写入必须使用原子写：

```text
write .tmp
fsync
rename
```

关键资源更新前保留版本：

```text
.history/<resource_type>/<resource_id>/<timestamp>.json
```

最低要求：

- 保存资源不能清空其他资源。
- 注册用户不能覆盖已有资源目录。
- 导入失败不能留下半写入状态。
- 删除资源前需要更新引用快照，便于缺失提示显示原名称。

## 9. 迁移范围

不在主代码路径兼容旧邮箱目录。一次性迁移脚本负责：

- 生成新 `user_id`。
- 新建 `backend/data/users/<user_id>/`。
- 拆分旧 `config/session_presets.json` 到 `resources/scenarios/`。
- 拆分旧 `config/dha_instances.json` 到 `resources/agents/`。
- 移动旧 `skills/` 到 `resources/skills/`。
- 拆分旧 MCP 配置到 `resources/tools/`。
- 拆分旧模型配置到 `resources/models/`。
- 将密钥迁移到 `vault/secrets.enc.json`。
- 输出迁移报告。

## 10. 开发验收标准

最低验收：

- 新用户注册后新建新目录结构。
- 资源中心能列出场景、专家、Skill、工具、模型。
- 新建、编辑、删除任一资源不会破坏其他资源。
- 场景能正确解析专家、专家能正确解析 Skill。
- 删除 Skill 后，场景/专家详情能显示可读缺失引用。
- 沙箱挂载用户全部 Skill，但只注册本轮允许工具。
- 导入导出不包含明文密钥。
- 老会话历史能显示当时的专家名和场景名快照。
