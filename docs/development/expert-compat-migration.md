# 专家命名兼容迁移说明

## 目标
将历史 `dha_*` 命名逐步迁移到 `expert_*`，同时保证现有前后端与数据可平滑运行。

## 当前兼容策略
- API 仍保留原路由：`/api/dha/instances`。
- 新增路由别名：`/api/experts`、`/api/experts/{expert_id}`。
- 会话相关接口同时兼容：
  - `dha_ids` 与 `expert_ids`
  - `add_dha_ids` 与 `add_expert_ids`
  - `remove_dha_ids` 与 `remove_expert_ids`
- 响应中增加兼容字段：
  - 专家实例：返回 `expert_id`（值等于 `dha_id`）
  - 会话列表/详情：返回 `expert_ids`（值等于 `dha_ids`）
  - 群聊详情/归档：返回 `expert_map`（值等于 `dha_map`）

## 数据兼容建议
- 存量配置暂保留 `dha_id`/`dha_ids` 作为主字段，逐步补充 `expert_id`/`expert_ids`。
- 新写入可优先使用 `expert_*`，服务端会自动回退到旧字段。

## 后续收口（下一阶段）
1. 前端请求逐步切到 `/api/experts` 与 `expert_*` 字段。
2. 后端内部变量统一为 `expert_*`，保留适配层。
3. 发布迁移窗口后，评估是否下线 `dha_*` 外部协议字段。
