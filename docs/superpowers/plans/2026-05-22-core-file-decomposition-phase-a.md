# Core File Decomposition Phase A 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 将 `backend/app/api/settings.py` 中的 session preset / scene bundle / public share import 逻辑拆到 `backend/app/api/settings_presets.py`，保持 API 行为不变。

**架构：** 新模块 `settings_presets.py` 拥有 `/settings/session-presets*` 与 `/settings/shares/{share_id}/import` 路由；`settings.py` 只保留 Skill 相关逻辑和共享 helper。通过导入 helper 的方式先减少迁移风险，后续再拆 Skill 模块。

**技术栈：** FastAPI APIRouter、现有 `session_preset_validate` / `scenario_bundle` / `settings_bundle_import` helper、pytest、conda env `st49`。

---

## 文件结构

- 新建：`backend/app/api/settings_presets.py`
  - Session preset CRUD
  - Scenario bundle export/import
  - Public share import
  - Requirements merge/prewarm call for imported skills
- 修改：`backend/app/api/routes.py`
  - include `settings_presets.router`
- 修改：`backend/app/api/settings.py`
  - 移除迁出的 route 函数，保留 Skill CRUD/share/parts 逻辑
  - 临时保留可复用 helper，直到 Phase B 拆 `settings_skills.py`
- 测试：优先跑现有 settings/import/share 相关测试；如覆盖不足，新增窄测试到 `backend/tests/`

## 任务 1：锁定当前 settings preset 行为

- [x] **步骤 1：查找现有测试**

运行：

```bash
/Users/ggd/.local/bin/rtk rg -n "session-presets|import-bundle|shares/.*/import|publish-share|export-bundle" backend/tests
```

预期：列出现有测试文件；如果没有覆盖 `/settings/session-presets/import-bundle` 或 `/settings/shares/{share_id}/import`，任务 2 需要补测试。

- [x] **步骤 2：运行当前相关测试作为基线**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_settings_import_conflict.py tests/test_public_share_api.py tests/test_frontend_business_flows.py tests/test_sessions_api.py'
```

预期：全部通过。若某测试不存在，记录实际可用测试名，不要跳过同类覆盖。

- [x] **步骤 3：Commit**

本任务只做基线确认，不提交。

## 任务 2：补一个路由保持不变的回归测试

- [x] **步骤 1：编写失败或通过的契约测试**

若现有测试没有覆盖 session preset list/update，新增：

```python
def test_session_presets_routes_remain_available(client):
    response = client.get("/api/settings/session-presets")
    assert response.status_code in {200, 401}
```

根据项目现有 auth fixture 调整 client 使用方式，目标是锁定路由仍然注册，不测试实现细节。

执行记录：现有 `test_frontend_resource_center_and_settings_flow` 已覆盖 session preset `PUT` + `GET`，未新增重复契约测试；私有 helper 测试改为指向 `settings_presets`，迁移前按预期失败于模块缺失。

- [x] **步骤 2：运行测试验证基线**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_settings_import_conflict.py tests/test_public_share_api.py tests/test_frontend_business_flows.py tests/test_sessions_api.py'
```

预期：通过；如果新增测试需要 auth fixture，先修测试，不改生产代码。

- [x] **步骤 3：Commit**

执行记录：本轮根据用户明确要求提交。

```bash
/Users/ggd/.local/bin/rtk git add backend/tests
/Users/ggd/.local/bin/rtk git commit -m "test: 锁定场景预设设置路由契约"
```

## 任务 3：新建 `settings_presets.py` 并迁移 session preset CRUD

- [x] **步骤 1：新建新 router 文件**

从 `settings.py` 迁移以下内容到 `backend/app/api/settings_presets.py`：

- `_get_session_presets_path`
- `_load_session_preset_rows_from_file`
- `_normalize_session_preset_row`
- `_merge_session_presets_into_file`
- `get_session_presets`
- `update_session_presets`

新文件顶部使用：

```python
router = APIRouter(tags=["settings"], dependencies=[Depends(user_context_dependency)])
```

