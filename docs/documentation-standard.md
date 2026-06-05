# 文档规范

## 目标

项目文档应同时服务 4 类读者：用户、开发者、测试/验收人员、部署运维人员。每份文档必须有明确归属目录和维护责任，不再使用零散的顶层中文文件名。

## 文件位置

| 文档类型 | 放置目录 | 命名示例 |
|----------|----------|----------|
| 用户需求、验收追踪 | `docs/requirements/` | `user-requirements.md`、`acceptance-and-tests.md` |
| 架构、详细设计、运行链路、接口 | `docs/architecture/` | `system-architecture.md`、`detailed-design.md`、`runtime-architecture.md` |
| 测试用例、回归、上线验收 | `docs/testing/` | `test-case-catalog.md`、`layer1-regression.md`、`pre-release-testing.md` |
| 用户教程、验收手册、截图 | `docs/user-manual/` | `user-guide.md`、`README.md` |
| Skill、MCP、沙箱工具契约 | `docs/skills/` | `skill-standard.md`、`sandbox-tool-interface.md` |
| 部署和运维约束 | `docs/operations/` | `single-user-single-sandbox.md` |
| 项目管理、任务拆分和汇报材料 | `docs/project/`、`docs/presentations/` | `implementation-task-breakdown.md`、`worklist.md`、`15-minute-technical-brief.md` |
| Superpowers 规格和计划 | `docs/superpowers/specs/`、`docs/superpowers/plans/` | `YYYY-MM-DD-topic-design.md` |

## 命名规则

- 文件名使用英文小写、数字和短横线，例如 `pre-release-testing.md`。
- 文档标题使用中文，保持业务可读性。
- 图片和附件放到所属目录的 `images/` 或 `assets/` 下。
- 不提交 `.DS_Store`、临时导出包、构建产物和本地运行状态。

## 变更同步规则

| 变更类型 | 必须同步 |
|----------|----------|
| 用户需求新增或删除 | `requirements/user-requirements.md`、`requirements/acceptance-and-tests.md`、`architecture/detailed-design.md`、`project/implementation-task-breakdown.md` |
| 验收标准变化 | `requirements/acceptance-and-tests.md`、`testing/test-case-catalog.md`、`testing/layer1-regression.md`、`testing/pre-release-testing.md` |
| API 或模块边界变化 | `architecture/detailed-design.md`、`architecture/project-structure.md`、相关 `architecture/*.md` |
| Skill/MCP/沙箱契约变化 | `skills/*.md`、必要时同步 `operations/*.md` |
| 用户操作路径变化 | `user-manual/user-guide.md`、`user-manual/README.md` 和截图脚本 |
| 部署方式变化 | `README.md`、`operations/*.md`、`testing/pre-release-testing.md` |

## 文档质量检查

提交前至少执行：

```bash
git diff --check -- docs
```

涉及代码或测试入口变化时，还需执行对应测试命令；上线前最低门槛见 `docs/testing/pre-release-testing.md`。
