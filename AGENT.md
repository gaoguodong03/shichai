# AGENT 交接记录

更新时间：2026-05-12

## 项目协作约定

- 项目根目录：`/Users/ggd/project/shichai`。
- 优先使用 `rtk` 执行命令；当前可用路径为 `/Users/ggd/.local/bin/rtk`。
- 后端验证统一使用 conda 环境：`conda run -n st49 bash -lc '...'`。
- 完成后执行 `git commit`，使用中文写较为详细的 commit 记录。
- 运行测试后需要清理 `backend` 下生成的 `__pycache__` / `.pyc`。
- 不要删除 `frontend/package-lock.json`。

## 当前模块化进展

### 后端入口与核心模块

- `backend/app/main.py` 已是薄入口，负责 `create_app`、CORS、health、静态挂载和启动。
- 路由集中注册在 `backend/app/api/routes.py`。
- 已拆出：
  - `backend/app/core/runtime_env.py`
  - `backend/app/core/lifespan.py`
  - `backend/app/core/static_spa.py`
  - `backend/app/core/dev_bootstrap.py`

### settings 路由拆分状态

`backend/app/api/settings.py` 已移除，设置相关路由直接由拆分后的模块注册：

- `backend/app/api/settings_app.py`
  - `/settings/app`
  - `/settings/host-profile*`
  - `load_app_settings` / `save_app_settings` / `normalize_host_profile`
- `backend/app/api/settings_secrets.py`
  - `/settings/api-secrets*`
  - API secrets 原始读写与 value 读取
- `backend/app/api/settings_mcp.py`
  - `/settings/mcp*`
  - MCP CRUD、测试、工具列表、工具调用、sandbox-call、分享发布
- `backend/app/api/settings_skills.py`
  - `/settings/skills*`
  - Skill CRUD、zip 导入导出、share 导入、requirements 合并
- `backend/app/api/settings_skill_store.py`
  - Skill 文件读写、目录定位、MCP 引用校验等存储 helper
- `backend/app/api/settings_skill_parts.py`
  - Skill 分片文件与目录管理路由
- `backend/app/api/settings_presets.py`
  - `/settings/session-presets*`
  - 场景预设、场景包导入导出、分享包导入
- `backend/app/api/sandbox_settings.py`
  - `/settings/sandbox`
  - `/settings/sandbox/requirements*`
- `backend/app/core/user_settings_paths.py`
  - 用户级配置路径公共 helper
- `backend/app/core/settings_references.py`
  - Skill / MCP / session preset 引用 remap
  - `replace_skill_id_in_user_configs`
  - `replace_mcp_server_id_in_user_configs`
  - `remove_skill_id_from_user_configs`
- `backend/app/core/settings_bundle_import.py`
  - bundle 导入时的 Skill/MCP 冲突检测
  - `copy_bundle_skills_to_user_by_name`

下一步建议：继续收敛 `settings_skills.py` 与 `settings_presets.py` 内部的 bundle 编排逻辑，但要谨慎处理 Skill、MCP、Agent、session preset 之间的交叉引用。

## 沙箱当前业务链路

主要执行链路：

1. Skill 工具入口：`backend/app/tools/run_skill_script.py`
2. 统一网关：`backend/app/agent/tool_gateway.py`
3. 沙箱服务：`backend/app/agent/sandbox_service.py`
4. OpenSandbox 适配：`backend/app/agent/sandbox_adapter.py`
5. 用户沙箱设置：`backend/app/api/sandbox_settings.py`
6. 用户镜像策略：`backend/app/agent/sandbox_image_policy.py`
7. 挂载策略：`backend/app/agent/sandbox_mount_policy.py`

核心行为：

- 用户级单沙箱复用，cache key 为 `user_id`。
- 沙箱挂载用户自己的 `agent-outputs/workspaces` 到 `/workspace`。
- 沙箱挂载用户自己的 `skills` 到 `/skills`，只读。
- Skill 脚本执行统一走 OpenSandbox，不再宿主机 subprocess 兜底。
- `run_skill_script` 新建工具时绑定 `owner_user_id`，执行时不再回退默认用户。
- 缺用户上下文时返回 `missing_user_context`。
- 用户 `config/sandbox/requirements.txt` 会：
  - 保存/merge 后触发 prewarm；
  - 沙箱执行前注入 `SKILL_REQUIREMENTS_B64`；
  - 沙箱内按 hash 安装并验证；
  - 空 requirements 也写入 verified hash，避免反复误判。

## 已修复的关键沙箱问题

### requirements 注入与安装

相关文件：

- `backend/app/tools/run_skill_script.py`
- `backend/app/agent/sandbox_service.py`

已做过的修复：

