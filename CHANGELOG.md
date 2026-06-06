# Changelog

## 26.06.06 - 2026-06-06 预发布验收补强

### P0 完成审计

- 对照 UR-01 至 UR-08 完成 P0 任务审计，新增 `docs/project/p0-completion-audit.md`。
- 将 P0 任务的代码、测试和文档证据同步到 `docs/project/implementation-task-breakdown.md`、`docs/testing/test-case-catalog.md` 和文档中心。

### P1 上线验收项

- T-UR09-01：资源包导入 dry-run 预览补充冲突、依赖缺失和 ID 重映射展示。
- T-UR10-01：补强模型、API Key 脱敏和默认主持人配置链路回归。
- T-UR11-01：补强 `/health`、生产静态资源、1Panel 打包和容器冒烟验收。

### 部署与打包

- `pack_1panel_backup.sh` 不再把本地 `.env` 中的密钥、认证库路径、运行输出或缓存打进 1Panel 备份包。
- 生产 `STATIC_DIR` 存在时，`GET /health` 仍返回 `{"status":"ok"}`，不会被 SPA fallback 遮蔽。
- 正式主应用镜像：`crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/dha:26.06.06`。
- 固定普通沙箱镜像：`crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.12.1-standard`。
- 固定 Playwright 沙箱镜像：`crpi-hzqv5l81v3ftz5jl.cn-beijing.personal.cr.aliyuncs.com/free4inno-yuanfang2025/sandbox:26.05.15-playwright`。

### 验证

- 第一层回归：后端 321 passed，前端构建通过。
- 后端全量测试：409 passed。
- 前端生产构建：通过。
- UI 点击级自动化：37 passed。
- Docker/1Panel 冒烟：`st49` 与 `opensandbox-server` 均 healthy，`/health` 接口返回 JSON，8100 登录页可打开。

### 已知警告

- `npm ci` 报告 13 个依赖漏洞，其中 9 个 moderate、4 个 high。
- Browserslist 数据提示过期。
- Vite CSS minify 存在既有 `Expected identifier but found "-"` 警告。
- 前端生产包仍有大 chunk 警告。
