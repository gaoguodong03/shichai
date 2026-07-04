# 会话存储结构重设计

日期：2026-07-04

## 背景

当前会话目录把会话配置、运行态、跨请求续跑状态和消息控制结果混在 `meta.json` / `history.json` 中。典型问题是：

- `meta.json` 名称不准确，实际同时保存会话定义和运行中状态。
- `leader_agent_name` 与 `host_config.leader_agent_name` 形成历史包袱；产品已确定会话由主持人体系统一调度，不再支持专家充当主持人。
- `host_config` 在会话层保存主持人模型、提示词和 Skill，容易复制资源中心事实源。
- `runtime_state` 是运行镜像，却和会话配置并列。
- `pending_*` / `skill_session_*` 是运行推导结果，存入会话配置后容易与历史消息不一致。
- `history.json` 使用 `role: assistant` 等 LLM 格式字段，不符合平台自己的会话消息模型。

本设计目标是把会话存储拆成清晰的三类事实源：会话定义、消息历史、运行镜像。

## 目标

1. 会话配置只保存用户可理解的元数据和资源引用。
2. 主持人、专家、Skill、模型、提示词的详细配置统一从资源中心或账号设置解析。
3. 跨轮 Skill 流程控制以消息历史为事实源，而不是以会话配置中的锁字段为事实源。
4. 浏览器刷新后仍能恢复运行中 UI，并重新接入当前进程内仍在执行的任务。
5. 后端进程重启后不声明可续跑任务；运行镜像可被识别为 stale 并清理。

## 非目标

- 不在本次设计中引入持久任务队列、worker 或重启后续跑能力。
- 不把专家 Skill、模型、工具权限快照复制进会话定义。
- 不保留新的 `next_turn` 持久字段；下一轮路由由后端实时推导。
- 不继续把 `required_user_fields`、`handoff_reason`、`result_code`、`source` 作为核心协议字段。

## 目录结构

新会话目录结构：

```text
sessions/{session_id}/
  session.json
  history.json
  runtime.json
  workspace/
  checkpoints/
```

职责：

- `session.json`：会话定义和资源引用。
- `history.json`：消息事实、工具结果、Skill 流程控制结果。
- `runtime.json`：当前运行镜像，仅用于刷新恢复和运行中 UI。

`meta.json` 不再作为新协议文件名使用。

## session.json

推荐结构：