- `create_run_skill_script_tool` 绑定 `owner_user_id`。
- `_current_user_requirements_b64(user_id)` 优先使用显式 user id。
- `SandboxService._prepare_command_env` 在执行命令前兜底注入 `SKILL_REQUIREMENTS_B64`。
- 空 requirements 会写入：
  - `installed_requirements_hash`
  - `verified_requirements_hash`
  - `requirements_verifier_version`
- 新增大量结构化日志，关键词包括：
  - `st49_skill_script_execute_start`
  - `st49_skill_script_execute_done`
  - `st49_skill_script_execute_nonzero`
  - `st49_skill_script_execute_failed`
  - `st49_skill_env_passthrough`
  - `st49_sandbox_command_env_injected`
  - `st49_sandbox_command_env_present`
  - `st49_sandbox_command_env_empty`
  - `st49_sandbox_requirements_loaded`
  - `st49_sandbox_requirements_check`
  - `st49_sandbox_requirements_install_start`
  - `st49_sandbox_requirements_install_done`
  - `st49_sandbox_requirements_install_failed`

### 沙箱复用策略修复

相关文件：

- `backend/app/agent/sandbox_service.py`
- `backend/tests/test_sandbox_service.py`

已修复：用户沙箱复用现在额外检查：

- requirements hash
- verified requirements hash
- verifier version
- image ref
- mount fingerprint
- network policy (`allow_network`)

避免禁网沙箱被错误复用于需联网策略，或挂载策略变化后继续复用旧沙箱。

对应测试：

- `test_cached_user_sandbox_recreated_when_network_policy_changes`

## 线上沙箱仍需重点排查的问题

线上沙箱一直出问题，建议新对话优先排查以下方向：

1. OpenSandbox lifecycle 是否可达
   - 检查 `OPENSANDBOX_DOMAIN` / `OPEN_SANDBOX_DOMAIN`
   - 检查 `OPENSANDBOX_PROTOCOL`
   - 检查 `OPENSANDBOX_USE_SERVER_PROXY`
   - 检查 `opensandbox-server` 容器健康状态

2. OpenSandbox execd endpoint 是否为空
   - 日志关键词：`opensandbox_execd_endpoint_empty`
   - endpoint 为空时命令通道可能可用，但 FilesystemAdapter 不可用。
   - 大文件写入 fallback 有约 200KB 限制，仍需要修复 endpoint。

3. 容器内/宿主机地址映射
   - 本地可能需要 `127.0.0.1:8091`。
   - 容器内常需要 `host.docker.internal:8091`。
   - Linux Docker 常需要 `extra_hosts: host.docker.internal:host-gateway`。

4. 挂载路径映射
   - 检查 `SANDBOX_HOST_PATH_MAP`。
   - OpenSandbox 所在宿主机必须能看到挂载源路径。
   - 重点看 `/workspace` 和 `/skills` 是否真实挂载。

5. 镜像选择
   - 默认镜像在 `backend/app/agent/sandbox_image_policy.py`。
   - 普通版：`standard`
   - 浏览器版：`playwright`
   - 可通过 `/settings/sandbox` 保存后触发 prewarm。

6. requirements 安装网络
   - requirements 非空时 prewarm 会打开 network policy。
   - 如果 pip 安装失败，看日志：
     - `requirements_install_nonzero`
     - `requirements_install_exception`
   - 注意国内网络/镜像源可能导致 pip 超时。

7. Skill 脚本执行超时
   - `SKILL_SCRIPT_TIMEOUT` 控制脚本超时。
   - 网关额外 slack：`SANDBOX_SCRIPT_GATEWAY_SLACK_MS`，默认 600000ms。
   - 首次建沙箱 + pip install + 脚本执行都包含在外层等待中。

## 常用验证命令

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_sandbox_service.py tests/test_group_chat_skill_script_cli_flow.py tests/test_skill_mcp_and_script_requirements.py tests/test_settings_import_conflict.py'
```

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m py_compile app/agent/sandbox_service.py app/tools/run_skill_script.py app/api/settings_skills.py app/api/settings_mcp.py app/api/sandbox_settings.py'
```

测试后清理缓存：

```bash
/Users/ggd/.local/bin/rtk sh -lc 'find backend -type d -name __pycache__ -prune -exec rm -rf {} +; find backend -type f -name "*.pyc" -delete'
```

## 最近通过的验证

- `tests/test_sandbox_service.py`
- `tests/test_group_chat_skill_script_cli_flow.py`
- `tests/test_skill_mcp_and_script_requirements.py`
- `tests/test_settings_import_conflict.py`
- `tests/test_sessions_api.py`

最近一次组合验证结果：`32 passed`。

## 交接提醒

- 不要只看 Skill 脚本 stdout/stderr，必须同时看 `_sandbox_trace` 中的：
  - `sandbox_id`
  - `image_ref`
  - `installed_requirements_hash`
  - `verified_requirements_hash`
  - `requirements_verifier_version`
