# 新窗口开发提示词

把下面内容复制到新 Codex 窗口作为开场提示。

```text
我们在 /Users/ggd/project/shichai 中重构多用户资源存储架构。请先阅读：

1. /Users/ggd/project/shichai/AGENTS.md
2. /Users/ggd/project/shichai/docs/architecture/user-resource-store/README.md
3. /Users/ggd/project/shichai/docs/architecture/user-resource-store/storage-standard.md

目标：
按“方案 A：继续 JSON 文件为主”实现新的用户资源存储标准。身份目录主键改为 user_id，不在主路径兼容旧邮箱目录。资源中心所有一等资源统一放到 backend/data/users/<user_id>/resources/ 下，包括 scenarios、agents、skills、tools、models。settings/ 存应用设置、密钥库和沙箱依赖。sessions/ 只放真实会话历史、工作区和会话检查点。沙箱可以物理挂载当前用户全部 Skill，但逻辑上只注册和暴露本轮场景/专家允许的 Skill 和工具。

关键标准：
- resources/scenarios/<scenario_id>/scenario.json
- resources/agents/<agent_name>/agent.json
- resources/skills/<directory_name>/SKILL.md + scripts/ + assets/ + templates/ + other/
- resources/tools/<tool_id>/tool.json
- resources/models/<model_provider_id>/model.json
- settings/app.json
- settings/secrets.enc.json
- settings/sandbox/requirements.txt
- sessions/<session_id>/session.json + history.json + runtime.json + chat.md + workspace/ + checkpoints/

请先做代码阅读和实现计划，不要直接大改。重点查：
- backend/app/core/user_context.py
- backend/app/core/user_settings_paths.py
- backend/app/api/auth.py
- backend/app/api/settings_skills.py
- backend/app/api/settings_presets.py
- backend/app/api/agents.py
- backend/app/api/group_chat.py
- backend/app/skills/loader.py
- backend/app/tools/run_skill_script.py
- backend/app/agent/sandbox_service.py
- backend/app/agent/sandbox_adapter.py
- frontend/src 里资源中心相关页面
- backend/tests 里 auth、settings、session preset、group chat、sandbox/skill 相关测试

开发要求：
1. 先写一个分阶段实现计划，控制 blast radius。
2. 不要把旧邮箱目录兼容逻辑留在主路径；如果需要旧数据处理，单独设计迁移脚本。
3. 保留现有 API 行为或提供兼容响应层，避免前端一次性大面积崩。
4. 写入 JSON 时使用原子写入，不能注册/保存时清空已有资源。
5. 密钥不能进入 resources、sessions、bundle 或沙箱挂载目录。
6. 沙箱 /skills 可以挂载当前用户全部 resources/skills，但工具注册和模型上下文必须按当前场景/专家白名单收敛。
7. 每一步都加针对性测试，优先覆盖数据路径、导入导出、缺失引用、沙箱工具注册。
8. 工作区可能有用户未提交改动，不要回滚无关文件。

请用中文沟通。先给我实现计划和风险拆分，等我确认后再改代码。
```