- [x] **步骤 2：注册 router**

在 `backend/app/api/routes.py` 中 include 新 router，保持路径不变。

具体修改：

```python
from app.api import settings_presets

app.include_router(settings_presets.router, prefix="/api")
```

- [x] **步骤 3：运行测试**

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_settings_import_conflict.py tests/test_public_share_api.py tests/test_frontend_business_flows.py tests/test_sessions_api.py'
```

预期：通过。

- [x] **步骤 4：Commit**

执行记录：本轮根据用户明确要求提交。

```bash
/Users/ggd/.local/bin/rtk git add backend/app/api/settings.py backend/app/api/settings_presets.py backend/app/api/routes.py
/Users/ggd/.local/bin/rtk git commit -m "refactor: 拆出场景预设设置路由"
```

## 任务 4：迁移 scenario bundle export/share/import

- [x] **步骤 1：迁移 bundle helper 和路由**

从 `settings.py` 迁移：

- `_session_preset_bundle_zip_for_preset`
- `export_session_preset_bundle`
- `get_session_preset_share_link`
- `publish_session_preset_share`
- `import_session_preset_bundle`
- `import_public_share_bundle`

保留对已有 core helper 的调用，不复制 core 层逻辑。

- [x] **步骤 2：迁移 import 需要的私有 helper**

如果 import bundle 依赖 Skill helper，先从 `settings.py` 导入这些 helper，避免一次性拆 Skill 模块：

```python
from app.api.settings import _skill_conflict_id_map, _merge_imported_skill_requirements_and_prewarm
```

如果出现循环导入，先停止并只迁移无循环依赖的 route；然后新建 `backend/app/core/settings_import_helpers.py`，把 `_skill_conflict_id_map` 和 requirement merge 需要的纯 helper 移入 core，再让两个 API 模块共同引用。

- [x] **步骤 3：运行测试**

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_settings_import_conflict.py tests/test_public_share_api.py tests/test_frontend_business_flows.py tests/test_sessions_api.py'
```

预期：通过。

- [x] **步骤 4：Commit**

执行记录：本轮根据用户明确要求提交。

```bash
/Users/ggd/.local/bin/rtk git add backend/app/api/settings.py backend/app/api/settings_presets.py backend/app/core/settings_import_helpers.py backend/app/api/routes.py
/Users/ggd/.local/bin/rtk git commit -m "refactor: 拆出场景包导入分享路由"
```

## 任务 5：验证、缓存清理和行数复核

- [x] **步骤 1：完整后端相关验证**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m pytest -q tests/test_settings_import_conflict.py tests/test_public_share_api.py tests/test_frontend_business_flows.py tests/test_sessions_api.py tests/test_auth_sqlite.py'
```

预期：全部通过。

- [x] **步骤 2：语法验证**

运行：

```bash
/Users/ggd/.local/bin/rtk conda run -n st49 bash -lc 'cd backend && python -m py_compile app/api/settings.py app/api/settings_presets.py app/api/routes.py'
```

预期：无输出，exit 0。

- [x] **步骤 3：清理缓存**

运行：

```bash
/Users/ggd/.local/bin/rtk sh -lc 'find backend -type d -name __pycache__ -prune -exec rm -rf {} +; find backend -type f -name "*.pyc" -delete'
```

- [x] **步骤 4：行数复核**

运行：

```bash
/Users/ggd/.local/bin/rtk sh -lc 'wc -l backend/app/api/settings.py backend/app/api/settings_presets.py'
```

预期：`settings.py` 明显下降，新增文件职责聚焦。

- [x] **步骤 5：最终提交**

执行记录：本轮根据用户明确要求提交。

如有验证文档或计划状态更新：

```bash
/Users/ggd/.local/bin/rtk git add docs/superpowers/plans/2026-05-22-core-file-decomposition-phase-a.md
/Users/ggd/.local/bin/rtk git commit -m "docs: 更新 settings 拆分执行状态"
```
