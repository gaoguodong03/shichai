# 文档审计记录

## 2026-06-05 文档规范化

目标：清理 `docs/` 顶层散乱文档，建立长期可维护的文档信息架构，并把关键文档同步到当前实现。

### 已完成

- 建立文档中心：`docs/README.md`。
- 建立文档规范：`docs/documentation-standard.md`。
- 建立文档清单：`docs/project/documentation-inventory.md`。
- 将顶层中文 Markdown 迁移到稳定英文路径：
  - `requirements/`
  - `architecture/`
  - `testing/`
  - `skills/`
  - `operations/`
  - `project/`
  - `presentations/`
  - `user-manual/`
- 更新需求、验收、测试和架构层的 UR-01 到 UR-11 追踪关系。
- 重写当前 API 设计文档，移除“公开 API、暂不认证、旧 `/api/chat`”等过时说明。
- 修正文档相对链接和旧顶层路径引用。
- 修复 `/api/sessions/{session_id}/chat` 非流式聚合返回最后一条主持人消息的问题，使其优先返回 `route.agent_id` 对应专家消息。

### 验证

- `git diff --check -- README.md backend/README.md backend/app/api/sessions.py docs`
- Markdown 相对链接检查：47 个 Markdown，无缺失本地链接。
- `./scripts/test-layer1.sh`
  - 后端：315 passed，86 deselected。
  - 前端：build PASS。

### 当前约定

- `docs/` 顶层只保留 `README.md` 和 `documentation-standard.md`。
- 当前规范文档以 `requirements/`、`architecture/`、`testing/`、`skills/`、`operations/`、`user-manual/` 为准。
- `docs/superpowers/` 保留历史规格和计划。历史文档中可能出现当时的 `/share/run`、`test_public_share_api` 等旧名称，不作为当前产品承诺。

### 后续审计重点

- 继续核对 `architecture/runtime-architecture.md` 和 `architecture/runtime-flow-overview.md` 的细节是否完全贴合当前代码。
- 根据用户手册截图脚本，补齐或更新 `user-manual/images/` 中缺失的截图资产。
- 若后续继续拆分或重构代码，需要同步更新 `architecture/project-structure.md` 和 `testing/layer1-regression.md`。
