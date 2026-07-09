# 资源包导入导出契约

本文定义资源中心导入导出的当前严格契约。资源包用于在账号之间复制可复用平台配置，导入语义是“让最新导入的资源可直接使用”，不是兼容旧包、合并旧字段或迁移历史会话数据。

## 1. 适用范围

资源包覆盖资源中心的五类资源：

| bundle_type | 根资源 | 递归包含 |
|-------------|--------|----------|
| `scenario` | 场景 | 场景引用的专家、专家引用的 Skill、Skill 引用的工具 |
| `agent` | 专家 | 专家引用的 Skill、Skill 引用的工具 |
| `skill` | Skill | Skill 声明的工具 |
| `tool` | 工具 | 无 |
| `model` | 模型 | 无 |

不允许 `mixed` 类型。模型另算：场景包和专家包只保留 `llm_name` 引用，不导出模型配置；只有模型包才导入导出模型配置。

资源包不覆盖：

- 会话、消息历史、运行态、`workspace/`、`checkpoints/`。
- 用户记忆、沙箱运行缓存、临时扫描结果。
- 环境变量真实值、账号凭据、用户密码。
- 旧协议、旧 id、旧目录兼容逻辑。

## 2. ZIP 结构

资源包使用资源中心镜像结构：

```text
st49-resource-bundle.zip
  bundle.json

  resources/
    scenarios/
      <scenario-dir>/
        scenario.json

    agents/
      <agent-dir>/
        agent.json

    skills/
      <skill-directory>/
        SKILL.md
        scripts/
        references/
        assets/
        templates/
        other/

    tools/
      <tool-dir>/
        tool.json

    models/
      <model-dir>/
        model.json
```

`bundle.json` 只描述包，不承载业务配置：

```json
{
  "exported_at": "2026-07-09T00:00:00Z",
  "bundle_type": "scenario",
  "root_resources": [
    { "type": "scenario", "name": "示例场景" }
  ],
  "resource_counts": {
    "scenarios": 1,
    "agents": 3,
    "skills": 5,
    "tools": 4,
    "models": 0
  }
}
```

## 3. 身份字段

导入导出按名称判断资源身份：

| 资源 | 业务身份 | 路径说明 |
|------|----------|----------|
| 场景 | `scenario.json.name` | `resources/scenarios/<scenario-dir>/` 只是落盘目录 |
| 专家 | `agent.json.name` | `resources/agents/<agent-dir>/` 只是落盘目录 |
| Skill | `SKILL.md` frontmatter `name` | `resources/skills/<skill-directory>/` 是本地执行路径 |
| 工具 | `tool.json.name` | `resources/tools/<tool-dir>/` 只是落盘目录 |
| 模型 | `model.json.name` | `resources/models/<model-dir>/` 只是落盘目录 |

禁止在资源包业务结构中出现以下字段：

- `id`
- `agent_id`
- `expert_id`
- `skill_id`
- `mcp_server_id`
- `provider_id`
- `model_id`
- `scenario_id`
- `*_ids`

目录名不是业务身份。Skill 的 `directory_name` 是执行路径字段，导入时必须根据目标账号本地目录重写引用。

## 4. 导出规则

导出前必须先校验依赖树；缺少下层依赖时禁止导出。

### 4.1 场景包

场景包必须包含：

1. 根场景。
2. 场景 `agent_names` 引用的全部专家。
3. 这些专家 `skills[].directory_name` 引用的全部 Skill。
4. 这些 Skill `allowed-tools` 声明的全部工具。

场景包不包含模型配置，只保留场景、专家中的 `llm_name` 引用。

### 4.2 专家包

专家包必须包含：

1. 根专家。
2. 专家 `skills[].directory_name` 引用的全部 Skill。
3. 这些 Skill `allowed-tools` 声明的全部工具。

专家包不包含模型配置，只保留专家中的 `llm_name` 引用。

### 4.3 Skill 包

Skill 包必须包含：

1. 根 Skill 的完整目录。
2. Skill `allowed-tools` 声明的全部工具。

### 4.4 工具包和模型包

工具包只包含工具配置。模型包只包含模型配置。模型包不得导出环境变量真实值。

## 5. 导入规则

导入必须先完整校验，再原子写入。校验失败时不得写入任何资源。

导入流程：

1. 解包到临时目录。
2. 校验 `bundle.json`、`bundle_type` 和 `resources/` 树。
3. 校验资源字段，只允许当前契约字段。
4. 校验依赖树完整性。
5. 计算同名覆盖、新增资源和 Skill 目录映射。
6. 用户确认后在临时写入区生成目标资源树。
7. 原子替换目标资源。
8. 刷新资源中心索引或缓存。

同名导入语义：

| 资源 | 同名处理 |
|------|----------|
| 场景 | 覆盖本地场景内容 |
| 专家 | 覆盖本地专家内容 |
| Skill | 保留本地目录名，删除旧目录内容，写入导入包中同名 Skill 的全部文件 |
| 工具 | 覆盖本地工具内容 |
| 模型 | 只在导入模型包时覆盖本地模型内容 |

不同名资源按当前命名规则创建新目录并写入。

## 6. Skill 目录映射

Skill 同名覆盖时必须保留目标账号的本地目录名，原因是本地其他专家可能已经引用该目录。

导入时需要生成临时 `directory_map`：

```text
包内 skill directory_name -> 目标账号本地 skill directory_name
```

这个映射只用于本次导入期间重写引用，不作为业务数据持久化。

需要重写的引用包括：

- 专家 `skills[].directory_name`
- 场景主持人配置中的 Skill 引用
- Skill frontmatter 中引用其他 Skill 或工具时涉及的本地目录字段

## 7. 环境变量边界

资源包不得包含平台内用户级环境变量真实值。

工具和模型配置中如需敏感值，只允许保存环境变量名或 `${env:NAME}` 占位。导入后目标账号必须在自己的 `settings/env.enc.json` 中配置对应环境变量。

场景、专家、Skill、工具和模型导入不得创建、覆盖或删除目标账号环境变量。

## 8. 导入摘要

导入预览和导入结果统一使用以下口径：

```text
新增 x 个，覆盖 x 个，失败 x 个
```

场景树导入需要按资源类型拆分展示：

- 场景：新增 x 个，覆盖 x 个，失败 x 个
- 专家：新增 x 个，覆盖 x 个，失败 x 个
- Skill：新增 x 个，覆盖 x 个，失败 x 个
- 工具：新增 x 个，覆盖 x 个，失败 x 个
- 模型：新增 x 个，覆盖 x 个，失败 x 个

不再使用“保留 x 个”描述同名资源。同名资源的正式语义是覆盖。

## 9. 历史数据边界

`backend/data/users` 中已有的历史数据不因导入导出契约变更而主动重写。

当前主导入导出链路只接受本文定义的当前资源包结构。旧包、旧字段、旧 id、旧目录兼容不进入主链路。如果未来确需处理历史数据，应设计一次性迁移脚本，而不是在导入、运行时或资源解析主路径中保留兜底逻辑。