- 如果线上报 `skill_python_requirements_bytes=0` 或 requirements 没注入，优先检查：
  - 用户上下文是否存在；
  - `run_skill_script` 是否拿到了 `owner_user_id`；
  - `SandboxService._prepare_command_env` 是否记录了 `st49_sandbox_command_env_injected/present/empty`。
- 如果线上报文件读写失败但命令可执行，优先怀疑 OpenSandbox endpoint 为空或 host/port 不可达。



你是 五九，担任本群主持人。你的角色：群聊主持人。

你是群聊主持人，负责在当前群内专家之间做调度，输出 current_phase、next_speaker、speaker_task 决策，平台会根据调度结果生成固定主持话术，你不得代答、复述用户需求或补充说明。



## 平台调度状态规则

你仍按主持人 Skill 判断下一步调度，你只需要在本轮回复中给出以下结构化结果：

**只输出 JSON（可用 ```json 包裹），不要输出任何面向用户的自然语言。**

```json
{
  "current_phase": "阶段：xxxx",
  "next_speaker": "agent-xxxxxx",
  "speaker_task": "请根据用户目标完成本阶段任务"
}
```

`current_phase` 用于保存当前场景流程阶段；
`next_speaker` 写场景角色id、`"invite"` 、`"user"` 或 `"end"`。
`speaker_task` 平台会把它作为后台任务文本交给下一位发言人执行。
专家发言完成后，平台会先交回主持人调度；这里的 `next_speaker` 是主持人本次调度出的下一步目标，只能是场景内角色id、 `"invite"` 、`"user"` 或 `"end"`。
你必须先判断任务目标是否已经完成：如果上一位专家已经给出明确答案、文件、查询结果或可交付结论，就不要再安排专家做“总结答复”或复述同一结果。
任务已完成且整个会话应结束时：`current_phase` 写 `"end"`，且 `next_speaker` 写 `"end"`。
需要等待用户继续输入时：`next_speaker` 写 `"user"`（平台不会展示主持气泡）。
需要邀请新专家完成任务时：`next_speaker` 写 `"invite"`（平台不会展示主持气泡）。
只有在仍缺关键信息、用户明确要求继续，或存在新的子任务时，才把 `next_speaker` 设为某个专家。



[LLM_ROUNDTRIP][host_decide] user_prompt:
【模式】新建会话（当前已有参与者，先在场内调度）。

【当前群聊参与者（next_speaker 优先写场景角色名或参与者名称；括号内系统 ID 仅供平台匹配兜底）】
- 沙箱依赖验证专家 (agent-sandbox-dep-check): 验证沙箱是否会安装 requirements.txt 中的依赖；运行脚本打印包版本号。
- 音频转文字 (agent-67c81847): 音频转文字
- 图片生成专家 (agent-8d0d15ba): 在网文协同写作中只负责做图大纲确认、图片提示词整理、调用图片生成工具、保存 brief、交付图片链接，并在用户确认后把已生成图片插入文章另存图文版新文件。

【任务目标】
第十六届中心捧月GUIAgent

【主持人决策上下文（对话与发言摘录）】
【用户】第十六届中心捧月GUIAgent.pptx

【主持人】我推荐以下专家加入讨论：

文字创作专家 (核心角色) — 负责与你确认文章方向、搭建大纲、撰写正文、后续的续写/改写/润色。
信息检索专家 (辅助角色) — 如果需要查找资料、核实数据、或者参考其他文章素材，他可以提供支持。
图片生成专家 (可选角色) — 如果文章需要配图，可以在文字完成后请他生成合适的图片并排版。

【主持人】已邀请“沙箱依赖验证专家”加入会话

【主持人】已邀请“音频转文字”加入会话

【主持人】已邀请“图片生成专家”加入会话

【用户】第十六届中心捧月GUIAgent.pptx

【用户】第十六届中心捧月GUIAgent.pptx

【主持人】下面由 音频转文字 发言。

【agent-67c81847】根据当前工作区目录内容，未发现任何音频文件，因此**无需执行音频转写**任务。

当前会话讨论目标是 **"第十六届中心捧月GUIAgent.pptx"**，这是一个PPT文件，不涉及音频转写。

**我的结论：**
- 本角色（音频转文字）暂无可处理的音频文件，本轮发言完毕，释放会话。

【用户】第十六届中心捧月GUIAgent

【用户】第十六届中心捧月GUIAgent

【本轮用户输入】
第十六届中心捧月GUIAgent

【刚发言的专家】agent-67c81847



[LLM_ROUNDTRIP][host_decide] model_output:
```json
{
  "current_phase": "阶段1：入口分流",
  "next_speaker": "user",
  "speaker_task": "用户已多次提及'第十六届中心捧月GUIAgent'，但未明确具体需求（如撰写文章、生成图片、处理PPT等）。请用户明确本次任务的具体目标。"
}
```
