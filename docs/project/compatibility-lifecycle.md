# 兼容层与回退路径清理计划

本文用于推进旧协议、旧字段、旧路径和旧数据结构的删除。当前项目口径是：主运行路径只走已规划的新接口和新数据结构；旧功能不保留长期兼容，不再为旧数据增加硬补丁判断。

## 清理原则

- 旧协议、旧字段、旧 id、旧路径默认删除。
- 如果同一功能存在两种数据结构，先反馈确认保留哪一个，再删除另一个。
- 新写入、新导入、新运行时只认当前规划结构。
- 旧数据处理不进入主运行路径；确需处理时单独写一次性迁移脚本。
- 故障容错和部署能力不要混入兼容层台账；它们需要单独说明是否保留。

## 已清理项

| ID | 清理项 | 当前结果 | 验证入口 |
| --- | --- | --- | --- |
| CC-01 | Skill 会话旧结束标记 `[[SKILL_SESSION_END]]` / `【技能会话结束】` | 不再释放 Skill 会话锁，不再从展示正文中移除，只作为普通文本 | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_group_orchestration_fsm.py -q'` |
| CC-02 | 主持人 Skill 旧目录 id 按 `skill_refs.name` 兜底解析 | 主持人 Skill 只按 `skills[].directory_name` 读取；目录名失效时不按名称搜索替代 Skill | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_host_takeover.py -q'` |
| CC-03 | `allowed-tools.python` 字符串写法 | 只接受数组；字符串不再拆行转数组 | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_skill_mcp_and_script_requirements.py -q'` |
| CC-04 | 从旧 `tool_debug.skill_session_state` 派生 `skill_result` | 只保留显式 `skill_result`；旧 `tool_debug` 不再生成新结构 | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_group_chat_state.py -q'` |
| CC-05 | MCP 配置旧运行字段 `enabled` / `status` / `tool_count` | API 创建、更新、ZIP 导入遇到旧运行字段直接返回协议错误；运行时若读到旧字段会记录 warning 后按当前配置处理 | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_frontend_business_flows.py::test_mcp_settings_rejects_legacy_runtime_fields tests/test_file_ref_and_gateway.py::test_mcp_manager_warns_and_ignores_legacy_enabled_false_when_loading_server -q'` |
| CC-06 | MCP / Skill 旧引用名、展示名、历史 server id 解析 | Skill MCP 依赖只按当前 server name 精确解析；不再按历史 id、短名包含匹配或 `reference-labels.id` 兜底 | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_mcp_skill_resolution.py tests/test_skill_mcp_and_script_requirements.py::test_get_mcp_servers_rejects_legacy_reference_label_ids -q'` |
| CC-07 | 账号文本文件 `auth_users.txt` seed 到 SQLite | 登录 / 注册 / 存在性检查不再读取文本账号文件；配置模板和 1Panel 环境不再暴露 `AUTH_USERS_FILE` | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_auth_sqlite.py tests/test_pack_1panel_backup.py -q'` |
| CC-10 | host / scheduler 旧字段 `next_prompt` 迁移到 `speaker_task` | `OrchestrationDecision` 不再输出 `next_prompt`，也不再迁移到 `speaker_task`；scheduler 归一化遇到旧字段返回协议错误；运行时只从 `speaker_task` 生成专家任务 | `rtk conda run --no-capture-output -n st49 bash -lc 'cd backend && python -m pytest tests/test_orchestration_contracts.py tests/test_scene_scheduler.py -q'` |

## 待继续删除或确认的旧兼容点

| ID | 旧兼容点 | 当前判断 | 下一步 |
| --- | --- | --- | --- |
| CC-09 | `session.json` / `history.json` / `runtime.json` 之外的会话旧结构 | 当前主路径已忽略 `meta.json`；继续扫描是否还有旧结构读取 | 保持 `test_group_chat_state.py` 的“忽略旧 meta.json”测试，发现新旧并存先反馈 |

## 不属于旧兼容的容错项

| 项 | 判断 |
| --- | --- |
| SPA fallback | 部署前端路由刷新能力，不是旧数据兼容；是否保留应按部署方式决定。 |
| HTML plaintext fallback | 外部网页格式容错，不是旧协议；是否保留应按 `call_api` 输出质量决定。 |
| LLM/tool 失败后的确定性错误摘要 | 错误恢复能力，不是旧字段兼容；可以保留，但不应掩盖协议错误。 |
| 非流式 `/api/sessions/{id}/chat` | 当前前端在 SSE 中断时用于补偿本轮回复，是产品容错入口；保留并要求复用 `/chat/stream` 的同一条编排逻辑。 |

## 删除检查清单

每删除一类旧兼容：

1. 先改测试，让旧协议被拒绝、忽略或不再产生新结构。
2. 运行目标测试确认红灯。
3. 删除运行时代码中的旧分支。
4. 运行目标测试确认绿灯。
5. 扫描文档和测试，移除旧协议示例。
6. 跑 `rtk git diff --check -- <changed paths>`。

## 当前严格结构

- Skill 会话控制：只认 `execution_status`、`result_code`、`message`、`artifacts`、`next_action.skill_session=keep|release`。
- 主持人调度：只认 `current_phase`、`next_speaker`、`speaker_task`。
- Skill Python 依赖：只认 `allowed-tools.python` 数组。
- 会话存储：只认 `session.json`、`history.json`、`runtime.json` 和 `sessions/index.json`。
- 资源身份：运行时只使用名称 / 当前目录名，不使用旧 id 兜底。
