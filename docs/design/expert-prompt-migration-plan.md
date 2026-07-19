# 现有专家提示词迁移实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:executing-plans 在当前工作区逐任务实现此计划。步骤使用复选框跟踪进度。

**目标：** 将指定用户下的三个现有专家迁移到跨场景专家通用提示词模板，同时保留各专家原有专业能力边界。

**架构：** 只修改 `agent.json` 的 `description` 和 `system_prompt`。平台、场景、主持人 Skill、普通 Skill 和其他用户资源均不修改；资源契约通过现有协作资源测试验证。

**技术栈：** JSON、Python、pytest。

---

## 文件范围

- 修改：`backend/tests/test_collaboration_scenario_resources.py`，增加跨场景专家模板契约。
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/信息检索专家/agent.json`，收敛为检索领域边界和质量标准。
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/文档合著专家/agent.json`，补全职责摘要并删除 Skill 工作流。
- 修改：`backend/data/users/user-d8f26bf88991429789b4905ba0ae8040/resources/agents/图片生成专家/agent.json`，收敛为视觉领域边界和质量标准。

## 任务 1：建立资源模板契约

- [x] 在 `backend/tests/test_collaboration_scenario_resources.py` 中读取三个专家并断言：`description` 非空且包含“交付”；`system_prompt` 包含“职责边界”“专业标准”“判断原则”和两条固定判断原则。
- [x] 断言三个专家提示词均不包含场景名称、主持人交接、Skill 名称、工作区规则、最终状态结构或流程控制字段。
- [x] 运行 `rtk pytest -q backend/tests/test_collaboration_scenario_resources.py::test_collaboration_experts_follow_cross_scenario_prompt_template`，预期因现有资源仍含旧文本而失败。

## 任务 2：迁移三个专家资源

- [x] 信息检索专家的 `description` 改为“负责公开资料搜索、公开网页抓取与来源整理，交付可追溯的研究素材。”；`system_prompt` 只保留不处理写作和图片任务、来源可追溯、事实层次清晰及两条通用判断原则。
- [x] 文档合著专家的 `description` 改为“负责结构化文档的规划、合著、修订与打磨，交付符合用户目标的完整文稿。”；`system_prompt` 只保留不处理检索和图片任务、结构适配、内容一致性及两条通用判断原则。
- [x] 图片生成专家的 `description` 改为“负责配图方案、图片生成与图文版装配，交付与内容目标一致的视觉产物。”；`system_prompt` 只保留不处理检索和正文写作、视觉一致性、图文一致性及两条通用判断原则。
- [x] 运行任务 1 的定向测试，预期通过。

## 任务 3：回归验证

- [x] 运行 `rtk pytest -q backend/tests/test_collaboration_scenario_resources.py backend/tests/test_expert_runtime.py backend/tests/test_host_takeover.py`，预期全部通过。
- [x] 使用 `rtk jq -e` 验证三个 `agent.json` 均为合法 JSON 且 `description`、`system_prompt` 非空。
- [x] 运行 `rtk git diff --check`，预期无格式错误。

## 范围外事项

- 不创建流程控制测试专家，因为它依赖尚未确认的普通 Skill 模板和对应 Skill 资源。
- 不迁移其他用户目录。
- 不修改平台运行时、主持人配置、场景资源或普通 Skill 正文。
