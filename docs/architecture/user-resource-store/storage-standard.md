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
  "agent_names": ["PPT引导专家", "图片生成专家"],
  "discussion_goal_example": "帮我做一个面向学生的AI工具介绍PPT",
  "host": {
    "name": "四九",
    "skill_name": "PPT主持技能",
    "skill_directory": "group-host-ppt-writing",
    "system_prompt": "",
    "llm_name": "",
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
    "agents": [{"name": "PPT引导专家"}],
    "skills": [{"name": "PPT主持技能", "directory_name": "group-host-ppt-writing"}],
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
resources/agents/<agent_name>/agent.json
```

职责：

- 描述专家角色、系统提示词、默认模型、可用 Skill 和工具。
- 专家可以引用 Skill、工具和模型，但不复制它们。

建议字段：

```json
{
  "name": "PPT引导专家",
  "role": "将用户想法收敛为PPT大纲与逐页文稿",
  "system_prompt": "你是PPT引导专家...",
  "skills": [
    {"name": "PPT大纲生成", "directory_name": "ppt-outline-to-deck"},
    {"name": "PPTX 组装", "directory_name": "pptx-deck-assembler"}
  ],
  "tool_ids": [],
  "llm_name": "",
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
resources/skills/<directory_name>/
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
- 可以引用平台内用户级环境变量，但不能保存变量真实值。

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
    "AMAP_API_KEY": "${env:AMAP_API_KEY}"
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
- API key 只保存 `api_key_env` 环境变量名。

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
  "api_key_env": "QWEN_API_KEY",
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
  <session_id>/
    session.json
    history.json
    runtime.json
    orchestration_state.json
    workspace/
    memory/
    checkpoints/
```

文件职责：

- `session.json`：会话主信息，包括标题、自动标题开关、参与专家、主持人快照和时间戳。
- `history.json`：聊天消息。
- `runtime.json`：UI 恢复镜像，只保存前端显示和停止运行需要的字段。
- `orchestration_state.json`：刷新不能丢的短期编排状态。
- `workspace/`：本次会话产生的文件。
- `memory/`：本次会话内部记忆状态。
- `checkpoints/`：会话检查点、对象存储和回滚链。

会话必须保存运行所需的主信息：

```json
{
  "title": "新对话",
  "title_auto_generated": true,
  "agent_names": ["PPT引导专家", "图片生成专家"],
  "host": {
    "name": "四九",
    "llm_name": "",
    "system_prompt": "",
    "skill_directory": "group-host-ppt-writing"
  },
  "created_at": "2026070812000000",
  "updated_at": "2026070812050000"
}
```

场景资源只在创建会话时作为初始化模板使用；创建后会话不再保存 `scenario_name`，也不通过场景资源解析主持人。

## 5. 设置与环境变量层

账号级设置文件：

```text
settings/app.json
settings/env.enc.json
settings/sandbox/requirements.txt
```

规则：

- 环境变量真实值不得出现在 `resources/`、`sessions/`、导出 bundle 或沙箱挂载目录。
- 资源文件只能保存 `api_key_env` 或 `${env:NAME}`。
- 导出工具或模型时，只导出缺失环境变量提示，不导出真实值。
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
- `settings/env.enc.json`、账号密码、完整用户配置不得挂载进沙箱。
- 工具调用输出写入当前 session 的 `workspace/`。

## 7. 导入导出

资源包用于复制资源中心配置，使用资源中心镜像结构：

```text
bundle.json
resources/
  scenarios/
  agents/
  skills/
  tools/
  models/
```

`bundle.json` 只描述包，不承载业务配置。`bundle_type` 只允许 `scenario`、`agent`、`skill`、`tool`、`model`，不允许 `mixed`。

导入流程：

1. 解包到临时目录。
2. 读取 `bundle.json`。
3. 校验资源字段和依赖树。
4. dry-run 返回将新增、将覆盖和需要补环境变量的内容。
5. 用户确认后在临时写入区生成目标资源树。
6. 原子替换目标资源目录并更新索引。
7. 记录导入事件。

导出规则：

- 导出场景时递归带上引用的专家、专家引用的 Skill、Skill 引用的工具配置。
- 导出专家时递归带上引用的 Skill 和 Skill 引用的工具配置。
- 导出 Skill 时带完整 Skill 目录和 Skill 引用的工具配置。
- 导出工具时只带工具配置。
- 导出模型时只带模型配置。
- 场景包和专家包只保留 `llm_name`，不导出模型配置。
- 不导出 `settings/env.enc.json` 中的环境变量真实值。
- 导出前发现下层依赖缺失时禁止导出。

导入冲突规则：

- 目标账号导入时不使用导出方 id 判断冲突。
- 资源身份统一使用名称：场景 `name`、专家 `name`、Skill frontmatter `name`、工具 `name`、模型 `name`。
- 同名资源表示覆盖本地资源内容。
- Skill 同名覆盖时保留本地目录名，删除旧目录内容，再写入导入包中同名 Skill 的完整目录。
- 不同名资源按当前命名规则创建新目录并写入。
- 导入期间可以生成临时 Skill 目录映射，用于把包内 `directory_name` 重写为目标账号本地目录名；该映射不持久化为业务数据。
- 导入摘要统一使用“新增 x 个，覆盖 x 个，失败 x 个”，不再使用“保留 x 个”。
- 旧包、旧 id、旧字段、旧目录兼容不进入主导入链路；历史数据处理应单独设计一次性迁移脚本。

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

## 9. 旧数据处理

主代码路径不保留旧邮箱目录、旧 `config/`、旧 `vault/`、旧用户级对象库或 legacy session 目录的读取兼容。当前实现按新结构直接初始化和写入；已有旧数据按本轮重构决策直接清理，不在运行时自动迁移。

新写入的数据只进入：

- `resources/scenarios/`
- `resources/agents/`
- `resources/skills/`
- `resources/tools/`
- `resources/models/`
- `settings/app.json`
- `settings/env.enc.json`
- `settings/sandbox/requirements.txt`
- `sessions/{session_id}/...`

## 10. 开发验收标准

最低验收：

- 新用户注册后新建新目录结构。
- 资源中心能列出场景、专家、Skill、工具、模型。
- 新建、编辑、删除任一资源不会破坏其他资源。
- 场景能正确解析专家、专家能正确解析 Skill。
- 删除 Skill 后，场景/专家详情能显示可读缺失引用。
- 沙箱挂载用户全部 Skill，但只注册本轮允许工具。
- 导入导出不包含环境变量真实值。
- 老会话历史能显示当时的专家名和场景名快照。
