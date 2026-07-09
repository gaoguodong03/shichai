# 平台内用户级环境变量契约

本文定义书童四九中“环境变量”的产品和运行时契约。这里的环境变量指 **平台内用户级环境变量**，不是宿主机进程的真实环境变量。

## 1. 统一结论

平台不再以“密钥库”“vault”或“api_key_ref”作为主抽象。模型、MCP、HTTP API、Skill 脚本和沙箱运行需要的敏感值，统一通过平台内用户级环境变量引用和注入。

| 旧口径 | 新口径 |
|--------|--------|
| 设置 -> 密钥 | 设置 -> 环境变量 |
| `settings/secrets.enc.json` | `settings/env.enc.json` |
| `/api/settings/api-secrets` | `/api/settings/env-vars` |
| `${vault:qwen}` | `${env:QWEN_API_KEY}` |
| `api_key_ref` | `api_key_env` |
| 密钥引用缺失 | 环境变量缺失 |

旧字段、旧路径和旧占位符不进入主运行时兜底。历史数据处理如果需要，应单独设计一次性迁移脚本；主代码路径按本文严格契约实现。

## 2. 存储契约

用户级环境变量按 `user_id` 隔离，保存于：

```text
backend/data/users/{user_id}/settings/env.enc.json
```

目标结构：

```json
{
  "items": {
    "QWEN_API_KEY": {
      "label": "Qwen API Key",
      "value": "明文只允许服务端读取",
      "sensitive": true
    }
  }
}
```

字段规则：

| 字段 | 规则 |
|------|------|
| `name` | 环境变量名，也是条目主键；建议使用大写字母、数字和下划线，如 `QWEN_API_KEY`。 |
| `label` | 用户界面显示名；不参与运行时查找。 |
| `value` | 真实值；只允许服务端内部读取，不返回前端、不进入资源包、不挂载进用户工作区。 |
| `value_set` | API 列表返回字段，表示是否已保存值。 |
| `sensitive` | 是否敏感；默认 `true`。敏感变量不得明文展示和导出。 |

## 3. 引用语法

资源配置中引用用户级环境变量时，统一使用：

```text
${env:VARIABLE_NAME}
```

适用位置：

- MCP `server_config.mcpServers.*.env`、SSE / HTTP headers 和 URL。
- 保存型 HTTP API 的 header、query、body 和 URL 配置。
- 模型配置的 `api_key_env`。
- Skill 脚本和沙箱运行前声明需要注入的环境变量。

禁止作为主契约继续使用：

```text
${vault:secret_id}
api_key_ref
secret_ref
settings/secrets.enc.json
/api/settings/api-secrets
```

## 4. 解析顺序

运行时解析某个变量名时，顺序为：

1. 当前用户 `settings/env.enc.json` 中的同名变量。
2. 宿主机进程环境变量 `os.environ` 中的同名变量。
3. 若仍不存在，返回明确的“缺少环境变量 `<NAME>`”诊断。

宿主机 `.env` 只属于部署级默认值和后端自身配置，不是产品主契约。用户级环境变量优先于宿主机变量，以保证多用户隔离和资源包迁移语义稳定。

## 5. 注入边界

运行时不得把用户的全部环境变量无条件注入给模型、MCP 子进程、HTTP 工具、Skill 脚本或沙箱。注入必须按本轮资源配置、Skill 声明和工具配置中显式引用到的变量收敛。

| 运行单元 | 注入规则 |
|----------|----------|
| LLM Provider | 读取模型配置中的 `api_key_env`，解析后传给 LLM 客户端。 |
| MCP stdio | 只把 `server_config.mcpServers.*.env` 中声明的变量传给子进程。 |
| MCP SSE / HTTP | 只替换 URL 和 headers 中的 `${env:...}`。 |
| 保存型 HTTP API | 只替换配置中出现的 `${env:...}`。 |
| Skill 脚本 | 只注入平台固定 Skill 变量和当前任务显式允许的用户级环境变量。 |
| 沙箱 | 不挂载 `settings/env.enc.json`；由后端把本轮需要的变量作为临时命令环境注入。 |

## 6. 导入导出

资源包只导出环境变量引用名，不导出真实值。

示例：

```json
{
  "server_config": {
    "mcpServers": {
      "exa-search": {
        "command": "npx",
        "args": ["-y", "exa-mcp-server"],
        "env": {
          "EXA_API_KEY": "${env:EXA_API_KEY}"
        }
      }
    }
  }
}
```

导入时如果目标用户缺少对应变量，导入预览和运行时诊断都应提示“缺少环境变量”。导入资源包不得创建、覆盖或删除目标账号的环境变量。

## 7. 文档和代码变更规则

涉及环境变量契约时，必须同步检查：

1. `docs/contracts/data-structure-and-field-logic.md`
2. `docs/design/interface-document.md`
3. `docs/design/detailed-design-spec.md`
4. `docs/requirements/user-requirements.md`
5. `docs/requirements/acceptance-and-tests.md`
6. `docs/architecture/scenario-bundle-export.md`
7. `docs/architecture/user-resource-store/storage-standard.md`
8. `docs/user-manual/`
9. `docs/skills/`
10. 前端 mock、E2E、后端 API 测试和导入导出测试

如果代码或测试仍出现 `vault`、`api_key_ref`、`api-secrets` 或 `settings/secrets.enc.json`，应视为旧契约残留，而不是兼容分支。