```json
{
  "title": "新对话",
  "title_auto_generated": true,
  "created_at": "2026062908104800",
  "updated_at": "2026062908104800",
  "orchestration_profile": "scene",
  "scenario_name": "场景名称",
  "agent_names": ["专家名称"],
  "system_prompt": "会话级系统提示词"
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `title` | 会话标题，用于会话列表展示。 |
| `title_auto_generated` | 标题是否仍允许后端自动生成或覆盖。 |
| `created_at` | 创建时间，格式为 `YYYYMMDDHHmmssSS`。 |
| `updated_at` | 更新时间，格式为 `YYYYMMDDHHmmssSS`。 |
| `orchestration_profile` | 编排模式，取值为 `scene` 或 `recruitment`。 |
| `scenario_name` | 场景引用。`scene` 模式下用于解析场景主持人配置和场景规则；空会话可为空。 |
| `agent_names` | 当前参与会话的专家名称列表，仅保存引用。 |
| `system_prompt` | 会话级系统提示词，直接作为顶层字段。 |

明确删除：

- `leader_agent_name`
- `host_config`
- `runtime_state`
- `pending_owner_agent_name`
- `pending_skill`
- `pending_phase`
- `pending_required_user_fields`
- `pending_handoff_reason`
- `skill_session_owner_name`
- `skill_session_skill`
- `context.system_prompt`

## 主持人解析规则

会话文件不保存主持人模型、主持人提示词、主持人 Skill 或主持人显示名。

后端按以下规则解析：

1. `orchestration_profile=scene` 且 `scenario_name` 非空时，从资源中心读取对应场景。
2. 场景资源提供场景主持人的 Skill、LLM、提示词和默认专家配置。
3. `orchestration_profile=recruitment` 时，加载账号级通用主持人配置。
4. `agent_names` 只表示当前会话参与专家；专家详情、模型、Skill 和工具权限均按名称从资源中心实时解析。

这样可以避免会话文件和资源中心形成两个真相源。

## runtime.json

推荐结构：

```json
{
  "running": true,
  "run_id": "run-id",
  "phase": "tool_running",
  "agent_name": "专家名称",
  "skill": "skill-directory",
  "started_at": "2026062908104800",
  "updated_at": "2026062908104800"
}
```

字段说明：

| 字段 | 含义 |
|------|------|
| `running` | 当前会话是否有运行中的后端任务。 |
| `run_id` | 当前运行编号。 |
| `phase` | 运行阶段，例如 `routing`、`agent_waiting`、`tool_running`、`finalizing`。 |
| `agent_name` | 当前正在执行的专家名称。 |
| `skill` | 当前正在执行的 Skill 目录名。 |
| `started_at` | 本轮运行开始时间。 |
| `updated_at` | 运行镜像更新时间。 |

边界：

- `runtime.json` 是运行镜像，不是任务队列。
- 浏览器刷新后可用它恢复运行中状态，并重新订阅事件流。
- 后端进程重启后，内存中的 `asyncio.Task` 已丢失，不能续跑；后端应识别 stale runtime 并清理。
- 编排决策不依赖 `runtime.json`。

## history.json

消息结构从 LLM 角色格式改为平台业务消息格式。

专家消息示例：

```json
{
  "message_id": "msg-xxxx",
  "speaker": {
    "type": "expert",
    "agent_name": "专家名称",
    "skill": "skill-directory"
  },
  "content": "展示给用户的正文",
  "created_at": "2026062908104800",
  "skill_result": {
    "execution_status": "succeeded",
    "next_action": {
      "agent_turn": "respond",
      "skill_session": "release"
    }
  },
  "tool_raw_results": [],
  "tool_debug": {}
}
```

用户消息示例：

```json
{
  "message_id": "msg-xxxx",
  "speaker": {
    "type": "user"
  },
  "content": "用户输入",
  "created_at": "2026062908104800"
}
```

主持人消息示例：

```json
{
  "message_id": "msg-xxxx",
  "speaker": {
    "type": "host"
  },
  "content": "主持人回复",
  "created_at": "2026062908104800"
}
```

核心规则：

- 不再保存 `role: assistant` 作为新协议字段。
- `skill_result.execution_status` 保留 `succeeded`、`blocked`、`failed`。
- `skill_result.next_action.agent_turn` 保留 `respond`、`continue`。
- `skill_result.next_action.skill_session` 保留 `keep`、`release`。
- `source`、`result_code`、`required_user_fields`、`handoff_reason` 不进入核心协议字段。
- 如需排查来源或业务码，可统一放入 `debug`，不参与核心编排判断。

## 跨轮路由推导

不持久化 `next_turn`。

每次用户请求进入时，后端实时推导入口路由，输入包括：

1. 当前用户消息，例如是否 `@`、点名专家、要求主持人接管。
2. `session.json` 中的 `orchestration_profile`、`scenario_name` 和 `agent_names`。
3. `history.json` 中最后一个有效专家消息的 `skill_result.next_action.skill_session`。
4. 当前资源中心中专家、Skill、场景和主持人配置是否仍然存在。

推导规则：

- 最近有效专家消息为 `skill_session=keep` 时，下一条用户消息默认直达同一专家和同一 Skill。
- 最近有效专家消息为 `skill_session=release` 时，下一条用户消息交回主持人或普通入口路由。
- 用户显式点名、`@`、要求主持人接管、专家已删除、Skill 已删除时，运行时推导可以覆盖历史 Skill 控制结果。
- 回滚历史后，Skill 会话状态自然跟随 `history.json` 变化，无需额外修复会话配置。

## 时间格式

新协议统一使用固定宽度字符串：

```text
YYYYMMDDHHmmssSS
2026062908104800
```

说明：

- `YYYY` 年。
- `MM` 月。
- `DD` 日。
- `HHmmss` 时分秒。
- `SS` 百分之一秒。

时间字段必须可按字符串排序。实现时需要统一时区；推荐使用服务端配置时区，当前部署默认按 `Asia/Shanghai` 生成。

## API 兼容策略

实现阶段应保留读旧数据能力：

- 旧 `meta.json` 读入后映射为新 `session.json` 响应结构。
- 旧 `runtime_state` 读入后映射为 `runtime.json` 或运行态响应。
- 旧 `pending_*` / `skill_session_*` 不再作为新写入字段；迁移时优先从 `history.json` 推导。
- 旧消息中的 `role`、`agent_name`、`skill` 可在读取时转换为 `speaker`。

新写入只写新结构。兼容层用于读取旧会话，不作为长期新协议。

## 实现影响范围

后端：

- 会话路径与读写：`backend/app/api/group_chat_state.py`、`backend/app/session_state/paths.py`、`backend/app/session_state/service.py`。
- 会话 API：`backend/app/api/sessions.py`、`backend/app/agent/group_session_service.py`。
- 群聊运行时：`backend/app/agent/group_chat_runtime.py`、`backend/app/agent/group_chat_skill_session.py`、`backend/app/agent/expert_runtime.py`。
- 主持人和场景解析：`backend/app/agent/scene_runtime.py`、`backend/app/agent/group_chat_host_runtime.py`。
- Skill 状态解析：`backend/app/agent/skill_session_contract.py`、`backend/app/agent/structured_output_contracts.py`。

前端：

- 会话列表与详情类型。
- 群聊消息渲染从 `role` / `agent_name` / `skill` 迁移到 `speaker`。
- 运行态恢复从会话响应中的 `runtime_state` 迁移到新的运行态响应形态。
- SSE 事件仍可保留现有事件类型，但 payload 需要逐步切到新结构。

文档：

- `docs/architecture/data-structure-and-field-logic.md`
- `docs/architecture/interface-map.md`
- `docs/architecture/session-modes.md`
- `docs/skills/skill-session-flow.md`
- `docs/skills/skill-standard.md`

## 验收标准

1. 新建会话只生成 `session.json`、`history.json` 和按需生成 `runtime.json`。
2. 新写入的 `session.json` 不包含 `leader_agent_name`、`host_config`、`runtime_state`、`pending_*`、`skill_session_*`。
3. 场景会话可以通过 `scenario_name` 正确解析主持人 Skill、LLM、提示词和参与专家。
4. 招募会话可以加载通用主持人配置。
5. 专家 Skill 的 `keep` / `release` 从 `history.json` 的 `skill_result.next_action.skill_session` 推导。
6. 删除或回滚消息后，跨轮 Skill 路由跟随历史自然变化。
7. 浏览器刷新后，在后端进程未重启的情况下可以恢复运行中提示并继续同步消息。
8. 后端进程重启后 stale `runtime.json` 不会让前端永久显示运行中。
9. 旧会话可读取，且新请求写回时使用新结构。

## 风险

- 字段迁移跨度大，后端、前端、文档和测试必须同步修改。
- `history.json` 成为 Skill 锁事实源后，最后有效专家消息的查找规则必须明确并有测试覆盖。
- 时间格式切换会影响排序、展示和测试断言。
- 如果读取兼容层过厚，可能延长旧字段生命周期；实现计划应明确兼容边界和清理点。
