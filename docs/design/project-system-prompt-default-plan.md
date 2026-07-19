# 项目整体系统提示词默认模板实现计划

> **面向 AI 代理的工作者：** 使用 test-driven-development 按红灯、绿灯、重构顺序执行；步骤使用复选框跟踪进度。

**目标：** 让未配置 `app_settings.system_prompt` 的设置初始化为已确认的完整可编辑模板，同时保留用户显式保存的任何值。

**架构：** 默认正文作为集中 Prompt 模板登记，由 `project_prompt.py` 提供读取函数；`settings_app.py` 只消费该默认值。前端继续显示后端字段，不维护副本。

**技术栈：** Python、JSON、FastAPI、pytest。

---

### 任务 1：锁定设置初始化契约

**文件：**
- 修改：`backend/tests/test_llm_config.py`

- [x] 添加测试：设置文件不存在时，`load_app_settings()["system_prompt"]` 等于集中默认模板，并包含六个工作区函数名。
- [x] 添加测试：设置文件显式保存 `system_prompt: ""` 后，读取结果仍为空字符串。
- [x] 保留并运行已有非空自定义值测试。
- [x] 运行 `rtk pytest -q backend/tests/test_llm_config.py -k 'app_settings'`，确认新增默认值测试因当前返回空字符串而失败。

### 任务 2：接入唯一默认正文

**文件：**
- 修改：`backend/app/agent/platform_prompt_templates.json`
- 修改：`backend/app/agent/project_prompt.py`
- 修改：`backend/app/api/settings_app.py`

- [x] 在 Prompt 注册表增加无运行时变量的 `project.system.default.v1`。
- [x] 在 `project_prompt.py` 增加 `get_default_project_system_prompt()`，通过 `render_platform_prompt()` 读取默认正文。
- [x] 将 `load_app_settings()` 初始字典中的空字符串替换为该函数返回值；仅在加载文件确实包含 `system_prompt` 时覆盖默认值。
- [x] 重跑任务 1 定向测试，确认全部通过。

### 任务 3：同步契约与回归验证

**文件：**
- 修改：`docs/contracts/prompt-assembly-contract.md`
- 修改：`docs/contracts/data-structure-and-field-logic.md`

- [x] 将项目整体系统提示词章节更新为真实默认正文和缺失字段初始化语义。
- [x] 运行 `rtk pytest -q backend/tests/test_llm_config.py backend/tests/test_platform_prompts.py`。
- [x] 运行 `rtk pytest -q backend/tests/test_docs_contract_alignment.py`。
- [x] 运行 `rtk git diff --check`。
